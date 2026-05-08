# `openjiuwen_deepsearch.framework.openjiuwen.agent.workflow` — `DeepSearchAgent`

## `DeepSearchAgent`
```python
class openjiuwen_deepsearch.framework.openjiuwen.agent.workflow.DeepSearchAgent()
```
**DeepSearchAgent** runs the multi-step “search” workflow: initialize research state, propose actions from an action space, execute tools in parallel (bounded by workers), validate new states, and stop when an answer is found or limits/timeouts apply. It subclasses **`BaseAgent`** and is constructed by **`AgentFactory`** when `search_mode` is `"search"` (see [`agent_factory`](./agent_factory.md)).

**Instance fields** (set during `run` or construction):

- **version** (`str`): Workflow card version, default `"1"`.
- **action_pool**, **completed_actions**, **final_answer**: runtime search loop state.
- **fail_count**, **total_input_tokens**, **total_output_tokens**: counters across sub-workflows.
- **log_dir**, **time_limit**, **query**, **gold_answer**, **tool_map**: per-run execution context.
- **agent_config** (`AgentConfig | None`), **per_question_params**, **search_config** (`SearchWorkflowConfig | None`): validated from the incoming `agent_config` and optional `service_config.search_workflow`.

---

### `setup_log_directory`
```python
setup_log_directory(save_as: str) -> None
```
Creates `{LogManager.get_log_dir()}/{save_as}/Action` and `.../Result`, sets **`log_dir`**, and assigns **`action_pool.log_dir`**.

**Parameters**:
- **save_as** (`str`): Subdirectory name under the base log directory (e.g. `result_{conversation_id}` from `run`).

---

### Output logs directory and files

Each `run(...)` call creates a per-conversation output directory:

- Base path: `LogManager.get_log_dir()` (commonly configured as `./output/logs` in entry scripts).
- Run folder: `result_{conversation_id}`.
- Full run path shape: `{base_log_dir}/result_{conversation_id}`.

Inside that folder, `DeepSearchAgent` writes:

- `Action/` — snapshots of action proposals from `find_action` steps.
- `Result/` — per-action execution outputs from `state_creation` steps.
- `action_pool.json` — live snapshot of pending/running/completed actions.
- `final_result.json` — final `SearchFinalResult` payload for the run.

Typical file names:

- `Action/action_{timestamp}_{uuid}.json`
- `Result/result_{timestamp}_{uuid}.json`
- `Result/answer_result_{timestamp}_{uuid}.json` (when an answer is found)
- `Result/error_result_{timestamp}_{uuid}.json` (when a step fails)

Example layout:

```text
output/logs/
  result_1234567890/
    Action/
      action_20260507081833921_9a82b4f4f33f46f08c6615e7c8e4ff2f.json
    Result/
      result_20260507081835542_5accc5b8f4cc498ab0b4f4f040afe76e.json
      answer_result_20260507081840117_2dd2bffc286b4fb3b6db95abf4f5fd8f.json
    action_pool.json
    final_result.json
```

Example `Action/action_*.json`:

```json
{
  "question": "who was the president of the former country whose capital is known as the white city?",
  "state": {
    "id": "0",
    "depth": 0,
    "answer_variable": 0,
    "retrieved_evidence_ids": [],
    "state": [
      {
        "id": 0,
        "type": "person",
        "question_clues": [],
        "discovered_clues": [],
        "candidate": null,
        "candidate_strength": null
      }
    ]
  },
  "proposals": [
    "Identify which country had a capital nicknamed 'the white city'",
    "Find presidents associated with that country"
  ],
  "scores": [0.83, 0.71],
  "action_ids": ["a1f1...", "b2e2..."],
  "message": []
}
```

Example `Result/result_*.json`:

```json
{
  "previous_state": {
    "id": "1",
    "depth": 1,
    "answer_variable": 0,
    "retrieved_evidence_ids": [],
    "state": []
  },
  "previous_action": "Identify which country had a capital nicknamed 'the white city'",
  "result": {
    "messages": [
      {"role": "assistant", "content": "The capital nickname points to Belgrade."}
    ],
    "new_states": [],
    "found_answer": null,
    "summary": null,
    "previous_action_id": "a1f1...",
    "retrieved_evidence_ids": []
  },
  "time_taken": 3.42
}
```

Example `final_result.json`:

```json
{
  "question": "who was the president of the former country whose capital is known as the white city?",
  "termination": "answer",
  "completion_time": 18.73,
  "current_date_time": "20260507081840119",
  "prediction": "Josip Broz Tito",
  "gold_answer": null,
  "messages": [
    {"role": "assistant", "content": "Final answer ..."}
  ],
  "config": {},
  "retrieved_evidence_ids": []
}
```

---

### `run`
```python
async run(
    message: str,
    conversation_id: str,
    agent_config: dict,
    report_template: str = "",
    interrupt_feedback: str = "",
) -> AsyncGenerator[str, None]
```
Same surface as **`BaseAgent.run`**. Validates with `validate_run_agent_params` and `validate_agent_required_field` (after stripping optional keys). Deep-copies **`agent_config`** into **`AgentConfig`**, sets up logging, **`SearchWorkflowConfig`** from `agent_config["service_config"]["search_workflow"]` (defaults on parse failure), **`per_question_params`**, **`WORKFLOW_EXECUTE_TIMEOUT`**, LLM context (requires `llm_config["general"]`), and tools from **`per_question_params.tool_map`**:

- **`"search_fetch"`**: `WebFetch` + `WebSearch` (uses `jina_api_key`, `serper_api_key` on **`agent_config`**).
- **`"retrieve"`**: `RetrieveBrowsecompPlus` (Milvus / embedder fields from **`search_workflow_milvus_config`**).

Other values for **`tool_map`** raise **`CustomValueException`**.

**Optional keys** removed before **`AgentConfig`** validation:

- **`service_config`** (`dict`): nested **`search_workflow`** is validated as **`SearchWorkflowConfig`**.
- **`gold_answer`** (`str | None`): optional benchmark label; forwarded into the final payload.

**Parameters**:
- **message** (`str`): User question (**`query`** for the internal loop).
- **conversation_id** (`str`): Used to name the log subdirectory.
- **agent_config** (`dict`): Full agent configuration plus optional **`service_config`** / **`gold_answer`** as above.
- **report_template**, **interrupt_feedback**: Accepted for API compatibility; not used in this agent’s path.

**Simple runnable example (`search_fetch`) with explicit log output path**:
```python
import asyncio
import copy
import json
import uuid
from openjiuwen_deepsearch.config.config import Config
from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory
from openjiuwen_deepsearch.utils.log_utils.log_manager import LogManager


async def main():
    query = "who was the president of the former country whose capital is known as the white city?"

    # Important: initialize LogManager before creating/running the agent.
    # Safety check in LogManager allows paths under ./output/logs.
    log_dir = "./output/logs/my_run_logs"
    LogManager.init(
        log_dir=log_dir,
        max_bytes=100 * 1024 * 1024,
        backup_count=20,
        level="INFO",
        is_sensitive=False,
    )

    # Start from project defaults and only override what differs.
    agent_config = Config().agent_config.model_dump()
    agent_config["search_mode"] = "search"  # default is "research"
    agent_config["workflow_human_in_the_loop"] = False  # default is True
    agent_config["search_workflow_per_question_params"]["time_limit"] = 300  # default is 4800
    agent_config["search_workflow_per_question_params"]["max_workers"] = 2  # default is 5

    # LLM for general reasoning in search mode.
    agent_config["llm_config"]["general"] = {
        "model_name": "<YOUR_LLM_MODEL_NAME>",
        "model_type": "<YOUR_LLM_MODEL_TYPE>",
        "base_url": "<YOUR_LLM_BASE_URL>",
        "api_key": bytearray("<YOUR_LLM_API_KEY>", encoding="utf-8"),
        "hyper_parameters": {"temperature": 0.2, "top_p": 1.0},
        "extension": {},
    }

    # search_fetch keys (tool_map defaults to "search_fetch").
    agent_config["jina_api_key"] = bytearray("<YOUR_JINA_API_KEY>", encoding="utf-8")
    agent_config["serper_api_key"] = bytearray("<YOUR_SERPER_API_KEY>", encoding="utf-8")

    conversation_id = str(uuid.uuid4())
    agent = AgentFactory().create_agent(copy.deepcopy(agent_config))
    async for chunk in agent.run(
        message=query,
        conversation_id=conversation_id,
        report_template="",
        interrupt_feedback="",
        agent_config=agent_config,
    ):
        payload = json.loads(chunk)
        print("SearchFinalResult:", json.dumps(payload, indent=2))

    print(f"Per-run artifacts written under: {log_dir}/result_{conversation_id}/")


if __name__ == "__main__":
    asyncio.run(main())
```

**Yields**:
- One JSON string (UTF-8, `ensure_ascii=False`) per run: serialized **`SearchFinalResult`** (or dict-safe fallback). Fields match the Pydantic model in `openjiuwen_deepsearch.framework.openjiuwen.agent.search_context` (**`question`**, **`termination`**, **`completion_time`**, **`current_date_time`**, **`prediction`**, **`gold_answer`**, **`messages`**, **`config`**, **`retrieved_evidence_ids`**).

**Raises**:
- **`CustomValueException`**: invalid run params, missing **`general`** LLM config, invalid **`tool_map`**, or init-state workflow failure after retries.

---

### `run_state_creation_workflow`
```python
async run_state_creation_workflow(action: Any, semaphore: asyncio.Semaphore) -> Any
```
Runs the **`state_creation`** subgraph for one **`Action`** under the given semaphore (used by the parallel worker loop). Prefer invoking **`run`** unless you extend the agent.

---

## Related

- **`AgentFactory.create_agent`**: use `"search_mode": "search"` to obtain **`DeepSearchAgent`** ([`agent_factory`](./agent_factory.md)).
- **`BaseAgent`**, **`DeepresearchAgent`**: same module; overview in [`workflow`](./workflow.md).
- Session / research models in [`search_context`](./search_context.md); **`SearchFinalResult`** lives in the same Python module for search-mode payloads.

---

## Telemetry Backend API

The telemetry backend is implemented by `server.telemetry_event_server` and runs as a FastAPI app (default: `http://127.0.0.1:8089`). It supports telemetry ingestion, background DeepSearch run execution, run cancellation, and JSONL log reads.

### Starting the backend server

Run the this command from project root:

```bash
uv run python -m server.telemetry_event_server
```


### `GET /health`
Lightweight liveness endpoint (plain text response).

**Response**:
- `200 OK`, body is plain text:
  - `ok; append JSONL to <path>` when file logging is enabled.
  - `ok (no JSONL file)` when `--no-jsonl` is used.

**Example output**:
```text
ok; append JSONL to /Users/dev/deepsearch/output/telemetry_logs/telemetry.jsonl
```

### `GET /`
Root liveness endpoint; same behavior as `GET /health`.

**Response**:
- `200 OK` plain text.

**Example output**:
```text
ok; append JSONL to /Users/dev/deepsearch/output/telemetry_logs/telemetry.jsonl
```

### `POST /events`
Telemetry ingest endpoint (path configurable via `--path`, default `/events`).

Accepts one JSON object per request and appends it as one JSONL line when file logging is enabled.

**Request body**:
- JSON object (commonly includes fields from telemetry emitter such as `event`, `run_id`, `seq`, `ts`, `payload`).
- Empty body is accepted and treated as `{}`.

**Response**:
- `204 No Content` on success.
- `400 Bad Request` if body is invalid JSON or not a JSON object.

**Example request body (well-formed event JSON)**:
```json
{
  "event": "run_started",
  "run_id": "f23e4567-e89b-12d3-a456-426614174000",
  "seq": 1,
  "ts": "2026-05-07T13:15:01.123Z",
  "source": "main.run_jiuwen_workflow",
  "action_id": null,
  "payload": {
    "query": "Who was the president of the former country whose capital is known as the white city?",
    "search_mode": "search"
  }
}
```

**Example output (success)**:
```text
HTTP/1.1 204 No Content
```

**Example output (invalid body)**:
```json
{
  "detail": "Bad Request"
}
```

### `POST /runs`
Starts a background DeepSearch graph run (`search` or `react`, not `research`) via `main.run_jiuwen_workflow`.

**Request body** (`CreateSearchRunRequest`):
- `query` (`str`, required): user question.
- `llm` (`object`, required): includes required `model_name`, `base_url`, `api_key`.
- `search_mode` (`"search" | "react"`, default `"search"`).
- `enable_question_router` (`bool`, default from `Config().agent_config`).
- `run_id` (`str | null`, optional): if omitted, server generates UUID.
- `conversation_id` (`str | null`, optional): if omitted, server generates UUID (API lifecycle correlation id).
- `tool_map` (`"search_fetch" | "retrieve"`, default from `PerQuestionParams`).
- `jina_api_key` / `serper_api_key` (required when `tool_map="search_fetch"`).
- `milvus` (`object`, optional): Milvus/embedder settings; embedder key/base URL required when `tool_map="retrieve"`.
- `search_workflow_per_question_params` (`object`, optional): shallow overrides validated against `PerQuestionParams`.

**Response**:
- `201 Created` with JSON:
  - `run_id`: actual run id.
  - `status`: `"started"`.
  - `conversation_id`: API lifecycle conversation id.

**Errors**:
- `409 Conflict`: `run_id` already in progress.
- `422 Unprocessable Entity`: validation error (e.g., missing required tool keys, invalid per-question overrides).

**Example request body**:
```json
{
  "search_mode": "search",
  "enable_question_router": true,
  "run_id": "f23e4567-e89b-12d3-a456-426614174000",
  "query": "Who was the president of the former country whose capital is known as the white city?",
  "conversation_id": "53e6d4e4-65bd-49ad-9a67-a0b6138df111",
  "llm": {
    "model_name": "gpt-4o-mini",
    "model_type": "openai",
    "base_url": "https://api.openai.com/v1",
    "api_key": "sk-***",
    "hyper_parameters": {
      "temperature": 0.2,
      "top_p": 1.0
    },
    "extension": {}
  },
  "tool_map": "search_fetch",
  "jina_api_key": "jina_***",
  "serper_api_key": "serper_***",
  "search_workflow_per_question_params": {
    "time_limit": 300,
    "max_workers": 2
  }
}
```

**Example output (201)**:
```json
{
  "run_id": "f23e4567-e89b-12d3-a456-426614174000",
  "status": "started",
  "conversation_id": "53e6d4e4-65bd-49ad-9a67-a0b6138df111"
}
```

**Example output (409)**:
```json
{
  "detail": "run_id already in progress"
}
```

### `POST /runs/{run_id}/cancel`
Cancels an in-flight run.

**Path params**:
- `run_id` (`str`): run identifier to cancel.

**Response**:
- `204 No Content` when cancellation signal is accepted.
- `404 Not Found` if run is unknown or already finished.

**Example output (204)**:
```text
HTTP/1.1 204 No Content
```

**Example output (404)**:
```json
{
  "detail": "unknown or finished run_id"
}
```

### `GET /telemetry/recent`
Returns the last N telemetry events from JSONL (optionally filtered by `run_id`).

**Query params**:
- `n` (`int`, required): number of events to return; clamped to `[1, 10000]`.
- `run_id` (`str`, optional): filter events for one run.

**Response**:
- `200 OK` JSON:
  - `items`: list of telemetry event objects.
  - `count`: number of returned items.

**Example output**:
```json
{
  "items": [
    {
      "event": "run_started",
      "run_id": "f23e4567-e89b-12d3-a456-426614174000",
      "seq": 1,
      "ts": "2026-05-07T13:15:01.123Z",
      "source": "main.run_jiuwen_workflow",
      "action_id": null,
      "payload": {
        "query": "Who was the president of the former country whose capital is known as the white city?",
        "search_mode": "search"
      }
    },
    {
      "event": "node_completed",
      "run_id": "f23e4567-e89b-12d3-a456-426614174000",
      "seq": 2,
      "ts": "2026-05-07T13:15:04.008Z",
      "source": "openjiuwen.agent.main_nodes",
      "action_id": "9f203ecb-4465-44ca-9f67-7c6a3f3021e1",
      "payload": {
        "node_name": "find_action",
        "duration_ms": 612,
        "proposals_count": 2
      }
    },
    {
      "event": "run_completed",
      "run_id": "f23e4567-e89b-12d3-a456-426614174000",
      "seq": 3,
      "ts": "2026-05-07T13:15:12.334Z",
      "source": "server.telemetry_event_server._run_search_workflow",
      "action_id": null,
      "payload": {
        "conversation_id": "53e6d4e4-65bd-49ad-9a67-a0b6138df111"
      }
    }
  ],
  "count": 3
}
```

### `GET /telemetry/range`
Returns telemetry events by `run_id` and inclusive sequence range.

**Query params**:
- `run_id` (`str`, required).
- `start_seq` (`int`, required).
- `end_seq` (`int`, required, must be `>= start_seq`).

**Response**:
- `200 OK` JSON:
  - `items`: matching telemetry events.
  - `count`: number of returned items.

**Errors**:
- `422 Unprocessable Entity` when `start_seq > end_seq`.

**Example output (`run_id=f23e4567-e89b-12d3-a456-426614174000&start_seq=2&end_seq=3`)**:
```json
{
  "items": [
    {
      "event": "node_completed",
      "run_id": "f23e4567-e89b-12d3-a456-426614174000",
      "seq": 2,
      "ts": "2026-05-07T13:15:04.008Z",
      "source": "openjiuwen.agent.main_nodes",
      "action_id": "9f203ecb-4465-44ca-9f67-7c6a3f3021e1",
      "payload": {
        "node_name": "find_action",
        "duration_ms": 612,
        "proposals_count": 2
      }
    },
    {
      "event": "run_completed",
      "run_id": "f23e4567-e89b-12d3-a456-426614174000",
      "seq": 3,
      "ts": "2026-05-07T13:15:12.334Z",
      "source": "server.telemetry_event_server._run_search_workflow",
      "action_id": null,
      "payload": {
        "conversation_id": "53e6d4e4-65bd-49ad-9a67-a0b6138df111"
      }
    }
  ],
  "count": 2
}
```
