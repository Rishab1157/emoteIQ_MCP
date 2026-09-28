import json
from typing import Optional

from crewai import Agent, Crew, Task
from crewai.events.event_bus import crewai_event_bus
from crewai.events.types.llm_events import LLMCallCompletedEvent, LLMCallFailedEvent, LLMCallStartedEvent
from crewai.events.types.tool_usage_events import ToolUsageErrorEvent, ToolUsageFinishedEvent, ToolUsageStartedEvent
from crewai.llm import LLM
from crewai.tools import tool

from client import call_tool, close, initialize

# ============================================================
# EVENT BUS LOGGING (LLM calls and tool calls)
# ============================================================

_llm_call_count = 0


@crewai_event_bus.on(LLMCallStartedEvent)
def _on_llm_call_started(source, event):
    global _llm_call_count
    _llm_call_count += 1
    print(f"\n===== LLM CALL #{_llm_call_count} : REQUEST =====")
    print(f"Model: {event.model}")
    print(f"Tools available: {[t['function']['name'] for t in (event.tools or [])]}")
    for message in event.messages or []:
        print(f"  [{message.get('role')}] {message.get('content')}")


@crewai_event_bus.on(LLMCallCompletedEvent)
def _on_llm_call_completed(source, event):
    print(f"----- LLM CALL #{_llm_call_count} : RESPONSE -----")
    print(f"Call type: {event.call_type}")
    print(f"Response: {event.response}")


@crewai_event_bus.on(LLMCallFailedEvent)
def _on_llm_call_failed(source, event):
    print(f"----- LLM CALL #{_llm_call_count} : FAILED -----")
    print(f"Error: {event.error}")


@crewai_event_bus.on(ToolUsageStartedEvent)
def _on_tool_started(source, event):
    print(f"\n>>>>> TOOL START: {event.tool_name}  args={event.tool_args}")


@crewai_event_bus.on(ToolUsageFinishedEvent)
def _on_tool_finished(source, event):
    output = str(event.output)
    print(f"<<<<< TOOL DONE: {event.tool_name}  ({len(output)} chars)  {output[:400]}{' ...' if len(output) > 400 else ''}")


@crewai_event_bus.on(ToolUsageErrorEvent)
def _on_tool_error(source, event):
    print(f"!!!!! TOOL ERROR: {event.tool_name}  {event.error}")


# ============================================================
# OLLAMA LLM
# ============================================================

llm = LLM(
    model="ollama/qwen2.5:14b",
    base_url="http://192.168.3.90:11434",
)


# ============================================================
# MCP TOOL WRAPPERS
# ============================================================

def _mcp(name: str, arguments: dict) -> str:
    response = call_tool(name, arguments)
    print(f"    [mcp] {name}({arguments}) -> {json.dumps(response)[:300]}")
    return json.dumps(response)


@tool("list_review_sources")
def list_review_sources() -> str:
    """List the review sources the MCP server supports and the filters each accepts."""
    return _mcp("list_sources", {})


@tool("start_review_job")
def start_review_job(app_id: str, limit: int, batch_size: int, stars: Optional[int] = None) -> str:
    """Start fetching Google Play reviews for app_id. Returns a job_id. stars (1-5) is optional."""
    filters = {"app_id": app_id}
    if stars:
        filters["stars"] = stars
    return _mcp("start_review_job", {"source": "Google Play", "filters": filters, "limit": limit, "batch_size": batch_size})


@tool("get_review_batch")
def get_review_batch(job_id: str, batch_no: int) -> str:
    """Get batch number batch_no (1, 2, 3 ...) of reviews for job_id. Stop when last_batch is true."""
    return _mcp("get_batch", {"job_id": job_id, "batch_no": batch_no})


@tool("get_job_status")
def get_job_status(job_id: str) -> str:
    """Get the status and progress of a review job."""
    return _mcp("job_status", {"job_id": job_id})


# ============================================================
# AGENT
# ============================================================

agent = Agent(
    role="App Review Analyst",
    goal="Read every batch of app reviews from the MCP server and summarise what users say.",
    backstory="You analyse Google Play reviews. You always get reviews through the MCP tools, one batch at a time.",
    llm=llm,
    tools=[list_review_sources, start_review_job, get_review_batch, get_job_status],
    verbose=True,
)


# ============================================================
# TASK
# ============================================================

task = Task(
    description="""
    Complete these steps strictly in order:

    1. Call start_review_job with app_id="com.supercell.brawlstars", limit=30, batch_size=10.
       Remember the job_id it returns.

    2. Call get_review_batch with that job_id and batch_no=1.
       Then batch_no=2, then batch_no=3, and so on.
       Keep going until a response has "last_batch": true. Do not skip a batch number.
       If a response has "ready": false and "last_batch": false, call the same batch_no again.

    3. For every batch, note how many reviews have score 4-5 (positive) and 1-2 (negative),
       and the main topics people mention.

    4. Call get_job_status with the job_id and report its final status and fetched count.

    You MUST use the tools for every step. Do not invent reviews.
    """,
    expected_output="""
    A short report with:
    - The job_id and its final status and fetched count
    - For each batch: batch number, positive count, negative count, main topics
    - An overall summary of what users like and dislike
    """,
    agent=agent,
)


crew = Crew(agents=[agent], tasks=[task], verbose=True)


if __name__ == "__main__":
    print("MCP tools on server:", initialize())
    try:
        result = crew.kickoff()
        print("\n========== FINAL RESULT ==========")
        print(result)
    finally:
        close()
