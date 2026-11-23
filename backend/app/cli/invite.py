import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.security import invite_code_hash, new_invite_code
from app.db.models import InviteCode, InviteRedemption, UsageLedger
from app.db.session import SessionFactory


async def create_invite(
    session: Any,
    *,
    label: str | None = None,
    uses: int = 1,
    ttl_days: int | None = None,
    created_by: UUID | None = None,
) -> tuple[InviteCode, str]:
    raw_code = new_invite_code()
    row = InviteCode(
        code_hash=invite_code_hash(raw_code),
        label=label,
        max_uses=max(1, uses),
        used_count=0,
        expires_at=(
            datetime.now(UTC) + timedelta(days=ttl_days) if ttl_days else None
        ),
        created_by=created_by,
    )
    session.add(row)
    await session.flush()
    return row, raw_code


async def list_invites(session: Any) -> list[dict[str, Any]]:
    rows = (
        await session.scalars(select(InviteCode).order_by(InviteCode.created_at.desc()))
    ).all()
    result: list[dict[str, Any]] = []
    for row in rows:
        redemptions = len(
            (
                await session.scalars(
                    select(InviteRedemption).where(InviteRedemption.code_id == row.id)
                )
            ).all()
        )
        ledger_count = len(
            (
                await session.scalars(
                    select(UsageLedger)
                    .join(InviteRedemption, InviteRedemption.user_id == UsageLedger.user_id)
                    .where(InviteRedemption.code_id == row.id)
                )
            ).all()
        )
        result.append(
            {
                "id": str(row.id),
                "label": row.label,
                "maxUses": row.max_uses,
                "usedCount": row.used_count,
                "redemptions": redemptions,
                "modelCalls": ledger_count,
                "expiresAt": row.expires_at.isoformat() if row.expires_at else None,
                "revokedAt": row.revoked_at.isoformat() if row.revoked_at else None,
            }
        )
    return result


async def revoke_invite(session: Any, code: str) -> bool:
    row = await session.scalar(
        select(InviteCode).where(InviteCode.code_hash == invite_code_hash(code))
    )
    if row is None:
        return False
    row.revoked_at = datetime.now(UTC)
    await session.flush()
    return True


async def _run(args: argparse.Namespace) -> int:
    async with SessionFactory() as session:
        if args.command == "create":
            row, raw = await create_invite(
                session,
                label=args.label,
                uses=args.uses,
                ttl_days=args.ttl_days,
            )
            await session.commit()
            print(f"invite created id={row.id} label={row.label} maxUses={row.max_uses}")
            print(f"code: {raw}")
            print("明文仅显示这一次，请立即转交使用者。")
            return 0
        if args.command == "list":
            for item in await list_invites(session):
                print(
                    f"{item['id']}  label={item['label']}  uses={item['usedCount']}/{item['maxUses']}"
                    f"  calls={item['modelCalls']}  expires={item['expiresAt']}  revoked={item['revokedAt']}"
                )
            return 0
        if args.command == "revoke":
            ok = await revoke_invite(session, args.code)
            await session.commit()
            print("revoked" if ok else "invite not found")
            return 0 if ok else 1
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli.invite")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create an invite code")
    create.add_argument("--label", default=None)
    create.add_argument("--uses", type=int, default=1)
    create.add_argument("--ttl-days", type=int, default=None)

    sub.add_parser("list", help="list invite codes with usage")

    revoke = sub.add_parser("revoke", help="revoke an invite code")
    revoke.add_argument("code")

    args = parser.parse_args(argv)
    if settings.app_env == "prod" and settings.secret_key.startswith("dev-insecure"):
        print("refusing to run with the development SECRET_KEY in prod")
        return 2
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())