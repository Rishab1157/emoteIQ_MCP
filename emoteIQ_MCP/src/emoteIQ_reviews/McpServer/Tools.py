import asyncio
from typing import Annotated, Any, Optional

from bson import ObjectId
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from ..Config import app_config
from ..Models import JobStatus
from ..Runner.TaskManager import tasks
from ..Sources import all_sources, get_source
from ..Storage.Batches import count_batches, get_batch_doc, unexpire_batches
from ..Storage.Jobs import claim_parent, create_job, get_job, mark_served, reopen_job
from ..Storage.RawPages import unexpire_raw_pages
from ..Storage.Reviews import get_reviews
from .Server import mcp


@mcp.tool()
async def list_sources() -> dict[str, Any]:
    """List the review sources this server can fetch from, with the filters each one accepts."""
    return {
        "sources": [
            {"source": src.source.value, "filters": src.filters_model.model_json_schema()}
            for src in all_sources()
        ],
        "batch_size": {"default": app_config.default_batch_size, "min": app_config.min_batch_size, "max": app_config.max_batch_size},
    }


@mcp.tool()
async def start_review_job(
    limit: Annotated[int, Field(ge=1, description="How many reviews to fetch in this job.")],
    source: Annotated[Optional[str], Field(description="Source name from list_sources. Omit when using parent_job_id.")] = None,
    filters: Annotated[Optional[dict[str, Any]], Field(description="Filters for that source, see list_sources. Omit when using parent_job_id.")] = None,
    batch_size: Annotated[Optional[int], Field(description="Reviews per get_batch call. Defaults to the server default.")] = None,
    parent_job_id: Annotated[Optional[str], Field(description="A finished job to continue from, with the same source and filters.")] = None,
) -> dict[str, Any]:
    """Start fetching reviews in the background. Returns a job_id right away; read the reviews with get_batch."""
    batch_size = batch_size or app_config.default_batch_size
    if not app_config.min_batch_size <= batch_size <= app_config.max_batch_size:
        raise ToolError(f"batch_size must be between {app_config.min_batch_size} and {app_config.max_batch_size}.")

    if parent_job_id:
        if source or filters:
            raise ToolError("Don't pass source or filters with parent_job_id: they are copied from the parent job.")
        child_id = ObjectId()
        parent = await claim_parent(parent_job_id, child_id)
        if parent is None:
            raise ToolError(await why_not_continuable(parent_job_id))
        job = await create_job(parent.source, parent.filters, limit, batch_size, parent=parent, job_id=child_id)
    else:
        if not source or filters is None:
            raise ToolError("Pass source and filters for a new job, or parent_job_id to continue one.")
        try:
            src = get_source(source)
            validated = src.parse_filters(filters)
        except (ValueError, ValidationError) as error:
            raise ToolError(f"Invalid source or filters: {error}") from None
        job = await create_job(src.source, validated.model_dump(mode="json"), limit, batch_size)

    tasks.start(job.id)
    return {
        "job_id": job.id,
        "status": job.status,
        "source": job.source,
        "filters": job.filters,
        "limit": job.limit,
        "batch_size": job.batch_size,
        "parent_job_id": job.parent_job_id,
    }


async def why_not_continuable(parent_job_id: str) -> str:
    parent = await get_job(parent_job_id)
    if parent is None:
        return f"Job {parent_job_id!r} was not found."
    if parent.status == JobStatus.RUNNING:
        return f"Job {parent_job_id} is still running. Wait until it finishes, then continue it."
    if parent.continuation_token is None:
        return f"Job {parent_job_id} has no more reviews to continue from."
    if parent.continued_by:
        return f"Job {parent_job_id} was already continued by job {parent.continued_by}. Continue that one instead."
    return f"Job {parent_job_id} cannot be continued."


AGENT_FIELDS = {"id", "score", "text", "date"}


@mcp.tool()
async def get_batch(
    job_id: Annotated[str, Field(description="The job_id from start_review_job.")],
    batch_no: Annotated[int, Field(ge=1, description="Batch number, starting at 1. Ask for 1, 2, 3 ... in order.")],
    ctx: Context,
) -> dict[str, Any]:
    """Get one batch of reviews. Waits briefly if the batch is still being fetched. Stop when last_batch is true."""
    job = await get_job(job_id)
    if job is None:
        raise ToolError(f"Job {job_id!r} was not found.")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + app_config.get_batch_wait_s
    doc = await get_batch_doc(job_id, batch_no)
    while doc is None:
        job = await get_job(job_id)
        if job.status != JobStatus.RUNNING:
            total = await count_batches(job_id)
            return {
                "job_id": job_id, "batch_no": batch_no, "ready": False, "reviews": [],
                "status": job.status, "last_batch": True, "total_batches": total,
                "message": f"Job is {job.status} and has only {total} batch(es). There is no batch {batch_no}.",
                "blocker": job.blocker.model_dump() if job.blocker else None,
            }
        if loop.time() >= deadline:
            return {
                "job_id": job_id, "batch_no": batch_no, "ready": False, "reviews": [],
                "status": job.status, "last_batch": False,
                "message": f"Batch {batch_no} is not ready yet ({job.fetched} of {job.limit} fetched). Call get_batch again.",
            }
        await ctx.report_progress(job.fetched, job.limit, message=f"Fetching reviews: {job.fetched} of {job.limit}")
        await asyncio.sleep(1)
        doc = await get_batch_doc(job_id, batch_no)

    reviews = await get_reviews(doc["review_ids"])
    await mark_served(job_id, batch_no)
    job = await get_job(job_id)
    total = await count_batches(job_id)
    return {
        "job_id": job_id, "batch_no": batch_no, "ready": True,
        "reviews": [review.model_dump(include=AGENT_FIELDS, mode="json") for review in reviews],
        "status": job.status,
        "last_batch": job.status != JobStatus.RUNNING and batch_no == total,
        "fetched": job.fetched, "limit": job.limit,
    }


@mcp.tool()
async def job_status(
    job_id: Annotated[str, Field(description="The job_id from start_review_job.")],
) -> dict[str, Any]:
    """Show a job's progress, why it stopped, and whether it can be continued."""
    job = await get_job(job_id)
    if job is None:
        raise ToolError(f"Job {job_id!r} was not found.")
    return {
        "job_id": job.id,
        "status": job.status,
        "is_active": job.is_active,
        "source": job.source,
        "filters": job.filters,
        "limit": job.limit,
        "batch_size": job.batch_size,
        "fetched": job.fetched,
        "batches_ready": await count_batches(job.id),
        "served_batches": job.served_batches,
        "can_continue": not job.is_active and job.continuation_token is not None and job.continued_by is None,
        "parent_job_id": job.parent_job_id,
        "root_job_id": job.root_job_id,
        "continued_by": job.continued_by,
        "blocker": job.blocker.model_dump() if job.blocker else None,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@mcp.tool()
async def retry_failed(
    job_id: Annotated[str, Field(description="A blocked or failed job to restart from where it stopped.")],
) -> dict[str, Any]:
    """Restart a blocked or failed job from its last saved position. Read new batches with get_batch as before."""
    job = await reopen_job(job_id)
    if job is None:
        current = await get_job(job_id)
        if current is None:
            raise ToolError(f"Job {job_id!r} was not found.")
        if current.continued_by:
            raise ToolError(f"Job {job_id} was already continued by job {current.continued_by}; retry that one instead.")
        raise ToolError(f"Job {job_id} is {current.status}. Only blocked or failed jobs can be retried.")
    await unexpire_batches(job.id)
    await unexpire_raw_pages(job.id)
    tasks.start(job.id)
    return {
        "job_id": job.id,
        "status": job.status,
        "fetched": job.fetched,
        "next_batch_no": await count_batches(job.id) + 1,
    }
