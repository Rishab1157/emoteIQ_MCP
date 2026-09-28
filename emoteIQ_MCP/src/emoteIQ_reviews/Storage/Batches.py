from datetime import timedelta
from typing import Optional

from ..Config import app_config
from .Jobs import now_utc
from .Mongo import get_db


def batch_id(job_id: str, batch_no: int) -> str:
    return f"{job_id}:{batch_no}"


async def save_batch(job_id: str, batch_no: int, review_ids: list[str]) -> None:
    await get_db().batches.replace_one(
        {"_id": batch_id(job_id, batch_no)},
        {
            "job_id": job_id,
            "batch_no": batch_no,
            "review_ids": review_ids,
            "created_at": now_utc(),
        },
        upsert=True,
    )


async def get_batch_doc(job_id: str, batch_no: int) -> Optional[dict]:
    return await get_db().batches.find_one({"_id": batch_id(job_id, batch_no)})


async def count_batches(job_id: str) -> int:
    return await get_db().batches.count_documents({"job_id": job_id})


async def expire_batches(job_id: str) -> None:
    await get_db().batches.update_many(
        {"job_id": job_id},
        {"$set": {"expires_at": now_utc() + timedelta(days=app_config.batches_ttl_days)}},
    )


async def unexpire_batches(job_id: str) -> None:
    await get_db().batches.update_many({"job_id": job_id}, {"$unset": {"expires_at": ""}})
