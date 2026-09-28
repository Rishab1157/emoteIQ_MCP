# emoteIQ Reviews

An MCP server that fetches app reviews in batches for AI agents, plus a CrewAI agent that uses it.

An agent asks for reviews (for example 1,000 Brawl Stars reviews, 50 at a time). The server fetches them from Google Play in the background, keeps the exact responses in MongoDB, parses them into one common review shape, and hands the agent one batch per `get_batch` call. Every request and every failure is logged to Kafka under the job ID.

```
emoteIQ_MCP/
├── emoteIQ_MCP/        MCP server (Python 3.14, uv project)
├── emoteIQ_Agent/      CrewAI agent for end-to-end testing (Python 3.13, uv project)
└── .vscode/launch.json Debug configs: "MCP Server", "Agent", "MCP Server + Agent"
```

---

## 1. Run it

**You need:** Docker Desktop running, [uv](https://docs.astral.sh/uv/), and the Ollama server the agent uses (`http://192.168.3.90:11434`, model `qwen2.5:14b`).

```powershell
# 1. MongoDB + Kafka (once; they keep running)
cd emoteIQ_MCP
docker compose up -d

# 2. MCP server  ->  http://127.0.0.1:8000/mcp
uv run python -m emoteIQ_reviews.McpServer

# 3. In a second terminal: the agent
cd emoteIQ_Agent
uv run python agent.py
```

Or open this top folder in VS Code, go to **Run and Debug**, pick **MCP Server + Agent** and press F5. The agent waits up to 30 s for the server to come up.

> Start the server with `python -m emoteIQ_reviews.McpServer`, not `uv run emoteIQ-reviews`. On this PC, Windows Application Control blocks the `.exe` launcher that uv generates.

---

## 2. The big picture

```
 emoteIQ_Agent   agent.py (CrewAI) + client.py (mcp SDK)
       │   ▲
       │   │   MCP over Streamable HTTP
       │   │   POST http://127.0.0.1:8000/mcp
       ▼   │   (tool results + progress messages)
 ┌────────────────────────────────────────────────┐
 │ emoteIQ_MCP  (one Python process)              │
 │                                                │
 │ McpServer/Tools.py   the 5 MCP tools           │
 │      │                                         │
 │      │ start_review_job → tasks.start(job)     │
 │      ▼                                         │
 │ Runner/   one background task per job          │
 │ TaskManager → JobRunner → Fetcher → Batcher    │
 │      │                                         │
 │      ▼                                         │
 │ Sources/GooglePlay ── HTTPS ──▶ Google Play    │
 └──────┬─────────────────────────────────────────┘
        │ writes                  ▲ get_batch and job_status read
        ▼                         │
  MongoDB   jobs · raw_pages · reviews · batches
  Kafka     job.events · fetch.events · fetch.failures · parse.errors
```

The two halves of the server never call each other directly:

- **The job runner** (background task) *writes* pages, reviews and batches to MongoDB.
- **The tools** (`get_batch`, `job_status`) *read* them from MongoDB.

That is why a batch the agent asks for is usually already waiting: the runner works up to 2 pages ahead.

---

## 3. What happens in one job, step by step

Example: the agent asks for 1,000 Brawl Stars reviews, 50 per batch. File paths are relative to `emoteIQ_MCP/src/emoteIQ_reviews/`.

### Step 1: the agent starts a job
`start_review_job(source="Google Play", filters={"app_id": "com.supercell.brawlstars"}, limit=1000, batch_size=50)`

| Where | What happens |
|---|---|
| [McpServer/Tools.py](emoteIQ_MCP/src/emoteIQ_reviews/McpServer/Tools.py) `start_review_job` | Checks `batch_size` (1–200). |
| [Sources/\_\_init\_\_.py](emoteIQ_MCP/src/emoteIQ_reviews/Sources/__init__.py) `get_source` | `"Google Play"` → `GooglePlaySource`. |
| [Sources/GooglePlay/GooglePlayFilters.py](emoteIQ_MCP/src/emoteIQ_reviews/Sources/GooglePlay/GooglePlayFilters.py) | Validates the filters, fills defaults (`lang=en`, `country=us`, `sort=NEWEST`), rejects unknown keys and `stars` + `sentiment` together. |
| [Storage/Jobs.py](emoteIQ_MCP/src/emoteIQ_reviews/Storage/Jobs.py) `create_job` | Saves the job document (`status: running`, id from `ObjectId()`). |
| [Runner/TaskManager.py](emoteIQ_MCP/src/emoteIQ_reviews/Runner/TaskManager.py) `tasks.start` | Starts the job runner as a background asyncio task. |
| Tool returns | `{"job_id": "...", "status": "running", ...}` right away. Fetching goes on in the background. |

### Step 2: the runner loads the job
[Runner/JobRunner.py](emoteIQ_MCP/src/emoteIQ_reviews/Runner/JobRunner.py) `JobRunner.load` then `run()`

- Reads the job back from MongoDB, picks the source and its config (page size 150, 3 retries).
- Rebuilds the **batcher**. For a new job it is empty. After a crash it rebuilds the reviews that were fetched but not yet batched from `raw_pages` (`Storage/RawPages.py` `pending_review_ids`) and continues batch numbering.
- Picks the token to start from: its own `continuation_token`, or the parent's token for a continuation, or none (page 1).
- Logs `job.events: started` to Kafka.

### Step 3: the page loop, once per Google page
`JobRunner.run_pages`, repeated until `limit` is reached or Google has no more reviews:

1. **`wait_for_reader`**: pauses while `fetched − served_batches × batch_size ≥ 2 × 150` (the agent is 2 pages behind). Also stops if someone cancelled the job.
2. **Size the request:** `count = min(150, limit − fetched)`. The last page asks for exactly what is left, so the saved token points at the next unread review.
3. **Fetch with retries:** [Runner/Fetcher.py](emoteIQ_MCP/src/emoteIQ_reviews/Runner/Fetcher.py) `fetch_with_retries`
   - `GooglePlaySource.fetch_page` → [GooglePlayClient.py](emoteIQ_MCP/src/emoteIQ_reviews/Sources/GooglePlay/GooglePlayClient.py) `fetch_page` → [GooglePlayRequest.py](emoteIQ_MCP/src/emoteIQ_reviews/Sources/GooglePlay/GooglePlayRequest.py) `build_request` (URL + `f.req` body) → `AsyncSession.post` (curl_cffi, one session per job so cookies carry across pages).
   - [GooglePlayParser.py](emoteIQ_MCP/src/emoteIQ_reviews/Sources/GooglePlay/GooglePlayParser.py) `read_page` (strip `)]}'`, find the `wrb.fr` frame, parse the JSON inside the string) → `parse_review` for each review → common `Review` model.
   - [Runner/Classify.py](emoteIQ_MCP/src/emoteIQ_reviews/Runner/Classify.py) `classify` names the result (see the table below). Retryable results wait 1 s, 2 s, 4 s and try again.
   - Every attempt is logged to `fetch.events`.
4. **Store the page:** `JobRunner.store_page`, always in this order:
   1. `save_raw_page`: the exact response text, its position (`start_pos`, `count`), tokens and review IDs → `raw_pages`
   2. `save_reviews`: upsert by review ID → `reviews`
   3. `batcher.add` ([Runner/Batcher.py](emoteIQ_MCP/src/emoteIQ_reviews/Runner/Batcher.py)) cuts full batches of 50; `save_batch` → `batches`
   4. `save_progress`: the checkpoint (`fetched`, `batched`, `pages`, new token) → `jobs`

What the runner does with each page result:

| Result (`Outcome`) | Retried? | What the runner does |
|---|---|---|
| `ok`: reviews + next token | – | Store page, loop again |
| `end`: reviews, no token | – | Store page, job **completed** (Google has no more) |
| limit reached | – | Store page, job **completed**, token kept for continuing |
| `empty` on page 1 | once | Job **completed** with 0 reviews (no matching reviews, or the app doesn't exist) |
| `empty` on a later page | 3× | Still empty → job **blocked**, token kept |
| `http_error` (429/403/5xx) | 3× | Still failing → job **blocked**, token kept |
| `network_error` (timeout etc.) | 3× | Still failing → job **blocked**, token kept |
| `parse_error` (Google changed the format) | no | Raw response saved, job **failed** |

### Step 4: the agent reads batches (at the same time as step 3)
`get_batch(job_id, 1)`, `get_batch(job_id, 2)`, ... in [McpServer/Tools.py](emoteIQ_MCP/src/emoteIQ_reviews/McpServer/Tools.py) `get_batch`

- Looks up the batch document `"<job_id>:<batch_no>"` in `batches`.
- **Not there yet** → checks again every second for up to 20 s, sending MCP progress messages (`Fetching reviews: 450 of 1000`). After 20 s it returns `ready: false`, "call again".
- **There** → loads the reviews by ID (`Storage/Reviews.py` `get_reviews`), keeps only `id`, `score`, `text`, `date`, and calls `mark_served` (this lets the runner fetch further).
- **`last_batch`** is `true` when the job has stopped and this is its highest batch number. Asking for a number past the end returns `"has only N batch(es)"` with `last_batch: true`.

### Step 5: the job finishes
`JobRunner.finish`

1. Flushes leftover reviews into a last, shorter batch (always, even when blocked or cancelled).
2. Saves the final checkpoint and token.
3. `finish_job`: sets `status`, `blocker` or `error`, `completed_at`, and `expires_at` (+90 days).
4. Starts the 7-day TTL on the job's batches and raw pages.
5. Kafka: `job.events: <status>`; plus `fetch.failures` (full token, filters, reason) when blocked, or `parse.errors` when failed.

### Step 6 (optional): more reviews, retry, status
- **More reviews:** `start_review_job(parent_job_id="<finished job>", limit=500)`. The server first **claims** the parent atomically (`Storage/Jobs.py` `claim_parent`: only one child per parent, the parent must be finished and have a token), then creates the child with the parent's filters and token. The child continues exactly where the parent stopped.
- **Blocked job:** `retry_failed(job_id)` reopens it (`reopen_job`), cancels its TTLs and starts the runner again. Batch numbers continue after the last one.
- **Anytime:** `job_status(job_id)` shows progress, the blocker or error, and `can_continue`.

### Server start and stop
[McpServer/Server.py](emoteIQ_MCP/src/emoteIQ_reviews/McpServer/Server.py) `lifespan`, once per server run:
- **Start:** create MongoDB indexes → connect Kafka → **resume every job still `running`** (after a crash or restart they continue from their checkpoint).
- **Stop:** cancel running jobs (they stay `running` in MongoDB and resume next start), close Kafka and MongoDB.

---

## 4. MCP tools

| Tool | Purpose |
|---|---|
| `list_sources` | Sources and the JSON schema of their filters, plus batch-size limits |
| `start_review_job` | New job (`source` + `filters` + `limit` + `batch_size`) or continuation (`parent_job_id` + `limit`) |
| `get_batch` | One batch by number; waits up to 20 s; `last_batch` tells the agent to stop |
| `job_status` | Status, progress, blocker/error, `can_continue`, chain (`parent_job_id`, `root_job_id`, `continued_by`) |
| `retry_failed` | Restart a blocked or failed job from its checkpoint |

Google Play filters: `app_id` (required), `lang`, `country`, `sort` (`NEWEST` / `RATING` / `HELPFULNESS`), `stars` (one value 1–5) **or** `sentiment` (1 positive = 4–5★, 2 critical = 1–3★).

---

## 5. Where the data goes

**MongoDB** (database `EmoteIQ`)

| Collection | `_id` | Holds | Deleted |
|---|---|---|---|
| `jobs` | ObjectId string | filters, limit, batch size, status, tokens, progress, blocker | 90 days after finishing |
| `raw_pages` | `<job_id>:<page_no>` | exact Google response, `start_pos`, `count`, tokens, review IDs | 7 days after finishing |
| `reviews` | `google_play:<review id>` | common review shape (author, score, text, UTC date, reply, extra) | never (shared by all jobs) |
| `batches` | `<job_id>:<batch_no>` | ordered review IDs | 7 days after finishing |

Every write is an upsert on a predictable `_id`, so a page fetched twice after a crash overwrites the same documents instead of duplicating them.

**Kafka** (falls back to `logs/events-fallback.jsonl` if Kafka is down)

| Topic | When | Key |
|---|---|---|
| `job.events` | started, completed, blocked, failed, cancelled | `root_job_id` |
| `fetch.events` | every request to Google, every retry | `job_id` |
| `fetch.failures` | a page still failing after retries: full token + filters + reason | `job_id` |
| `parse.errors` | a response that could not be parsed | `job_id` |

---

## 6. Debugging: where to put breakpoints

Use the **MCP Server + Agent** debug config, then break at:

| To see | Breakpoint |
|---|---|
| What the agent sends | `emoteIQ_Agent/agent.py` the tool functions (`start_review_job`, `get_review_batch`) |
| A tool call arriving at the server | `McpServer/Tools.py` `start_review_job` / `get_batch` |
| Each loop turn of a job | `Runner/JobRunner.py` `run_pages`, the `fetch_with_retries` line |
| The exact request to Google | `Sources/GooglePlay/GooglePlayRequest.py` end of `build_request` (look at `inner`) |
| The raw response | `Sources/GooglePlay/GooglePlayClient.py` after `session.post` (`response.text`) |
| How one review is mapped | `Sources/GooglePlay/GooglePlayParser.py` `parse_review` |
| How batches are cut | `Runner/Batcher.py` `add` |
| Why a job stopped | `Runner/JobRunner.py` `finish` (look at `stop`) |

Logs to watch while it runs (run the `docker exec` commands in PowerShell; Git Bash rewrites `/opt/...` into a Windows path and they fail):
- **Agent terminal:** `===== LLM CALL #n` (prompts and answers), `>>>>> TOOL START` / `<<<<< TOOL DONE` / `!!!!! TOOL ERROR`, `[mcp] ...` (raw MCP calls) and `[mcp progress]`.
- **Server terminal:** startup, and one `POST /mcp` line per tool call.
- **Kafka:** `docker exec -it emoteiq_mcp-kafka-1 /opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic fetch.events --from-beginning`
- **MongoDB:** `docker exec -it emoteiq_mcp-mongo-1 mongosh EmoteIQ --eval "db.jobs.find().sort({created_at:-1}).limit(1)"`

---

## 7. Configuration

All settings have defaults; override them in `emoteIQ_MCP/.env` or as environment variables.

| Setting | Env variable | Default |
|---|---|---|
| MongoDB URI / database | `EMOTEIQ_MONGO_URI` / `EMOTEIQ_MONGO_DB` | `mongodb://localhost:27017` / `EmoteIQ` |
| Kafka | `EMOTEIQ_KAFKA_BOOTSTRAP` | `localhost:9092` |
| Server address | `EMOTEIQ_MCP_HOST` / `EMOTEIQ_MCP_PORT` | `127.0.0.1` / `8000` |
| Batch size default / min / max | `EMOTEIQ_DEFAULT_BATCH_SIZE` / `..._MIN_...` / `..._MAX_...` | 50 / 1 / 200 |
| Pages fetched ahead of the agent | `EMOTEIQ_FETCH_AHEAD_PAGES` | 2 |
| `get_batch` wait | `EMOTEIQ_GET_BATCH_WAIT_S` | 20 |
| TTL jobs / batches / raw pages (days) | `EMOTEIQ_JOBS_TTL_DAYS` / `EMOTEIQ_BATCHES_TTL_DAYS` / `EMOTEIQ_RAW_PAGES_TTL_DAYS` | 90 / 7 / 7 |
| Google Play page size, timeout, retries | `EMOTEIQ_GOOGLE_PLAY_PAGE_SIZE` / `..._REQUEST_TIMEOUT_S` / `..._MAX_RETRIES` | 150 / 15 / 3 |
| curl_cffi browser profile | `EMOTEIQ_GOOGLE_PLAY_IMPERSONATE` | `chrome120` |

Code: `Config/BaseConfig.py` (app + shared source fields), `Config/GooglePlayConfig.py`, `Config/__init__.py` (`app_config`, `get_source_config`).

---

## 8. Adding a new source (for example YouTube)

1. `Config/Source.py`: add `YOUTUBE = "..."`.
2. `Config/YouTubeConfig.py`: `class YouTubeConfig(SourceConfig)` with its own env prefix; register it in `Config/__init__.py`.
3. `Sources/YouTube/`: filters model, request, client, parser, and `YouTubeSource(BaseSource)` returning `PageResult`.
4. `Sources/__init__.py`: add it to `_SOURCES`.

The runner, storage, Kafka events and MCP tools don't change. `list_sources` shows the new source automatically.

---

## 9. Known limits

- **One server process only.** Two processes would both resume the same `running` jobs. Running several needs a lease per job.
- **No authentication.** Fine on `127.0.0.1`; add auth before exposing the server.
- **Google Play's `batchexecute` is an internal endpoint.** It can change without notice (it already moved from `UsvDTd` to `oCPfdb`). Keep request rates polite and check the terms-of-service position before running at scale.
- **Agent issues seen in the end-to-end run (not fixed yet):**
  - `stars` in the agent's `start_review_job` tool is treated as required by CrewAI 1.6.1, so the first calls fail until the model sends `stars: null`.
  - On longer runs `qwen2.5:14b` loses track (re-reads batches, skips parts of the report), probably Ollama's default context window. Raising `num_ctx` or letting a CrewAI Flow drive the batch loop should help.
  - CrewAI prints "Service Unavailable ... exporting spans" at the end: its own telemetry, harmless.
- **No automated tests yet** (`emoteIQ_MCP/tests/` is empty); everything so far was checked with one-off scripts.
