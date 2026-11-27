# KayGPT API Specification (v1)

Base path: `/api/v1`. In development the interactive OpenAPI docs are at `/api/docs` (disabled in production).

## Conventions

- **JSON** request and response bodies (`Content-Type: application/json`), except uploads (`multipart/form-data`) and the chat stream (`text/event-stream`).
- **IDs** are UUIDs. **Timestamps** are ISO 8601 with UTC offset.
- **Errors** always have this shape:
  ```json
  { "error": { "code": "not_found", "message": "Conversation not found.", "details": null, "request_id": "9f1c…" } }
  ```
  | Status | `code` examples |
  |---|---|
  | 401 | `not_authenticated`, `session_expired`, `invalid_credentials` |
  | 403 | `csrf_failed`, `origin_not_allowed` |
  | 404 | `not_found` (also returned for resources owned by someone else) |
  | 409 | `email_taken` |
  | 413 | `payload_too_large` |
  | 415 | `unsupported_media_type` |
  | 422 | `validation_error` (with `details[]`), `unknown_model` |
  | 429 | `rate_limited` (+ `Retry-After` header) |
  | 500 | `internal_error` (no internal details) |
- Every response carries `X-Request-ID` (echoed if the client sends a valid one).

## Authentication

Cookie-based server-side sessions.

- `POST /auth/register` and `POST /auth/login` set `kaygpt_session` (HttpOnly, `SameSite=Lax` by default, `Secure` in production, 30-day expiry) and return a `csrf_token`.
- Every **state-changing** request (`POST/PUT/PATCH/DELETE`) made with a session must send `X-CSRF-Token: <csrf_token>`. The token is an HMAC of the session token, so it rotates with each login. `GET /auth/me` returns it again (e.g. after a page reload).
- State-changing requests carrying a browser `Origin` header must come from `FRONTEND_URL`/`CORS_ORIGINS` (or the API's own origin).
- Any 401 response clears a stale session cookie.
- Rate limits (per client IP, per minute, per process): auth 10, chat 30, upload 10 (configurable).

### `POST /auth/register` → 201
```json
{ "email": "kay@example.com", "password": "at-least-10-chars", "display_name": "Kay" }
```
Response (`AuthResponse`):
```json
{ "user": { "id": "uuid", "email": "kay@example.com", "display_name": "Kay", "created_at": "…" }, "csrf_token": "hex" }
```
Errors: 409 `email_taken`, 422 (email format, password length 10–128).

### `POST /auth/login` → 200
`{ "email", "password" }` → `AuthResponse`. Error 401 `invalid_credentials` (same message for unknown email and wrong password).

### `POST /auth/logout` → 204
Requires session + CSRF. Deletes the server-side session and clears the cookie.

### `GET /auth/me` → 200
`AuthResponse` for the current session.

## Models

### `GET /models` → 200 (public)
```json
{
  "default_model": "gemini-3.8-flash",
  "models": [
    { "id": "gemini-3.8-flash", "label": "gemini-3.8-flash", "provider": "gemini", "description": "Fast, balanced default", "is_default": true }
  ]
}
```
The list comes from `GEMINI_MODELS`. Unknown ids sent elsewhere are rejected with 422 `unknown_model` (no silent fallback).

## Conversations

All require a session; users only ever see their own rows (others' ids return 404).

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/conversations` | `q` (title search), `limit` (1–100, default 30), `offset` | `Page<Conversation>` newest-updated first |
| POST | `/conversations` | `{ "title"?: str, "model_id"?: str }` | 201 `Conversation` |
| GET | `/conversations/{id}` | | `Conversation` |
| PATCH | `/conversations/{id}` | `{ "title": str (1–200) }` | `Conversation` |
| DELETE | `/conversations/{id}` | | 204. Also deletes messages, the LangGraph checkpoint thread, and the conversation's documents (rows, vectors, files). Memories are kept. |
| GET | `/conversations/{id}/messages` | `limit` (1–200, default 50), `before` (message id cursor) | `MessagePage` |

```json
// Conversation
{ "id": "uuid", "title": "Trip planning", "model_id": "gemini-3.8-flash", "created_at": "…", "updated_at": "…" }
// Page<T>
{ "items": [T], "total": 42, "limit": 30, "offset": 0 }
// MessagePage: the newest `limit` messages before the cursor, returned oldest → newest
{ "items": [Message], "has_more": true }
// Message
{
  "id": "uuid", "conversation_id": "uuid", "role": "user" | "assistant",
  "content": "markdown", "status": "complete" | "stopped" | "error",
  "model_id": "gemini-3.8-flash", "metadata": { "tools": ["web_search"] }, "created_at": "…"
}
```
To page backwards, pass `before = items[0].id` while `has_more` is true.

## Chat streaming

### `POST /chat/stream`
Requires session + CSRF. Request:
```json
{ "conversation_id": "uuid | null", "message": "text (≤ 32000)", "model": "gemini-3.8-flash | null", "regenerate": false }
```
- `conversation_id: null` creates a conversation titled from the message.
- `regenerate: true` (requires `conversation_id`, ignores `message`) re-answers the last user message: the previous answer is removed from the transcript and the agent resumes from the checkpoint before it, so the old answer is not in the model's history either.
- Validation problems (unknown model, missing conversation, blank message) return normal JSON errors **before** the stream starts.

Response: `200 text/event-stream` with `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`.

#### Event protocol
Each event is one SSE frame, `data: <json>\n\n`. Lines starting with `:` are keep-alive comments (sent every `SSE_HEARTBEAT_SECONDS`, default 15 s, while the agent is busy, e.g. during a web search); clients ignore them.

| `type` | Fields | Meaning |
|---|---|---|
| `start` | `conversation_id`, `user_message_id`, `model`, `title` | Always first. Gives the id of a newly created conversation. |
| `token` | `content` | Next piece of assistant text (Markdown). Concatenate in order. |
| `tool_start` | `id`, `name`, `label` | The agent called a tool. `name` ∈ `calculator`, `web_search`, `search_uploaded_documents`, `remember_this`, `recall_memory`; `label` is display text. Tool **arguments are never sent**. |
| `tool_end` | `id`, `name`, `label`, `status` (`success`/`error`) | The tool finished. Tool **output is never sent**. |
| `error` | `code`, `message` | Terminal. Generic, user-safe message; details are only in server logs. |
| `done` | `conversation_id`, `message_id` (null if the model produced no text), `title` | Terminal. The assistant message is already saved. |

Example:
```
data: {"type":"start","conversation_id":"6f…","user_message_id":"a1…","model":"gemini-3.8-flash","title":"What's new in AI?"}

data: {"type":"tool_start","id":"call_1","name":"web_search","label":"Web search"}

: keep-alive

data: {"type":"tool_end","id":"call_1","name":"web_search","label":"Web search","status":"success"}

data: {"type":"token","content":"Here are "}

data: {"type":"token","content":"the latest updates…"}

data: {"type":"done","conversation_id":"6f…","message_id":"b2…","title":"What's new in AI?"}
```

#### Cancellation
Closing the connection (e.g. `AbortController.abort()` for a Stop button) cancels the agent run. The text generated so far is saved as an assistant message with `status: "stopped"` and added to the agent's history, so the next turn continues consistently. Interrupted tool calls are closed with an error result before the next turn.

## Documents

| Method | Path | Body / query | Response |
|---|---|---|---|
| POST | `/documents/upload` | multipart: `file` (required), `conversation_id` (optional) | **202** `Document` with `status: "pending"` |
| GET | `/documents` | `conversation_id` (optional) | `Document[]`: all of the user's documents, or those searchable in that conversation (conversation-scoped + user-wide) |
| GET | `/documents/{id}` | | `Document` (poll for `status`) |
| DELETE | `/documents/{id}` | | 204; removes row, vectors and stored file |

```json
{
  "id": "uuid", "conversation_id": "uuid | null", "filename": "report.pdf",
  "content_type": "application/pdf", "size_bytes": 123456,
  "status": "pending" | "processing" | "ready" | "failed",
  "error_message": "No text could be extracted from this file." | null,
  "chunk_count": 12, "created_at": "…", "updated_at": "…"
}
```
- Scope: with `conversation_id` the document is searchable only in that chat (the original behaviour); without it, in all the user's chats.
- Accepted: `.pdf`, `.docx`, `.txt`, `.md`, `.py`, `.csv`, up to `MAX_UPLOAD_SIZE_MB` (default 20). Content is checked, not just the extension: PDFs must start with `%PDF-`, DOCX must be a valid Word zip (zip-bomb guarded), text files must be UTF-8 without NUL bytes. Encrypted PDFs fail ingestion.
- Errors: 413 too large, 415 unsupported/invalid content, 422 empty file, 404 conversation not owned.
- Client filenames are display-only; storage keys are generated server-side.

## Memory

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/memory` | `q` (optional semantic query), `limit` (≤100), `offset` | `Page<Memory>`: newest first, or, with `q`, ranked by relevance with `score` = cosine distance (lower is closer) |
| POST | `/memory` | `{ "content": str (1–2000) }` | **201** `{ "memory": Memory, "created": true }`, or **200** with `created: false` when it duplicates an existing memory (same text ignoring case/whitespace, or semantically near-identical) |
| DELETE | `/memory/{id}` | | 204 |

```json
{ "id": "uuid", "content": "I prefer metric units", "source": "agent" | "user" | "imported", "conversation_id": "uuid | null", "created_at": "…", "score": 0.12 | null }
```

## Preferences

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/preferences` | | `Preferences` (created with defaults on first read) |
| PUT | `/preferences` | any subset of `{ "default_model", "theme", "settings" }` | `Preferences` |

```json
{ "default_model": "gemini-3.1-pro-preview" | null, "theme": "system" | "light" | "dark", "settings": {} }
```
`default_model` must be a known model id (422 `unknown_model`). `settings` is a free-form object (≤ 4 KB).

## Health

| Path | Use | Response |
|---|---|---|
| `GET /health` | Liveness (Render/Docker health checks) | `{"status":"ok","version":"2.0.0","checks":{}}` |
| `GET /health/ready` | Readiness | `checks.database`, `checks.vector_store`; **503** if the database is unreachable, `status: "degraded"` if only the vector store is |
