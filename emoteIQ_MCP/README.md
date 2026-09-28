# emoteIQ Reviews MCP server

Fetches app reviews in batches for AI agents over MCP (Streamable HTTP).

```powershell
docker compose up -d                            # MongoDB + Kafka
uv run python -m emoteIQ_reviews.McpServer      # http://127.0.0.1:8000/mcp
```

How a job flows through the code, the tools, the data, debugging and configuration: see the [main README](../README.md).
