import type { ApiErrorBody } from "@/types/api";

/**
 * Base URL of the KayGPT API. Empty (default) means same origin: the browser calls
 * `/api/v1/...` on the Next.js host, which rewrites to the FastAPI backend, keeping the
 * session cookie first-party. Set NEXT_PUBLIC_API_URL only for direct cross-origin mode.
 */
export const API_BASE = `${(process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "")}/api/v1`;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** CSRF token from the last auth response. Lives only in memory for this tab. */
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function buildHeaders(method: string, init?: HeadersInit, json = true): Headers {
  const headers = new Headers(init);
  if (json && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (UNSAFE.has(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  return headers;
}

export async function toApiError(response: Response): Promise<ApiError> {
  let body: Partial<ApiErrorBody> | null = null;
  try {
    body = (await response.json()) as Partial<ApiErrorBody>;
  } catch {
    body = null;
  }
  const error = body?.error;
  return new ApiError(
    response.status,
    error?.code ?? "http_error",
    error?.message ?? `Request failed (${response.status}).`,
    error?.details,
  );
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | null | undefined>;
  signal?: AbortSignal;
}

export function apiUrl(path: string, query?: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

/** JSON request to the API. Throws ApiError for non-2xx responses. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? "GET";
  const isForm = options.body instanceof FormData;
  const response = await fetch(apiUrl(path, options.query), {
    method,
    credentials: "include",
    headers: buildHeaders(method, undefined, !isForm && options.body !== undefined),
    body: isForm
      ? (options.body as FormData)
      : options.body !== undefined
        ? JSON.stringify(options.body)
        : undefined,
    signal: options.signal,
  });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
