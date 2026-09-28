from pymongo import ReplaceOne

from ..Models import Review
from .Mongo import get_db


def to_doc(review: Review) -> dict:
    doc = review.model_dump()
    doc["_id"] = doc.pop("id")
    return doc


async def save_reviews(reviews: list[Review]) -> None:
    if not reviews:
        return
    await get_db().reviews.bulk_write(
        [ReplaceOne({"_id": r.id}, to_doc(r), upsert=True) for r in reviews],
        ordered=False,
    )


def from_doc(doc: dict) -> Review:
    doc = dict(doc)
    doc["id"] = doc.pop("_id")
    return Review.model_validate(doc)


async def get_reviews(review_ids: list[str]) -> list[Review]:
    docs = await get_db().reviews.find({"_id": {"$in": review_ids}}).to_list()
    by_id = {doc["_id"]: doc for doc in docs}
    return [from_doc(by_id[rid]) for rid in review_ids if rid in by_id]
