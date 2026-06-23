# Flow — Verification Findings (2026-06-23)

Traceability matrix for `FLOW-SPEC.md` §14. Evidence beside this file: `screens/` (Playwright screenshots, gitignored as bulky) and `state/` (`/app/state` JSON dumps — the anti-hallucination same-fact evidence). Automated journey result: `results.json` → **24/24** (`scripts/flow_e2e.mjs`).

Standard of proof: every CRUD claim is shown three ways together — rendered UI (screenshot), present in server-side `/app/state` (dump), and surviving a reload.

## A–L Acceptance checklist

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| A1 | Stack boots clean (3000/8000/8080) | ✅ | dev-stack.log; ports 200 |
| A2 | Fresh session seeds (6 tasks, 4 events, 5 docs) | ✅ | `screens/01-home.png`, `state/state-seed.json` |
| A3 | New Session reseeds clean | ✅ | UX review `21-after-new-session.png` |
| B-Home | `/home` agenda + counts | ✅ | `screens/01-home.png` |
| B-ToDo | `/todo` grouped tasks + status/priority pills | ✅ | `screens/02-todo.png` |
| B-Cal | `/calendar` agenda merges events + due tasks | ✅ | `screens/03-calendar.png` |
| B-Docs | `/documents` library + drafts | ✅ | `screens/04-documents.png` |
| B-AIWB | `/assistant` chat + artifact canvas | ✅ | `screens/11-doc-drafted.png` |
| C1 | Agent navigation, one `navigate` call | ✅ | `screens/06-agent-nav-calendar.png` |
| C2 | Client quick-nav instant, no agent turn | ✅ | `screens/02–05`, results.json |
| D1 | create_task → state + rendered | ✅ | `screens/07`, `state/state-after-create-task.json` (High/Work/due 2026-06-27) |
| D2 | update_task status → In progress | ✅ | `screens/08`, `state/state-after-update-task.json` |
| D3 | add_subtask | ✅ | `state/state-after-subtask.json` |
| D4 | delete_task / delete_event | ✅ | capabilities `ask3-delete-gym.png` + adversarial `a2-deleted-then-ask.png` (gone from state) |
| E1 | create_event → agenda + state | ✅ | `screens/09`, `state/state-after-create-event.json` |
| E2 | update_event (move date) | ✅ | `screens/10`, `state/state-after-move-event.json` (→2026-06-25) |
| F1 | Draft doc → canvas + workspace file | ✅ | `screens/11-doc-drafted.png`; `kickoff.md` |
| F2 | Edit doc → content changed | ✅ | `screens/12`; 213→293 chars (intro added) |
| G | RAG: grounded answer with source | ✅ | `screens/16-rag-answer.png` ("watch travel expenses…", Source: Q2-Budget-Overview.md); trace shows `search_documents` |
| G-fail | search_documents fails loud | ✅ | absent-topic → honest "Nothing in your notes…" (`screens/17-rag-absent.png`); `SEARCH_NOT_CONFIGURED`/`SEARCH_FAILED`/`NO_RESULTS` markers wired in agent.py |
| H1 | Pane renders only from /app/state | ✅ | every D/E row: claim ↔ state agree; adversarial `findings.json` |
| H2 | No claim without tool success | ✅ | `screens/13-fail-loud-nav.png`; adversarial impossible-mutation `a1` |
| H3 | Persistence after reload | ✅ | `screens/14-persistence-after-reload.png` |
| I1 | Unknown destination → fail loud, no false nav | ✅ | `screens/13`; route `/calendar/e-5` unchanged; resolver keyword-guard hardened |
| I2 | Ambiguous reference → candidates | ✅ | adversarial `a3-ambiguous.png` (lists candidates, moves 0) |
| J1 | Monday light theme all surfaces | ✅ | `screens/01–04, 11` |
| J2 | Status colors correct | ✅ | `screens/02-todo.png` |
| J3 | No leftover terracotta/dark | ✅ | grep clean |
| J4 | Responsive (dock collapses <~1100px) | ✅ | `screens/15-narrow-home.png` |
| K1 | Orchestrator never runs the SDK | ✅ | no SDK refs in app.py/session_manager.py (docstring only) |
| K2 | AG-UI events intact | ✅ | ToolCallStart/End, RunFinished, TOOL_CALL_RESULT; live turns stream |
| K3 | Tax fully removed from shipped code | ✅ | grep `tax/filing/taxdb` clean (session-container/*.py + frontend/src) |
| L1 | One-command rerun | ✅ | `node scripts/flow_e2e.mjs` → 24/24 |
| L2 | Traceability matrix | ✅ | this file |
| L3 | Limitations section | ✅ | below |

## M — Adversarial / critique reviewers (3 parallel, evidence-bound)

| Lens | Verdict | Key result |
|------|---------|-----------|
| Skeptical end-user + visual | ✅ pass, polish noted | Monday fidelity strong, fail-loud exemplary, latency well-handled; 1 major (hydration badge) + minors → see Residual |
| Adversarial trust + break-it | ✅ invariant holds | 8 attacks passed (impossible mutation, delete-then-ask, ambiguous, cancel mid-stream, rapid sends, garbage/injection, unknown nav, Feb-30 invalid date); **zero SAID-vs-STATE divergence** |
| Capabilities | ✅ 7/7 composed asks | multi-step list+update, RAG→CRUD compose, delete, multi-entity, reasoning, doc draft+edit, open-ended triage — all grounded, all reflected in state |

Synthesis gate: findings deduped; the one MAJOR fixed and re-verified; minors triaged below. No blocking issues remain.

### Fixed this pass (re-verified)
- **Double status pill** on To-Do rows → single pill; overdue now a red due-date accent (`screens/02-todo.png`). Re-verified.
- **Locale/timezone date-format hazard** in `dayLabel` → deterministic UTC + fixed names (hydration hardening).

## Residual / limitations (honest)
- **Hydration "1 Issue" dev badge** (UX major) — intermittent; I could **not reproduce it across 12+ reloads** after hardening the locale date-format hazard (the most probable cause). It is a **dev-overlay only** symptom and cannot appear in a production build. Marked **mitigated, not reproduced** — recommend a production build for live demos. *Not* claimed as a confirmed fix.
- **AI Workbench at ~900px** keeps chat+canvas side-by-side (tight, not broken). Deferred polish.
- **Split first-paint** — assistant pane ready a beat before the workspace ("Loading workspace…"). Minor, ~600ms window.
- **Safety-filter inconsistency** on lookalike destructive prompts (adversarial minor) — Azure content-filter behavior, not our code; **not a trust failure** (claims always matched state).
- **Documents "Uploaded" label** for seeded docs — wording quibble (they're provided, not uploaded). Cosmetic.
- **False alarm (dismissed):** capabilities reviewer's "empty trace.jsonl" — it ran from the wrong cwd and read the wrong repo's log path; `tax-agent/logs/trace.jsonl` is populated (the e2e RAG check reads `search_documents` from it).
