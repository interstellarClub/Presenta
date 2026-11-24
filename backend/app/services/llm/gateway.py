import json
import re
import time
from typing import Any, TypeVar
from uuid import UUID

import httpx
from pydantic import BaseModel, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import UpstreamError, ValidationFailedError
from app.services.llm import mock
from app.services.llm.metering import UsageLedgerRow, record_usage
from app.services.llm.prompts import load_prompt, render
from app.services.llm.retry import (
    RetryableUpstreamError,
    is_retryable_status,
    sleep_backoff,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

NETWORK_ATTEMPTS = 3


class LLMResponse(BaseModel):
    value: Any
    raw: str
    provider: str
    model: str
    thinking: bool
    attempts: int
    latency_ms: int


def _extract_json(raw: str) -> Any:
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise ValidationFailedError(
                "model output contains no JSON document", details={"raw": raw[:12000]}
            ) from None
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
        raise ValidationFailedError(
            "model output is not valid JSON", details={"raw": raw[:12000]}
        ) from None


def _error_code_for_status(status_code: int) -> str:
    if status_code in (401, 403):
        return "upstream_auth"
    if status_code == 429:
        return "upstream_rate_limit"
    if 500 <= status_code < 600:
        return "upstream_server"
    return "upstream_client"


def _api_key() -> str:
    value = settings.deepseek_api_key
    if value is None:
        return ""
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


async def _post_deepseek(
    messages: list[dict[str, str]], *, thinking: bool, temperature: float
) -> tuple[str, dict[str, Any], str | None]:
    api_key = _api_key()
    headers = {"Authorization": f"Bearer {api_key}"}
    payload: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "temperature": temperature,
        "max_tokens": settings.llm_max_tokens,
        "stream": False,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        for attempt in range(NETWORK_ATTEMPTS):
            try:
                response = await client.post(url, json=payload, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt == NETWORK_ATTEMPTS - 1:
                    raise RetryableUpstreamError(
                        f"deepseek transport error: {type(exc).__name__}",
                        error_code="upstream_transport",
                    ) from exc
                await sleep_backoff(attempt)
                continue
            if response.status_code >= 400:
                error_code = _error_code_for_status(response.status_code)
                if is_retryable_status(response.status_code) and attempt < NETWORK_ATTEMPTS - 1:
                    await sleep_backoff(attempt)
                    continue
                raise RetryableUpstreamError(
                    f"deepseek returned {response.status_code}",
                    status_code=response.status_code,
                    error_code=error_code,
                )
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise RetryableUpstreamError(
                    "deepseek response has no choices", error_code="upstream_empty"
                )
            message = choices[0].get("message") or {}
            content = message.get("content") or ""
            usage = data.get("usage") or {}
            call_id = str(data.get("id") or "") or None
            return content, usage, call_id
    raise RetryableUpstreamError(
        f"deepseek call failed: {type(last_error).__name__ if last_error else 'unknown'}",
        error_code="upstream_transport",
    )


async def _record(
    session: AsyncSession,
    *,
    success: bool,
    latency_ms: int,
    usage: dict[str, Any] | None,
    thinking: bool,
    purpose: str,
    user_id: UUID | None,
    deck_id: UUID | None,
    job_id: UUID | None,
    error_code: str | None,
    provider: str,
    model: str,
    upstream_call_id: str | None = None,
) -> UsageLedgerRow:
    usage = usage or {}
    return await record_usage(
        session,
        provider=provider,
        model=model,
        purpose=purpose,
        thinking=thinking,
        latency_ms=latency_ms,
        success=success,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        user_id=user_id,
        deck_id=deck_id,
        job_id=job_id,
        error_code=error_code,
        upstream_call_id=upstream_call_id,
    )


async def generate_structured(
    session: AsyncSession,
    *,
    purpose: str,
    schema: type[SchemaT],
    system_prompt: str,
    user_prompt: str,
    mock_context: dict[str, Any],
    user_id: UUID | None = None,
    deck_id: UUID | None = None,
    job_id: UUID | None = None,
    thinking: bool | None = None,
    temperature: float = 0.2,
    repair_budget: int | None = None,
) -> SchemaT:
    use_thinking = settings.deepseek_thinking if thinking is None else thinking
    started = time.perf_counter()

    if settings.llm_provider == "mock":
        payload = mock.build_payload(purpose, mock_context)
        try:
            value = schema.model_validate(payload)
            valid = True
            problem = ""
        except ValidationError as exc:
            value = None
            valid = False
            problem = str(exc)
        await _record(
            session,
            success=valid,
            latency_ms=int((time.perf_counter() - started) * 1000),
            usage={
                "prompt_tokens": len(system_prompt + user_prompt) // 4,
                "completion_tokens": len(problem) // 4,
            },
            thinking=use_thinking,
            purpose=purpose,
            user_id=user_id,
            deck_id=deck_id,
            job_id=job_id,
            error_code=None if valid else "mock_invalid",
            provider="mock",
            model="mock",
        )
        if not valid:
            raise ValidationFailedError(
                "mock provider produced payload failing schema validation",
                details={
                    "schema": schema.__name__,
                    "errors": problem[:2000],
                    "raw": json.dumps(payload, ensure_ascii=False)[:12000],
                    "invalid_payload": payload,
                },
            )
        return value  # type: ignore[return-value]

    if not settings.deepseek_api_key_configured:
        raise UpstreamError("DEEPSEEK_API_KEY is not configured on the server")

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_problem = ""
    budget = settings.llm_max_retries if repair_budget is None else max(0, repair_budget)
    max_schema_attempts = budget + 1
    for _schema_attempt in range(max_schema_attempts):
        usage: dict[str, Any] | None = None
        attempt_started = time.perf_counter()
        try:
            result = await _post_deepseek(
                messages, thinking=use_thinking, temperature=temperature
            )
            if len(result) == 3:
                raw, usage, call_id = result
            else:  # 兼容只返回 (content, usage) 的测试替身
                raw, usage = result  # type: ignore[misc]
                call_id = None
        except RetryableUpstreamError as exc:
            await _record(
                session,
                success=False,
                latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                usage=None,
                thinking=use_thinking,
                purpose=purpose,
                user_id=user_id,
                deck_id=deck_id,
                job_id=job_id,
                error_code=exc.error_code,
                provider="deepseek",
                model=settings.deepseek_model,
            )
            raise UpstreamError(str(exc), details={"reason": exc.error_code}) from exc

        try:
            parsed = _extract_json(raw)
            value = schema.model_validate(parsed)
        except (ValidationFailedError, ValidationError) as exc:
            last_problem = str(exc)[:4000]
            await _record(
                session,
                success=False,
                latency_ms=int((time.perf_counter() - attempt_started) * 1000),
                usage=usage,
                thinking=use_thinking,
                purpose=purpose,
                user_id=user_id,
                deck_id=deck_id,
                job_id=job_id,
                error_code="schema_invalid",
                provider="deepseek",
                model=settings.deepseek_model,
                upstream_call_id=call_id,
            )
            messages.append({"role": "assistant", "content": raw[:12000]})
            messages.append(
                {
                    "role": "user",
                    "content": render(
                        load_prompt("llm", "schema_repair"), errors=last_problem
                    ),
                }
            )
            continue

        await _record(
            session,
            success=True,
            latency_ms=int((time.perf_counter() - attempt_started) * 1000),
            usage=usage,
            thinking=use_thinking,
            purpose=purpose,
            user_id=user_id,
            deck_id=deck_id,
            job_id=job_id,
            error_code=None,
            provider="deepseek",
            model=settings.deepseek_model,
            upstream_call_id=call_id,
        )
        return value

    raise ValidationFailedError(
        "model output failed schema validation after repair attempts",
        details={"schema": schema.__name__, "errors": last_problem},
    )