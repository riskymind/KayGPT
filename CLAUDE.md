# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

KayGPT: a single-process agentic chatbot. FastAPI serves a Jinja2 single-page UI (`templates/index.html`) and an SSE chat endpoint backed by a LangGraph agent using Google Gemini, with tools for RAG over uploaded files (ChromaDB), Tavily web search, long-term memory (SQLite), and a calculator.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt   # also needs `certifi` (imported by app.py/agent.py/rag.py but not pinned)
python app.py                     # uvicorn on 0.0.0.0:8080 with reload=True
python test.py                    # smoke test: streams one message through the agent (calls Gemini, needs API keys)
```

There is no test suite, linter, or formatter configured. `test.py` is a manual script, not pytest.

Required `.env` in the project root: `GOOGLE_API_KEY`, `TAVILY_API_KEY`; optional `LANGSMITH_*` vars. Note: the README documents `GOOGLE_MODEL`, but `agent.py` actually reads `GEMINI_MODEL` for the default model.

The README describes Docker and a GitHub Actions → ECR → EC2 deploy, but no `Dockerfile` or `.github/workflows/` exist in this tree yet.

## Architecture

Request flow for `POST /chat/stream` ([app.py](app.py)):
1. Body `{message, thread_id, model}`. `get_agent(model)` ([agent.py](agent.py)) returns a compiled graph cached per model name; unknown model names fall back to the default via `ALLOWED_MODELS`.
2. The conversation row and the user message are written to SQLAlchemy tables ([database.py](database.py)).
3. `set_current_thread_id(thread_id)` sets a **module-level global** in [tools.py](tools.py). The RAG and memory tools use this global to scope results per thread, because LangChain `@tool`s don't receive the thread id. This is not safe under concurrent requests; keep it in mind when touching tools.
4. `agent.stream(..., stream_mode="messages")` is filtered by `should_stream_chunk` so only plain AI text tokens (no tool calls or tool outputs) go to the client as SSE `data: {"token": ...}`, followed by `{"done": true}`. The accumulated answer is saved as the assistant message.

Graph: `START → chatbot ⇄ tools` (prebuilt `ToolNode` + `tools_condition`). The system prompt is prepended on every chatbot call and not stored in state.

### Two separate persistence layers (both under `data/`)
- `data/langgraph_checkpoints.sqlite`: LangGraph `SqliteSaver` checkpointer, keyed by `thread_id`. This is the agent's actual conversational memory.
- `data/chatbot_memory.db`: SQLAlchemy tables `conversations`, `chat_messages` (UI sidebar and `/history` only, never fed back to the LLM) and `long_term_memory` (`remember_this`/`recall_memory` tools; `search_memory` ignores the query and returns the latest 20 entries for the thread).

Deleting one store without the other leaves the UI history and the agent's memory out of sync.

### RAG ([rag.py](rag.py))
`/upload` saves the file to `uploads/{uuid}_{name}`, extracts text (pdf/docx/txt/md/py/csv), splits it into chunks of 900 with 150 overlap, and adds them to the Chroma collection `agentic_chatbot_docs` in `chroma_db/` with `metadata.thread_id`. Retrieval filters by `thread_id`, so documents are only visible within the conversation they were uploaded to. Embeddings: `gemini-embedding-001`.

### Import-time side effects
`rag.py` builds the embeddings client and Chroma store at import time, and `tools.py` builds the Tavily client at import time. Importing `app`, `agent`, or `tools` therefore requires valid API keys in the environment. Each entry module calls `load_dotenv()` and sets `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` to certifi before importing the LangChain libraries. Keep that ordering if you add modules.

All paths (`data/`, `uploads/`, `chroma_db/`, `templates/`) are relative to the CWD, so run from the repo root.

### Frontend
`templates/index.html` is a single file with inline JS that calls `/conversations`, `/history/{thread_id}`, `/upload` (multipart with `thread_id`), and `/chat/stream`, parsing the SSE stream manually through `fetch` + `ReadableStream`. If you change the SSE payload shape, update both sides.
