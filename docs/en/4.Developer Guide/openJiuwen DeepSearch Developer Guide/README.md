# Initialize DeepResearch configuration

---

The `Config` type combines **AgentConfig** (user-tunable via public APIs) and **ServiceConfig** (internal defaults). When initializing, set fields on `AgentConfig` as needed.

```python
from openjiuwen_deepsearch.config.config import Config

agent_config = Config().agent_config.model_dump()

# 1. Configure at least one working LLM
agent_config["llm_config"]["general"]["model_name"] = ""
agent_config["llm_config"]["general"]["model_type"] = ""
agent_config["llm_config"]["general"]["base_url"] = ""
agent_config["llm_config"]["general"]["api_key"] = ""

# 2. Configure web augmentation / search engine
agent_config["web_search_engine_config"]["search_engine_name"] = ""
agent_config["web_search_engine_config"]["search_url"] = ""
agent_config["web_search_engine_config"]["search_api_key"] = ""

# 3. Optional execution overrides
agent_config["workflow_human_in_the_loop"] = False
agent_config["outline_interaction_enabled"] = False
agent_config["search_mode"] = "research"
agent_config["execution_method"] = "parallel"
```

## LLM configuration

---

DeepSearch can assign up to four logical models:

- **plan_understanding** — intent and planning (Outliner, Planner); reduces hallucinations.
- **info_collecting** — information gathering (InfoCollector).
- **writing_checking** — report body and rich content (Sub-reporter).
- **general** — default for any stage without a specific model (**required**).

**general must be configured**; other slots fall back to **general**. Prefer a strong model for **general**.

Supported backends (OpenAI-compatible):

- SiliconFlow: set `LLMConfig.model_type` to `siliconflow`.
- OpenAI-compatible HTTP APIs: set `model_type` to `openai`.

> Obtain `api_key`, `model_name`, and `base_url` from your provider.

## Web search / augmentation configuration

---

Supported engines (set `web_search_engine_config.search_engine_name`):

- `google`
- `tavily`
- `xunfei` (iFlytek)
- `petal` (Petal AI web augmentation)
- `custom`

> Register with the vendor for `search_api_key` and `search_url`.

## TLS / SSL

---

For LLM, tools, and embedding endpoints you can enforce TLS verification:

- **LLM**: `LLM_SSL_VERIFY=true` and optional `LLM_SSL_CERT`.
- **Tools**: `TOOL_SSL_VERIFY=true` and `TOOL_SSL_CERT`.
- **Embedding**: `EMBEDDING_SSL_VERIFY=true` enables HTTPS verification; system trust store is enough unless you use private CAs—then set `EMBEDDING_SSL_CERT` to a PEM path. When starting via this repo’s `server/main.py`, unset/blank `EMBEDDING_SSL_VERIFY` is treated as `false` (matches `.env.example`). `true` with an untrusted cert and no CA file can break index builds.

To disable verification, set the three `*_SSL_VERIFY` flags to `false` (or leave embedding unset as above).

```python
import os
os.environ["LLM_SSL_VERIFY"] = "false"
os.environ["LLM_SSL_CERT"] = ""
os.environ["TOOL_SSL_VERIFY"] = "false"
os.environ["TOOL_SSL_CERT"] = ""
os.environ["EMBEDDING_SSL_VERIFY"] = "false"
os.environ["EMBEDDING_SSL_CERT"] = ""
```

# Instantiate an agent

---

The stack ships a deep-research agent that plans, gathers evidence, and writes reports.

## Via `AgentFactory` (recommended)

---

`AgentFactory` picks `DeepresearchAgent` vs `DeepresearchDependencyAgent` from `execution_method` (and related flags).

```python
from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory

agent_factory = AgentFactory()
agent = agent_factory.create_agent(agent_config)
```

## Via constructor

---

To force the parallel agent:

```python
from openjiuwen_deepsearch.framework.openjiuwen.agent.workflow import DeepresearchAgent

agent = DeepresearchAgent()
```

# Generate research reports

---

`DeepresearchAgent.run` and `generate_template` cover the main flows:

1. Query only.
2. Query + existing template (follow structure).
3. Query + sample report (extract template, then generate).

## Query-only run

---

`run(message: str, ...)` streams JSON chunks. Each chunk is a `dict` with `agent` and `content`. Final report content arrives from `NodeId.END.value`; with post-report editing enabled, `user_feedback_processor` adds another interaction round before completion.

```python
import json
import uuid
from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory
from openjiuwen_deepsearch.framework.openjiuwen.agent.workflow import parse_endnode_content

agent_factory = AgentFactory()
agent = agent_factory.create_agent(agent_config)

message = "User question"
conversation_id = str(uuid.uuid4())

async for chunk in agent.run(message=message, conversation_id=conversation_id, agent_config=agent_config):
    logger.debug("[Stream message from node: %s]", chunk)
    chunk_content = json.loads(chunk)
    report_result = parse_endnode_content(chunk_content)
    if report_result:
        logger.debug("[Final Report is: %s]", report_result)
```

## Query + user template

---

Enable template-following in `agent_config`. The template describes top-level sections, subsections, functional notes, and whether a section is “core.”

Example template (Markdown):

```markdown
# Company overview
> Functional summary: Describe the target company in detail
> Core section: true

## 1.1 Basic information
> Functional summary: List foundational company facts.

## 1.2 Business scope and main activities
> Functional summary: Explain registered business scope and actual core business.

## 1.3 Ownership structure and related parties
> Functional summary: Shareholding, contributions, shareholder types, and key affiliates.

# Operations and industry analysis
> Functional summary: Operations and industry context
> Core section: true

## 2.1 Macro and regional economics
> Functional summary: Macro industry environment, regional economy, industrial clusters.

## 2.2 Industry status and outlook
> Functional summary: Current state and outlook for the industry segments.

## 2.3 Competitive positioning
> Functional summary: Capacity, R&D, market position, brand, key customers.

## 2.4 Upstream/downstream chain
> Functional summary: Supply chain and customer structure.
```

Call `generate_template` with `is_template=True`:

```python
import base64
from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory

file_path = "template.md"
file_stream = base64.b64encode(read_file_safely(file_path)).decode("utf-8")
is_template = True

agent_factory = AgentFactory()
agent = agent_factory.create_agent(agent_config)

result = await agent.generate_template(
    file_name=file_path,
    file_stream=file_stream,
    is_template=is_template,
    agent_config=agent_config,
)
user_template_content = result["template_content"]
```

Pass the normalized template into `run` via `report_template` (base64 string):

```python
async for chunk in agent.run(
    message=message,
    conversation_id=conversation_id,
    agent_config=agent_config,
    report_template=user_template_content,
):
    ...
```

## Query + sample report

---

Same as above but upload a sample report (Markdown, DOCX, PDF, HTML) and set `is_template=False` in `generate_template`. The service extracts a template, then you call `run` with `report_template=user_template_content` as in the previous section.

# Human-in-the-loop (HITL)

---

Pause at key points for natural-language feedback so users can steer planning.

**Keep `conversation_id` identical across resume calls.**

Supported stages:

1. **Clarification** — questions before planning.
2. **Outline interaction** — revise or accept the outline.

## Clarification

Set:

```python
agent_config["workflow_human_in_the_loop"] = True
```

(Default is on in many deployments.)

Flow: user asks → system asks follow-ups → interrupt → user answers → resume.

### Feedback channels

```python
service_config.workflow_feedback_mode = "web"  # Studio/UI
# or
service_config.workflow_feedback_mode = "cmd"  # terminal input
```

### Web-style payloads

```python
# Round 1
{
    "message": "User question",
    "conversation_id": "<id>",
    "agent_config": {"workflow_human_in_the_loop": True, ...},
}

# Round 2
{
    "message": "User answers the clarifying questions",
    "conversation_id": "<same id>",
    "agent_config": {"workflow_human_in_the_loop": True, ...},
}
```

## Outline interaction

Enable:

```python
agent_config["outline_interaction_enabled"] = True
```

(Default on.) After outline generation the workflow waits for feedback.

| Action | Meaning | Next step |
| ------ | ------- | --------- |
| `accepted` | Approve outline | Enter reporting |
| `revise_comment` | Free-text change request | Regenerate outline |
| `revise_outline` | User-edited outline text | Regenerate outline |

Server fields (`DeepSearchRequest`): `outline_interaction_enabled`, `outline_interaction_max_rounds` (1–100, default 3). SDK passes them through `agent_config`.

### `space_id` and local knowledge bases

`space_id` scopes tenants: KB creation/upload APIs are tied to it. When calling `run` with local search, every id in `local_search_config.local_search_config_ids` must belong to that `space_id`; cross-space ids are rejected.

**KB + object storage**: only when `CHECKPOINTER_TYPE=redis` do uploads go to configured object storage for multi-instance consistency; `in_memory` / `persistence` keep files on local disk (OBS unused). Multi-instance deployments require shared MySQL; `redis` + `sqlite` is rejected.

Agent cache keys hash stable JSON of all fields that affect agent construction (excluding `message`, `conversation_id`, `interrupt_feedback`), including `space_id`, `local_search_config`, web search settings, `llm_config`, and feature flags—so changing KB or engine config within a space invalidates stale agents.

> Do not trust raw `space_id` from clients on untrusted networks; bind it to auth at the gateway.

### Web outline example

```python
# Round 1 — outline pending feedback
{
    "message": "Analyze China’s NEV market trends",
    "conversation_id": "<id>",
    "agent_config": {"outline_interaction_enabled": True, "outline_interaction_max_rounds": 3, ...},
}

# Round 2 — comment-based revision
{
    "message": "Add a section on charging infrastructure",
    "conversation_id": "<same id>",
    "interrupt_feedback": "revise_comment",
    "agent_config": {...},
}

# Round 3 — accept
{
    "message": "",
    "conversation_id": "<same id>",
    "interrupt_feedback": "accepted",
    "agent_config": {...},
}
```

### Notes

- Reuse **`conversation_id`** for every resume call.
- Interrupts pause until feedback arrives.
- After `outline_interaction_max_rounds`, the workflow proceeds automatically.

---

# Post-report local editing

---

After the report (and provenance) are ready, users can expand/polish/shorten selections.

Enable:

```python
agent_config["user_feedback_processor_enable"] = True
agent_config["user_feedback_processor_max_interactions"] = 3
```

Unlike pre-planning HITL, this enters `UserFeedbackProcessorNode` after generation: first emit a full `final_result` snapshot; subsequent calls reuse the same `conversation_id` and send JSON strings in `message`; each successful rewrite returns partial replacements plus an updated `final_result`; `finish` or max rounds ends the session.

Supported actions: `expand`, `polish`, `shorten`, `finish`.

Payload shape (first three actions):

- `action`
- `selected_text`
- `start_offset` / `end_offset` in the current report
- optional `user_instruction`

```python
import json
import uuid
from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory

agent_factory = AgentFactory()
agent = agent_factory.create_agent(agent_config)

conversation_id = str(uuid.uuid4())
message = "Produce an industry research report"

async for chunk in agent.run(message=message, conversation_id=conversation_id, agent_config=agent_config):
    logger.debug("[Stream message from node: %s]", chunk)

feedback_message = json.dumps(
    {
        "action": "expand",
        "selected_text": "snippet to expand",
        "start_offset": 120,
        "end_offset": 136,
        "user_instruction": "Add industry background and figures",
    },
    ensure_ascii=False,
)

async for chunk in agent.run(message=feedback_message, conversation_id=conversation_id, agent_config=agent_config):
    logger.debug("[Rewrite stream message: %s]", chunk)

finish_message = json.dumps({"action": "finish"}, ensure_ascii=False)
async for chunk in agent.run(message=finish_message, conversation_id=conversation_id, agent_config=agent_config):
    logger.debug("[Finish stream message: %s]", chunk)
```

Rules:

- `selected_text` must exactly match `[start_offset, end_offset)` in the latest report or offsets are rejected.
- Selection length is capped by `service_config.user_feedback_processor_max_text_length` (default `2000`).
- Always treat the newest `final_result` as authoritative for offsets/citations.

# Further reading

- End-to-end sample: [main.py](https://gitcode.com/openJiuwen/deepsearch/blob/dev/main.py)
- API docs (English tree): [docs/en/4.Developer Guide](../)
