from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from ..Config import Source, app_config
from ..Models import Blocker, Job, JobStatus
from .Mongo import get_db


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def create_job(
    source: Source,
    filters: dict[str, Any],
    limit: int,
    batch_size: int,
    parent: Optional[Job] = None,
    job_id: Optional[ObjectId] = None,
) -> Job:
    job_id = str(job_id or ObjectId())
    now = now_utc()
    job = Job(
        _id=job_id,
        source=source,
        filters=filters,
        limit=limit,
        batch_size=batch_size,
        parent_job_id=parent.id if parent else None,
        root_job_id=parent.root_job_id if parent else job_id,
        start_token=parent.continuation_token if parent else None,
        created_at=now,
        updated_at=now,
    )
    await get_db().jobs.insert_one(job.model_dump(by_alias=True))
    return job


async def get_job(job_id: str) -> Optional[Job]:
    doc = await get_db().jobs.find_one({"_id": job_id})
    return Job.model_validate(doc) if doc else None


async def claim_parent(parent_id: str, child_id: ObjectId) -> Optional[Job]:
    doc = await get_db().jobs.find_one_and_update(
        {
            "_id": parent_id,
            "continued_by": None,
            "status": {"$ne": JobStatus.RUNNING},
            "continuation_token": {"$ne": None},
        },
        {"$set": {"continued_by": str(child_id), "updated_at": now_utc()}},
        return_document=ReturnDocument.AFTER,
    )
    return Job.model_validate(doc) if doc else None


async def save_progress(
    job_id: str,
    fetched: int,
    batched: int,
    pages: int,
    continuation_token: Optional[str],
) -> None:
    await get_db().jobs.update_one(
        {"_id": job_id},
        {"$set": {
            "fetched": fetched,
            "batched": batched,
            "pages": pages,
            "continuation_token": continuation_token,
            "updated_at": now_utc(),
        }},
    )


async def finish_job(
    job_id: str,
    status: JobStatus,
    blocker: Optional[Blocker] = None,
    error: Optional[str] = None,
) -> None:
    now = now_utc()
    await get_db().jobs.update_one(
        {"_id": job_id},
        {"$set": {
            "status": status,
            "blocker": blocker.model_dump() if blocker else None,
            "error": error,
            "completed_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(days=app_config.jobs_ttl_days),
        }},
    )


async def mark_served(job_id: str, batch_no: int) -> None:
    await get_db().jobs.update_one(
        {"_id": job_id},
        {"$max": {"served_batches": batch_no}, "$set": {"updated_at": now_utc()}},
    )
    
async def running_job_ids() -> list[str]:
    docs = await get_db().jobs.find({"status": JobStatus.RUNNING}, {"_id": 1}).to_list()
    return [doc["_id"] for doc in docs]



async def reopen_job(job_id: str) -> Optional[Job]:
    doc = await get_db().jobs.find_one_and_update(
        {
            "_id": job_id,
            "status": {"$in": [JobStatus.BLOCKED, JobStatus.FAILED]},
            "continued_by": None,
        },
        {
            "$set": {"status": JobStatus.RUNNING, "blocker": None, "error": None, "updated_at": now_utc()},
            "$unset": {"completed_at": "", "expires_at": ""},
        },
        return_document=ReturnDocument.AFTER,
    )
    return Job.model_validate(doc) if doc else None
