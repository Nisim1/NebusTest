# GitHub Repo Summarizer API

A FastAPI service that takes a public GitHub repository URL and returns a structured, LLM-generated summary: what the project does, which technologies it uses, and how it's organised.

```
POST /summarize  {"github_url": "https://github.com/psf/requests"}
→ { "summary": "...", "technologies": [...], "structure": "..." }
```

---

## Quick Start

```bash
# 1. Clone & enter
cd SolutionNebius

# 2. Create virtual environment & install
python -m venv .venv
source .venv/bin/activate
pip install -e .

# 3. Set your OpenAI key
export OPENAI_API_KEY="sk-..."

# 4. Run
python -m repo_summarizer.main
```

The server starts on **http://localhost:8000**. Test it:

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│              interface/ (FastAPI)                    │  Thin HTTP shell
│  routes.py → schemas.py → error_handlers.py         │
├─────────────────────────────────────────────────────┤
│           infrastructure/ (Adapters)                │  External I/O
│  GitHubRestAdapter        OpenAIAdapter             │
├─────────────────────────────────────────────────────┤
│        services/ (Use Cases & Pure Logic)            │  Business rules
│  summarize_repo  file_filter  file_scorer           │
│  ast_extractor   token_budget  security_sentinel    │
├─────────────────────────────────────────────────────┤
│     domain/ (Entities, Value Objects, Ports)         │  Core contracts
│  GitHubUrl  RepoFile  SummaryResult                 │
│  RepoFetcher (Protocol)  LlmGateway (Protocol)     │
└─────────────────────────────────────────────────────┘
         Dependencies point INWARD only ↑
```

**Clean Architecture rules enforced:**
- Domain defines `Protocol`-based ports (`RepoFetcher`, `LlmGateway`); infrastructure implements them.
- The service layer contains pure, testable logic — no HTTP, no SDK imports.
- The interface layer is a thin shell: parse request → call use case → map response.
- Cross-layer communication uses frozen dataclasses (entities) or Pydantic models (DTOs).

---

## Processing Pipeline

```
Request → Validate URL → Fetch metadata & tree → Filter files
        → Fetch content (async, ≤30 files) → AST skeleton extraction
        → Import-graph centrality scoring → Deterministic token budgeting
        → Security sentinel (redact secrets) → Assemble context
        → Multi-pass LLM summarisation → Structured JSON response
```

### Why each step exists

| Step | What | Why |
|------|------|-----|
| **File filtering** | Skip `node_modules/`, `.git/`, binaries, lock files, files >200 KB | Noise reduction — these files add zero signal for understanding a project |
| **AST skeleton extraction** | Parse Python via `ast`, JS/TS via regex → extract class/function signatures + docstrings | **Information density**: a 500-token skeleton carries more understanding than 500 tokens of raw code. We preserve *what* things are, not *how* they work. |
| **Graph centrality ranking** | Build a directed import graph → compute PageRank → rank files | Files imported by many others are structural pillars. PageRank finds them in O(n+e) — fast and intuitive for "most depended-on" ranking. Falls back to heuristic scoring for non-Python repos. |
| **Deterministic token budgeting** | `tiktoken` (cl100k_base) for exact counts; proportional allocation with rollover | No guessing — every token is accounted for. Budget: README 30%, Config 15%, Tree 10%, Source skeletons 40%, Reserve 5%. Unused slots roll tokens forward. Same repo → same context → reproducible results. |
| **Security sentinel** | Regex-based secret detection + `[REDACTED]` replacement | Never send API keys, tokens, passwords, or private keys to an external LLM. Patterns cover AWS keys, GitHub tokens, JWTs, connection strings, PEM headers, and generic `password=` / `secret=` patterns. |
| **Multi-pass summarisation** | If source content exceeds 2× its budget slot: Pass 1 summarises top files individually, Pass 2 synthesises everything. | Single-pass works for most repos. Multi-pass handles very large repos without crashing or losing information — summarise parts, then combine. |

---

## Model Choice

**GPT-4o-mini** (configurable via `OPENAI_MODEL` env var)

Chosen for its excellent structured JSON output quality and strong performance at code analysis tasks. The `response_format={"type": "json_object"}` mode guarantees parseable output, and `temperature=0.2` keeps summaries factual and deterministic.

---

## Repository Content Strategy

### What we include (in priority order)

1. **README** — 80% of project understanding comes from a good README
2. **Config/metadata** — `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile` reveal the tech stack instantly
3. **Directory tree** — (capped at 200 lines) shows project layout at a glance
4. **Source file skeletons** — AST-extracted class/function signatures with docstrings, ordered by import-graph centrality

### What we skip

- **Vendor/generated**: `node_modules/`, `dist/`, `build/`, `venv/`, `__pycache__/`
- **Binaries**: `.png`, `.jpg`, `.pdf`, `.exe`, `.so`, `.woff`, `.zip`, etc.
- **Lock files**: `package-lock.json`, `yarn.lock`, `poetry.lock`, `Cargo.lock`
- **Large files**: anything >200 KB (configurable)
- **Secret files**: `.env`, `.env.local`, `.env.production`

### Token budget allocation

| Slot | Budget % | Content |
|------|----------|---------|
| README | 30% | Truncated at line boundaries if too long |
| Config files | 15% | Concatenated with headers |
| Directory tree | 10% | Flat indented listing |
| Source skeletons | 40% | AST skeletons ranked by PageRank score |
| Reserve | 5% | Safety margin for prompt overhead |

Unused tokens from earlier slots **roll over** to subsequent slots — no capacity is wasted.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model to use for summarisation |
| `GITHUB_TOKEN` | No | — | GitHub personal access token (raises rate limit from 60 → 5,000 req/h) |
| `MAX_CONTEXT_TOKENS` | No | `12000` | Total token budget for LLM context |
| `MAX_FILE_SIZE_KB` | No | `200` | Skip files larger than this |
| `MAX_FILES_TO_FETCH` | No | `30` | Max files to download per request |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |

---

## API Reference

### `POST /summarize`

**Request:**
```json
{ "github_url": "https://github.com/psf/requests" }
```

**Success response (200):**
```json
{
  "summary": "Requests is a popular Python HTTP library...",
  "technologies": ["Python", "urllib3", "certifi"],
  "structure": "Standard Python package layout with src/requests/, tests/, docs/."
}
```

**Error response (4xx / 5xx):**
```json
{
  "status": "error",
  "message": "Repository not found. Make sure the URL points to a public repository."
}
```

| Status | When |
|--------|------|
| 422 | Invalid URL or empty repository |
| 403 | Private repository |
| 404 | Repository does not exist |
| 429 | GitHub API rate limit exceeded |
| 502 | LLM provider error |

### `GET /health`

Returns `{"status": "ok"}` — simple liveness probe.

---

## Project Structure

```
src/repo_summarizer/
├── main.py                          # Uvicorn entry point
├── domain/
│   ├── entities.py                  # RepoFile, FileNode, SummaryResult, etc.
│   ├── value_objects.py             # GitHubUrl (self-validating)
│   ├── exceptions.py                # Domain exception hierarchy
│   └── ports/
│       ├── repo_fetcher.py          # Protocol: fetch tree & content
│       └── llm_gateway.py           # Protocol: send prompt → get text
├── services/
│   ├── summarize_repo.py            # Main orchestration use case
│   ├── file_filter.py               # Skip/classify heuristics
│   ├── ast_extractor.py             # Python AST + JS regex extraction
│   ├── file_scorer.py               # PageRank + heuristic scoring
│   ├── token_budget.py              # tiktoken-based budget allocator
│   ├── security_sentinel.py         # Secret detection & redaction
│   └── content_assembler.py         # Build structured LLM context
└── infrastructure/
    ├── config.py                    # Pydantic Settings (env vars)
    ├── github_rest_adapter.py       # RepoFetcher → GitHub REST API
    └── openai_adapter.py            # LlmGateway → OpenAI SDK
└── interface/
    ├── app.py                       # FastAPI factory + lifespan
    ├── routes.py                    # POST /summarize (thin controller)
    ├── schemas.py                   # Request / response Pydantic models
    ├── error_handlers.py            # Exception → HTTP status mapping
    └── dependencies.py              # FastAPI Depends() wiring
```
