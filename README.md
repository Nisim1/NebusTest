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

# 3. Configure environment
cp .env.example .env
# Open .env and set your OPENAI_API_KEY (required)
# Adjust PORT, HOST, or any other variable as needed

# 4. Run
python -m repo_summarizer.main
```

The server starts on **http://localhost:8000** (or whatever `PORT`/`HOST` you set in `.env`). Test it:

```bash
curl -X POST http://localhost:8000/summarize \
  -H "Content-Type: application/json" \
  -d '{"github_url": "https://github.com/psf/requests"}'
```

---

## Environment Variables

All configuration is loaded from the `.env` file (copy `.env.example` to get started).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | **Yes** | — | OpenAI API key |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | Model used for summarisation |
| `GITHUB_TOKEN` | No | — | GitHub personal access token (raises rate limit from 60 → 5,000 req/h) |
| `MAX_CONTEXT_TOKENS` | No | `32000` | Total token budget for LLM context |
| `MAX_FILE_SIZE_KB` | No | `200` | Skip files larger than this (KB) |
| `MAX_FILES_TO_FETCH` | No | `30` | Max files to download per request |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG` / `INFO` / `WARNING` / `ERROR`) |
| `HOST` | No | `0.0.0.0` | Interface the server binds to |
| `PORT` | No | `8000` | Port the server listens on |

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

The project follows **Clean Architecture**:
- **Domain** defines `Protocol`-based ports (`RepoFetcher`, `LlmGateway`); nothing here imports from infrastructure or interface.
- **Services** contain pure, testable business logic — no HTTP clients, no SDK imports.
- **Infrastructure** implements the ports (GitHub REST, OpenAI SDK). Swapping providers means changing one adapter file.
- **Interface** is a thin FastAPI shell: parse request → call use case → map response.
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

### Design decisions

| Step | What | Why |
|------|------|-----|
| **File filtering** | Skip `node_modules/`, `.git/`, binaries, lock files, files >200 KB | Noise reduction — these files add zero signal for understanding a project |
| **AST skeleton extraction** | Parse Python via `ast`, JS/TS via regex → extract class/function signatures + docstrings | **Information density**: a 500-token skeleton carries more understanding than 500 tokens of raw code. We preserve *what* things are, not *how* they work. |
| **Graph centrality ranking** | Build a directed import graph → compute PageRank → rank files | Files imported by many others are structural pillars. PageRank finds them in O(n+e) — fast and intuitive for "most depended-on" ranking. Falls back to heuristic scoring for non-Python repos. |
| **Deterministic token budgeting** | `tiktoken` (cl100k_base) for exact counts; proportional allocation with rollover | No guessing — every token is accounted for. Budget: README 30%, Config 15%, Tree 10%, Source skeletons 40%, Reserve 5%. Unused slots roll tokens forward. Same repo → same context → reproducible results. |
| **Security sentinel** | Regex-based secret detection + `[REDACTED]` replacement | Never send API keys, tokens, passwords, or private keys to an external LLM. Patterns cover AWS keys, GitHub tokens, JWTs, connection strings, PEM headers, and generic `password=` / `secret=` patterns. |
| **Multi-pass summarisation** | If source content exceeds 2× its budget slot: Pass 1 summarises top files individually, Pass 2 synthesises everything | Single-pass works for most repos. Multi-pass handles very large repos without crashing or losing information — summarise parts, then combine. |
| **GPT-4o-mini default** | `response_format={"type": "json_object"}` + `temperature=0.2` | Guarantees parseable structured output. Low temperature keeps summaries factual and deterministic. |

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
├── infrastructure/
│   ├── config.py                    # Pydantic Settings (env vars + .env file)
│   ├── github_rest_adapter.py       # RepoFetcher → GitHub REST API
│   └── openai_adapter.py            # LlmGateway → OpenAI SDK
└── interface/
    ├── app.py                       # FastAPI factory + lifespan
    ├── routes.py                    # POST /summarize (thin controller)
    ├── schemas.py                   # Request / response Pydantic models
    ├── error_handlers.py            # Exception → HTTP status mapping
    └── dependencies.py              # FastAPI Depends() wiring
```
