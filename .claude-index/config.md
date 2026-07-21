# Index Configuration

## Excluded Directories
- node_modules
- .git
- .next
- out
- __pycache__
- .venv / venv
- .pytest_cache
- dist / build
- .agentmesh
- .claude
- .idea / .vscode

## Priority Directories
- backend/ (Flask REST API — models, routes, services)
- frontend/ (Next.js App Router — app, components, lib, hooks)

## Tech Stack
- Frontend: Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, @dnd-kit, SWR
- Backend: Python Flask, SQLAlchemy 2, Flask-JWT-Extended, Flask-CORS
- LLM (optional): AGENT_LLM_* env — Anthropic Messages / OpenAI-compatible, over stdlib urllib (no third-party HTTP dep)
- Persistence: SQLite (backend/aragon.db, WAL + synchronous=NORMAL, auto-created + seeded on first run)
- Language: Python (~55%), TypeScript (~45%)

## Index Settings
- Generated: 2026-07-20
- Project Root: M:\takoAI\AragonTeam
- Index Version: 1.0
- Environments Configured: No
- Backend test baseline at generation: 371 collected (pytest --collect-only)

## Clean Code Settings
- Enabled: Yes
- Preset: strict
- MAX_FILE_LINES: 800
- MAX_METHOD_LINES: 50
- MAX_FUNCTION_PARAMS: 5
- MAX_CYCLOMATIC: 10
- MAX_LINE_LENGTH: 80
- MAX_NESTING_DEPTH: 4

> Note: `strict` preset intersected with the polyglot language-minimum
> (TypeScript ∩ Python) — Python's tighter file/method/line caps win, so the
> final values (800 / 50 / 80) are stricter than the strict-preset defaults.
