# emoteIQ Agent

A CrewAI agent that tests the emoteIQ reviews MCP server end to end: it starts a review job, reads every batch with `get_batch` until `last_batch`, and writes a short report.

```powershell
uv run python agent.py        # the MCP server must be running (it waits up to 30 s for it)
```

- `client.py`: keeps one MCP session open and exposes `initialize()` and `call_tool()` for the CrewAI tools.
- `agent.py`: event-bus logging (LLM calls and tool calls), the Ollama LLM (`qwen2.5:14b`), the tool wrappers, the agent and its task.

See the [main README](../README.md) for the full workflow.
