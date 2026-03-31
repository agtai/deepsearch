# `openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory`

## `AgentFactory`
```python
class openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory.AgentFactory()
```
**AgentFactory** builds Agent instances from `search_mode` and `execution_method` in config.

> **Module side effect**: importing sets env var `WORKFLOW_EXECUTE_TIMEOUT` from `Config().service_config.workflow_execution_timeout`.

### `__init__`
```python
__init__()
```
Builds the execution-method → Agent class map:

- `"parallel"` → `DeepresearchAgent`
- `dependency_driving` → `DeepresearchDependencyAgent`
- `search` → `DeepsearchAgent`  # **search mode not supported yet**

**Example**:

```python
>>> from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory
>>> factory = AgentFactory()
>>> print(factory.agent_map)
{...}
```

### `create_agent`
```python
create_agent(agent_config: dict)
```
Validates config and returns the matching Agent instance.

**Parameters**:
- **agent_config** (dict): Passed through `validate_agent_required_field` and `AgentConfig.model_validate`.

**Returns**:
- `DeepresearchAgent` for parallel execution (default).

**Raises**:
- `CustomValueException` on validation failure or unknown execution method.

**Example**:
```python
>>> from openjiuwen_deepsearch.framework.openjiuwen.agent.agent_factory import AgentFactory
>>> factory = AgentFactory()

>>> # Example 1: parallel
>>> agent_config = {
...     "llm_config": {"model_name": "gpt-4", "model_type": "openai"},
...     "search_mode": "research",
...     "execution_method": "parallel",
... }
>>> agent = factory.create_agent(agent_config)
>>> print(type(agent).__name__)
DeepresearchAgent

>>> # Example 2: dependency-driven
>>> agent_config = {
...     "llm_config": {"model_name": "gpt-4", "model_type": "openai"},
...     "search_mode": "research",
...     "execution_method": "dependency_driving",
... }
>>> agent = factory.create_agent(agent_config)
>>> print(type(agent).__name__)
DeepresearchDependencyAgent
```
