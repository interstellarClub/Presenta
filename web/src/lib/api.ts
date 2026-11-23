export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const API_PREFIX = "/api";

async function parseError(response: Response): Promise<ApiError> {
  let code = "request_failed";
  let message = `请求失败 (${response.status})`;
  let details: unknown;
  try {
    const body = (await response.json()) as {
      code?: string;
      message?: string;
      details?: unknown;
      detail?: unknown;
    };
    code = body.code ?? code;
    message = body.message ?? message;
    details = body.details ?? body.detail;
  } catch {
    // non-JSON error body
  }
  return new ApiError(response.status, code, message, details);
}

export async function api<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_PREFIX}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_PREFIX}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    credentials: "include",
    body: JSON.stringify(body ?? {}),
    signal,
  });
  if (!response.ok || !response.body) {
    throw await parseError(response);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      let eventName = "message";
      const dataLines: string[] = [];
      for (const rawLine of block.split("\n")) {
        const line = rawLine.trimEnd();
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length > 0) {
        let payload: unknown = dataLines.join("\n");
        try {
          payload = JSON.parse(payload as string);
        } catch {
          // keep raw text payload
        }
        onEvent(eventName, payload);
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export async function uploadDocument(file: File, title?: string): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  const response = await fetch(`${API_PREFIX}/documents`, {
    method: "POST",
    body: form,
    credentials: "include",
  });
  if (!response.ok) throw await parseError(response);
  return response.json();
}