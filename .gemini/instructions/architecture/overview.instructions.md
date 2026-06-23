---
name: architecture:overview
description: System architecture overview for the RFP Agent — tiers, services, key design decisions.
---

# System Overview

```
Frontend (Next.js 16, App Router)     :3000
    ↓ HTTP + SSE
Orchestrator (FastAPI)                :8000   [app.py, session_manager.py]
    ↓ SSE stream proxy
Session Container (FastAPI)           :8080   [session-container/server.py, agent.py]
    ↓ CopilotClient (github-copilot-sdk)
Azure OpenAI
```

## Key Design Decisions

- **Orchestrator never runs the SDK.** It proxies SSE from the session container's `/chat/stream` to the frontend line-by-line with no buffering.
- **One container per user in production** via an ACA Sandbox (`Microsoft.App/SandboxGroups`, microVM-isolated; public preview — the newer ACA *Sandboxes* primitive, not the older Dynamic Sessions pool). Locally, a single shared container serves all sessions — `/reset` is called on each new session to simulate isolation.
- **Sessions tracked in-memory only.** No database. Lost on orchestrator restart; frontend restores via `GET /sessions/{id}` which probes the container pool.
- **AG-UI protocol** for SSE events (from the `ag_ui` package). Session container emits typed events; frontend `Chat.tsx` reducer dispatches them.
- **Auth forwarding:** Orchestrator fetches a Cognitive Services token and forwards it to the session container via `X-Cogservices-Token` header. Session containers use this token (or `DefaultAzureCredential` locally) to call Azure OpenAI.

## Key Files by Tier

**Orchestrator (root/)**
- `app.py` — FastAPI endpoints: session CRUD, message streaming, file upload
- `session_manager.py` — SSE proxy, session set management, auth token forwarding
- `content_processing.py` — ADLS + Azure Content Understanding integration

**Session Container (session-container/)**
- `server.py` — FastAPI endpoints: `/chat/stream`, `/upload`, `/files`, `/files/content`, `/reset`, `/health`; holds `AgentSession` as module-level singleton
- `agent.py` — `AgentSession` wrapping `CopilotClient`; translates SDK events to AG-UI; asyncio.Queue-based event pipeline
- `skills/` — 10 markdown skill files loaded by the Copilot SDK (bid-no-bid, requirements, strategy, drafting, exec summary, compliance, risk/gap, pricing, customer intelligence, iterative refinement)

**Frontend (frontend/src/)**
- `components/Chat.tsx` — main state machine (`useReducer`), session lifecycle, SSE handling
- `lib/sse.ts` — SSE stream parser
- `lib/api.ts` — backend HTTP client (`NEXT_PUBLIC_API_URL` → orchestrator)
- `lib/session.ts` — `sessionStorage`-backed session persistence

## Conventions

- **Python:** async everywhere — FastAPI + httpx + azure SDK async clients
- **Frontend:** React 19, Tailwind CSS 4, TypeScript strict mode, `data-testid` attributes for Playwright selectors
- **Two separate uv projects:** root (orchestrator) and `session-container/` — each has its own `pyproject.toml` + `uv.lock`
- **WORKSPACE env var** controls where uploaded files land in the session container
- **Docker/Dockerfiles** exist for CI/Azure DevOps only — not used for local dev
- **Agent output formats:** markdown (`.md`) for narrative deliverables, CSV for matrices/tables, JSON for structured data. No binary formats (DOCX, PDF, XLSX).
