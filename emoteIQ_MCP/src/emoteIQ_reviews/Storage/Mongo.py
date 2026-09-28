from typing import Optional

from pymongo import ASCENDING, AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from ..Config import app_config

_client: Optional[AsyncMongoClient] = None


def get_db() -> AsyncDatabase:
    global _client
    if _client is None:
        _client = AsyncMongoClient(app_config.mongo_uri, tz_aware=True)
    return _client[app_config.mongo_db]


async def close_db() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None


async def ensure_indexes() -> None:
    db = get_db()

    await db.jobs.create_index([("root_job_id", ASCENDING)])
    await db.jobs.create_index([("status", ASCENDING)])
    await db.jobs.create_index("expires_at", expireAfterSeconds=0)

    await db.raw_pages.create_index([("job_id", ASCENDING), ("page_no", ASCENDING)], unique=True)
    await db.raw_pages.create_index("expires_at", expireAfterSeconds=0)

    await db.reviews.create_index([("target_id", ASCENDING), ("date", ASCENDING)])

    await db.batches.create_index([("job_id", ASCENDING), ("batch_no", ASCENDING)], unique=True)
    await db.batches.create_index("expires_at", expireAfterSeconds=0)
