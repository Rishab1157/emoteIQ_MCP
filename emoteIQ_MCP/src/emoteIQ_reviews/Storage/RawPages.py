from datetime import timedelta
from typing import Optional

from ..Config import Source, app_config
from .Jobs import now_utc
from .Mongo import get_db


def raw_page_id(job_id: str, page_no: int) -> str:
    return f"{job_id}:{page_no}"


async def save_raw_page(
    job_id: str,
    source: Source,
    page_no: int,
    start_pos: int,
    count: int,
    token_in: Optional[str],
    token_out: Optional[str],
    status_code: int,
    raw_text: str,
    review_ids: list[str],
) -> None:
    await get_db().raw_pages.replace_one(
        {"_id": raw_page_id(job_id, page_no)},
        {
            "job_id": job_id,
            "source": source,
            "page_no": page_no,
            "start_pos": start_pos,
            "count": count,
            "token_in": token_in,
            "token_out": token_out,
            "status_code": status_code,
            "raw": raw_text,
            "review_ids": review_ids,
            "fetched_at": now_utc(),
        },
        upsert=True,
    )


async def expire_raw_pages(job_id: str) -> None:
    await get_db().raw_pages.update_many(
        {"job_id": job_id},
        {"$set": {"expires_at": now_utc() + timedelta(days=app_config.raw_pages_ttl_days)}},
    )


async def pending_review_ids(job_id: str, batched: int, fetched: int) -> list[str]:
    if fetched <= batched:
        return []
    pages = await get_db().raw_pages.find(
        {"job_id": job_id, "$expr": {"$gt": [{"$add": ["$start_pos", "$count"]}, batched]}},
        {"start_pos": 1, "review_ids": 1},
    ).sort("page_no", 1).to_list()
    ids = [rid for page in pages for rid in page["review_ids"]]
    offset = batched - pages[0]["start_pos"] if pages else 0
    return ids[offset:fetched - batched + offset]


async def unexpire_raw_pages(job_id: str) -> None:
    await get_db().raw_pages.update_many({"job_id": job_id}, {"$unset": {"expires_at": ""}})
