# `openjiuwen_deepsearch.framework.openjiuwen.agent.main_graph_nodes`

Main-graph and key subgraph nodes (aligned with current code).

## Main graph nodes

### `StartNode`
```python
class StartNode(Start)
```
Workflow entry: validate/default inputs, init `SearchContext` (`query`, `session_id`, `messages`, `search_mode`, `report_template`), merge `agent_config` + `service_config` into runtime `config`, set `thread_id` and `interrupt_feedback`.

### `EntryNode`
```python
class EntryNode(BaseNode)
```
Language detection/routing via `classify_query`, normalize locale (`zh-CN` / `en-US`); on failure set `final_result.exception_info` and stop.

### `GenerateQuestionsNode`
```python
class GenerateQuestionsNode(BaseNode)
```
HITL clarifying questions via `query_interpreter` with `workflow_max_gen_question_retry_num` retries; success → `search_context.questions`; failure → `exception_info`.

### `FeedbackHandlerNode`
```python
class FeedbackHandlerNode(BaseNode)
```
Reads user feedback (`workflow_feedback_mode` `cmd`/`web`); `FINISH_TASK` ends run; invalid input → `exception_info`.

### `OutlineNode`
```python
class OutlineNode(BaseNode)
```
Outline generation: `report_template` present uses `outliner_template` prompt else `outliner`; retries via `outliner_max_generate_outline_retry_num`; streams outline to `search_context.current_outline`.

### `DependencyOutlineNode`
```python
class DependencyOutlineNode(OutlineNode)
```
Dependency-aware outline via `dep_driving_outliner`; same retry/stream behavior as `OutlineNode`.

### `OutlineInteractionNode`
```python
class OutlineInteractionNode(BaseNode)
```
Outline HITL: if `outline_interaction_enabled` is off → `EditorTeamNode`; if rounds ≥ `outline_interaction_max_rounds` → notify and continue; reads feedback (`cmd`/`web`) as JSON:

```json
{
  "interrupt_feedback": "accepted/revise_comment/revise_outline",
  "feedback": "User text: comments for revise_comment, or new outline for revise_outline"
}
```

Actions: `accepted` → `EditorTeamNode`; `revise_comment` / `revise_outline` → `OutlineNode`; history in `search_context.outline_interactions`.

### `DependencyOutlineInteractionNode`
```python
class DependencyOutlineInteractionNode(OutlineInteractionNode)
```
Same as parent; on `accepted` routes to `DependencyEditorTeamNode` instead of `EditorTeamNode`.

### `EditorTeamNode`
```python
class EditorTeamNode(BaseNode)
```
(`editor_team_manager_node.py`) Runs concurrent sub-workflows and forwards streamed subgraph output.

### `DependencyEditorTeamNode`
```python
class DependencyEditorTeamNode(EditorTeamNode)
```
Dependency-layer pipeline: per layer, parallelize previous-layer writing with current-layer reasoning; merges subgraph streams.

### `ReporterNode`
```python
class ReporterNode(BaseNode)
```
Final report via `Reporter.generate_report`; failures → `exception_info`; success → `search_context.report` and `all_classified_contents`.

### `SourceTracerNode`
```python
class SourceTracerNode(BaseNode)
```
Skips if `source_tracer_research_trace_source_switch` is off; validates citations, fills `final_result.response_content` / `citation_messages` with offsets (`citation_start_offset`, `citation_end_offset`) for later local edits; failures → `exception_info`.

### `UserFeedbackProcessorNode`
```python
class UserFeedbackProcessorNode(BaseNode)
```
Post-report local edits when `user_feedback_processor_enable`: first pass emits full `final_result` snapshot; parses JSON actions `expand` / `shorten` / `polish` / `finish`; updates citations/infer messages; tracks `feedback_interaction_count` and `rewrite_history`; stops at max interactions or `finish`.

### `SourceTracerInferNode`
```python
class SourceTracerInferNode(BaseNode):
```
Skips if `source_tracer_infer_switch` is off; builds provenance reasoning artifacts → `final_result.infer_messages`; failures → `exception_info`.

### `EndNode`
```python
class EndNode(End)
```
Emits `final_result` JSON and `"ALL END"`.

---

## Editor-team subgraph (`reasoning_writing_graph/editor_team_nodes.py`)

`SectionStartNode` → `ResearchPlanReasoningNode` → (`InfoCollectorNode` → `ResearchPlanReasoningNode`)* → `SubReporterNode` → `SubSourceTracerNode` → `SectionEndNode`.

---

## Collector subgraph (`collector_graph/`)

`StartNode` → `GenerateQueryNode` → `InfoRetrievalNode` → `SupervisorNode` → (loop)* → `SummaryNode` → `GraphEndNode` → `End`.

---

## Dependency reasoning subgraph (`dependency_reasoning_team_nodes.py`)

`SectionReasoningStartNode` → `DependencyPlanReasoningNode` → (`DependencyInfoCollectorNode` → `DependencyPlanReasoningNode`)* → `SectionReasoningEndNode`.

---

## Dependency writing subgraph (`dependency_writing_team_nodes.py`)

`SectionWritingStartNode` → `SubReporterNode` → `SubSourceTracerNode` → `SectionEndNode`.

---

## Execution sketches

### Parallel main graph
```
StartNode -> EntryNode -> [GenerateQuestionsNode -> FeedbackHandlerNode] -> OutlineNode
-> [OutlineInteractionNode -> OutlineNode]* -> EditorTeamNode -> ReporterNode -> SourceTracerNode -> EndNode
-> SourceTracerInferNode -> UserFeedbackProcessorNode -> EndNode
```

### Dependency-driven main graph
```text
StartNode -> EntryNode -> [GenerateQuestionsNode -> FeedbackHandlerNode] -> DependencyOutlineNode
-> [DependencyOutlineInteractionNode -> DependencyOutlineNode]*
-> DependencyEditorTeamNode -> ReporterNode -> SourceTracerNode
-> SourceTracerInferNode -> UserFeedbackProcessorNode -> EndNode
```

`DependencyEditorTeamNode` pipelines dependency layers (“previous writing + current reasoning” in parallel per layer).

### Editor-team subgraph
```
SectionStartNode -> ResearchPlanReasoningNode -> [InfoCollectorNode -> ResearchPlanReasoningNode]*
-> SubReporterNode -> SubSourceTracerNode -> SectionEndNode
```

### Collector subgraph
```
StartNode -> GenerateQueryNode -> InfoRetrievalNode -> SupervisorNode
-> [InfoRetrievalNode -> SupervisorNode]* -> SummaryNode -> GraphEndNode -> End
```

### Dependency reasoning subgraph
```
SectionReasoningStartNode -> DependencyPlanReasoningNode -> [DependencyInfoCollectorNode -> DependencyPlanReasoningNode]*
-> SectionReasoningEndNode
```

### Dependency writing subgraph
```
SectionWritingStartNode -> SubReporterNode -> SubSourceTracerNode -> SectionEndNode
```
