# openjiuwen_deepsearch.framework.openjiuwen.agent.workflow — DeepSearchAgent

## class openjiuwen_deepsearch.framework.openjiuwen.agent.workflow.DeepSearchAgent
```python
class openjiuwen_deepsearch.framework.openjiuwen.agent.workflow.DeepSearchAgent()
```
**DeepSearchAgent** 实现「search」模式的多步检索推理：初始化研究状态、从动作空间采样动作、在并发上限内执行工具与状态校验，并在找到答案或触发时间/次数等终止条件时结束。它继承 **`BaseAgent`**，当配置中 **`search_mode` 为 `"search"`** 时由 **`AgentFactory`** 创建（参见 [`agent_factory`](./agent_factory.md)）。

**实例字段**（在 `run` 过程中或构造后使用）：

- **version**（`str`）：子工作流卡片版本，默认 `"1"`。
- **action_pool**、**completed_actions**、**final_answer**：搜索循环运行时状态。
- **fail_count**、**total_input_tokens**、**total_output_tokens**：跨子工作流的计数。
- **log_dir**、**time_limit**、**query**、**gold_answer**、**tool_map**：单次运行的执行上下文。
- **agent_config**（`AgentConfig | None`）、**per_question_params**、**search_config**（`SearchWorkflowConfig | None`）：由入参 **`agent_config`** 及可选 **`service_config.search_workflow`** 校验得到。

---

### setup_log_directory
```python
setup_log_directory(save_as: str) -> None
```
在 **`{LogManager.get_log_dir()}/{save_as}`** 下创建 **`Action`** 与 **`Result`** 子目录，写入 **`log_dir`**，并设置 **`action_pool.log_dir`**。

**参数**：
- **save_as**（`str`）：日志根目录下的子目录名（`run` 中通常为 `result_{conversation_id}`）。

---

### run
```python
async run(
    message: str,
    conversation_id: str,
    agent_config: dict,
    report_template: str = "",
    interrupt_feedback: str = "",
) -> AsyncGenerator[str, None]
```
与 **`BaseAgent.run`** 签名一致。先经 **`validate_run_agent_params`**、再剥离可选字段后经 **`validate_agent_required_field`** 校验。将 **`agent_config`** 深拷贝为 **`AgentConfig`**，配置日志目录、从 **`agent_config["service_config"]["search_workflow"]`** 解析 **`SearchWorkflowConfig`**（解析失败则使用默认配置）、**`per_question_params`**、环境变量 **`WORKFLOW_EXECUTE_TIMEOUT`**、LLM 上下文（要求 **`llm_config`** 中存在 **`general`**），以及由 **`per_question_params.tool_map`** 决定的工具：

- **`"search_fetch"`**：注册 **`WebFetch`** 与 **`WebSearch`**（使用配置中的 **`jina_api_key`**、**`serper_api_key`**）。
- **`"retrieve"`**：注册 **`RetrieveBrowsecompPlus`**（Milvus / 向量化相关字段来自 **`search_workflow_milvus_config`**）。

**`tool_map`** 取其他值会抛出 **`CustomValueException`**。

在写入 **`AgentConfig`** 前会从字典中 **`pop`** 的**可选**字段：

- **`service_config`**（`dict`）：其中的 **`search_workflow`** 会校验为 **`SearchWorkflowConfig`**。
- **`gold_answer`**（`str | None`）：可选标准答案（评测场景），会进入最终返回结构。

**参数**：
- **message**（`str`）：用户问题（内部作为 **`query`**）。
- **conversation_id**（`str`）：用于日志子目录命名。
- **agent_config**（`dict`）：完整 Agent 配置，并可附带 **`service_config`** / **`gold_answer`**。
- **report_template**、**interrupt_feedback**：为与其它 Agent 统一的接口保留；本 Agent 主路径不使用。

**简单可运行示例（`search_fetch`）**：
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

**返回（生成器）**：
- 每次运行 **`yield`** 一条 JSON 字符串（`ensure_ascii=False`）：一般为 **`SearchFinalResult`** 的序列化结果。字段与 `openjiuwen_deepsearch.framework.openjiuwen.agent.search_context` 中的 Pydantic 模型一致（**`question`**、**`termination`**、**`completion_time`**、**`current_date_time`**、**`prediction`**、**`gold_answer`**、**`messages`**、**`config`**、**`retrieved_evidence_ids`** 等）。

**异常**：
- **`CustomValueException`**：运行参数非法、缺少 **`general`** LLM 配置、**`tool_map`** 非法，或初始化状态子工作流在重试后仍失败等。

---

### run_state_creation_workflow
```python
async run_state_creation_workflow(action: Any, semaphore: asyncio.Semaphore) -> Any
```
在给定信号量下为单个 **`Action`** 执行 **`state_creation`** 子图（供内部并行 worker 使用）。集成方请优先调用 **`run`**；仅在扩展 Agent 行为时再考虑直接调用。

---

## 相关文档

- **`AgentFactory.create_agent`**：配置 **`"search_mode": "search"`** 得到 **`DeepSearchAgent`**（[`agent_factory`](./agent_factory.md)）。
- **`BaseAgent`**、**`DeepresearchAgent`**：同模块概述见 [`workflow`](./workflow.md)。
- 会话/研究侧模型见 [`search_context`](./search_context.md)；**`SearchFinalResult`** 与之一同在上述 Python 模块中定义，用于 search 模式最终载荷。

---

## Telemetry 后端 API

Telemetry 后端由 `server.telemetry_event_server` 提供（FastAPI，默认 `http://127.0.0.1:8089`）。能力包括：事件上报、后台 DeepSearch 运行、运行取消、JSONL 事件查询。

### 启动命令

在项目根目录执行：

```bash
uv run python -m server.telemetry_event_server
```

### `GET /health`
轻量存活探针（返回纯文本）。

**响应**：
- `200 OK`，响应体为纯文本：
  - 启用文件落盘时：`ok; append JSONL to <path>`
  - 使用 `--no-jsonl` 时：`ok (no JSONL file)`

**示例输出**：
```text
ok; append JSONL to /Users/dev/deepsearch/output/telemetry_logs/telemetry.jsonl
```

### `GET /`
根路径健康检查，与 `GET /health` 行为一致。

**响应**：
- `200 OK`，纯文本。

**示例输出**：
```text
ok; append JSONL to /Users/dev/deepsearch/output/telemetry_logs/telemetry.jsonl
```

### `POST /events`
Telemetry 事件写入接口（路径可由 `--path` 配置，默认 `/events`）。

接收单个 JSON 对象；若开启 JSONL 落盘，则按一行一条写入日志文件。

**请求体**：
- JSON 对象（常见字段：`event`、`run_id`、`seq`、`ts`、`payload`）。
- 空请求体也允许，会按 `{}` 处理。

**响应**：
- `204 No Content`：成功。
- `400 Bad Request`：请求体不是合法 JSON，或不是 JSON 对象。

**示例请求体（规范事件 JSON）**：
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

**示例输出（成功）**：
```text
HTTP/1.1 204 No Content
```

**示例输出（无效请求）**：
```json
{
  "detail": "Bad Request"
}
```

### `POST /runs`
启动后台 DeepSearch 图运行（支持 `search` / `react`，不支持 `research`），内部调用 `main.run_jiuwen_workflow`。

**请求体**（`CreateSearchRunRequest`）：
- `query`（`str`，必填）：用户问题。
- `llm`（`object`，必填）：必须包含 `model_name`、`base_url`、`api_key`。
- `search_mode`（`"search" | "react"`，默认 `"search"`）。
- `enable_question_router`（`bool`，默认取自 `Config().agent_config`）。
- `run_id`（`str | null`，可选）：不传则服务端生成 UUID。
- `conversation_id`（`str | null`，可选）：不传则服务端生成 UUID（用于 API 生命周期关联）。
- `tool_map`（`"search_fetch" | "retrieve"`，默认取自 `PerQuestionParams`）。
- `jina_api_key` / `serper_api_key`（当 `tool_map="search_fetch"` 时必填）。
- `milvus`（`object`，可选）：Milvus/Embedding 配置；当 `tool_map="retrieve"` 时要求 embedder key/base URL。
- `search_workflow_per_question_params`（`object`，可选）：浅覆盖参数，会按 `PerQuestionParams` 校验。

**响应**：
- `201 Created`，JSON：
  - `run_id`：实际运行 ID
  - `status`：`"started"`
  - `conversation_id`：API 生命周期会话 ID

**错误**：
- `409 Conflict`：`run_id` 已在运行中。
- `422 Unprocessable Entity`：参数校验失败（如缺少工具所需 key、覆盖字段非法）。

**示例请求体**：
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

**示例输出（201）**：
```json
{
  "run_id": "f23e4567-e89b-12d3-a456-426614174000",
  "status": "started",
  "conversation_id": "53e6d4e4-65bd-49ad-9a67-a0b6138df111"
}
```

**示例输出（409）**：
```json
{
  "detail": "run_id already in progress"
}
```

### `POST /runs/{run_id}/cancel`
取消正在运行的任务。

**路径参数**：
- `run_id`（`str`）：待取消任务 ID。

**响应**：
- `204 No Content`：已接受取消请求。
- `404 Not Found`：任务不存在或已结束。

**示例输出（204）**：
```text
HTTP/1.1 204 No Content
```

**示例输出（404）**：
```json
{
  "detail": "unknown or finished run_id"
}
```

### `GET /telemetry/recent`
读取最近 N 条 telemetry 事件（可按 `run_id` 过滤）。

**查询参数**：
- `n`（`int`，必填）：返回条数，服务端会约束到 `[1, 10000]`。
- `run_id`（`str`，可选）：仅返回指定运行 ID 的事件。

**响应**：
- `200 OK`，JSON：
  - `items`：事件列表
  - `count`：返回数量

**示例输出**：
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
按 `run_id` + 序号区间（含边界）读取事件。

**查询参数**：
- `run_id`（`str`，必填）
- `start_seq`（`int`，必填）
- `end_seq`（`int`，必填，且必须 `>= start_seq`）

**响应**：
- `200 OK`，JSON：
  - `items`：匹配事件列表
  - `count`：返回数量

**错误**：
- `422 Unprocessable Entity`：`start_seq > end_seq`。

**示例输出（`run_id=f23e4567-e89b-12d3-a456-426614174000&start_seq=2&end_seq=3`）**：
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

**示例输出（`start_seq > end_seq`）**：
```json
{
  "detail": "start_seq must be <= end_seq"
}
```
