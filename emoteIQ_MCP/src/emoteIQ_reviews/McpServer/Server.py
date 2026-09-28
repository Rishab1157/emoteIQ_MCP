import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from ..Config import app_config
from ..Events.EventLog import events
from ..Runner.TaskManager import tasks
from ..Storage.Mongo import close_db, ensure_indexes

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncGenerator[dict, None]:
    await ensure_indexes()
    await events.start()
    resumed = await tasks.resume_running()
    log.info("emoteIQ reviews server ready, resumed %d running job(s)", len(resumed))
    try:
        yield {}
    finally:
        await tasks.shutdown()
        await events.stop()
        await close_db()


mcp = MCPServer(
    "emoteIQ-reviews",
    instructions=(
        "Fetch app reviews in batches. Call list_sources to see sources and filters, "
        "start_review_job to begin, then get_batch with batch_no 1, 2, 3 ... until last_batch is true. "
        "To get more reviews after a job finishes, start a new job with parent_job_id."
    ),
    lifespan=lifespan,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from . import Tools  # noqa: F401  (registers the tools on `mcp`)
    mcp.run(transport="streamable-http", host=app_config.mcp_host, port=app_config.mcp_port)
