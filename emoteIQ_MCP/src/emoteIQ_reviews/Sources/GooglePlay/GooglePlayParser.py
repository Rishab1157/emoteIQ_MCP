import json 
from urllib.parse import urlencode

from ...Config import Source
from ...Models import Review

from datetime import datetime, timezone
from typing import Any, Optional

def dig(data: Any, *path: int) -> Any:
    for index in path:
        if not isinstance(data, list) or index >= len(data):
            return None
        data = data[index]
    return data

def to_datetime(value: Any) -> Optional[datetime]:
    seconds = dig(value, 0)
    if seconds is None:
        return None
    nanos = dig(value, 1) or 0
    return datetime.fromtimestamp(seconds + nanos / 1e9, tz=timezone.utc)

class GooglePlayParseError(Exception):
    pass


def read_page(text: str) -> tuple[list[list], Optional[str]]:
    try:
        frames = json.loads(text[text.index("\n") + 1:])
    except ValueError as error:
        raise GooglePlayParseError(f"Response is not valid batchexecute JSON: {error}") from None

    frame = next((f for f in frames if dig(f, 0) == "wrb.fr"), None)
    if frame is None:
        raise GooglePlayParseError("No 'wrb.fr' frame in response")

    payload = dig(frame, 2)
    if payload is None:
        return [], None

    data = json.loads(payload)
    return dig(data, 0) or [], dig(data, 1, 1)

def read_criterias(raw: Any) -> list[dict]:
    criterias = []
    for item in dig(raw, 12, 0) or []:
        rating = dig(item, 1, 0) if dig(item, 1) is not None else dig(item, 2, 0)
        criterias.append({"criteria": dig(item, 0), "rating": rating})
    return criterias

ID_PREFIX = Source.GOOGLE_PLAY.name.lower()

def parse_review(raw: list, app_id: str, base_url: str) -> Review:
    review_id = dig(raw, 0)
    reply = dig(raw, 7)
    return Review(
        id=f"{ID_PREFIX}:{review_id}",
        source=Source.GOOGLE_PLAY,
        target_id=app_id,
        author=dig(raw, 1, 0),
        score=dig(raw, 2),
        text=dig(raw, 4),
        date=to_datetime(dig(raw, 5)),
        likes=dig(raw, 6),
        reply_text=dig(reply, 1),
        reply_date=to_datetime(dig(reply, 2)),
        url=f"{base_url}/store/apps/details?{urlencode({'id': app_id, 'reviewId': review_id})}",
        extra={
            "version": dig(raw, 10),
            "reply_author": dig(reply, 0),
            "author_image": dig(raw, 1, 1, 3, 2),
            "criterias": read_criterias(raw),
        },
    )