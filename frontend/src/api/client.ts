import { config } from "../config";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type TokenSource = () => string | undefined;

let tokenSource: TokenSource = () => undefined;

// The auth provider registers itself here so plain functions can attach the token
// without every call site threading it through.
export function setTokenSource(source: TokenSource): void {
  tokenSource = source;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = tokenSource();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  const response = await fetch(`${config.apiBaseUrl}${path}`, { ...init, headers });
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    }
  } catch {
    // Not JSON; fall through to the status text.
  }
  return response.statusText || `HTTP ${response.status}`;
}
