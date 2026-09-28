import asyncio
from typing import Any, NamedTuple, Optional

from pydantic import BaseModel

from ..Events.EventLog import Topic, events
from ..Sources import BaseSource, PageResult, SourceParseError
from .Classify import Outcome, classify

RETRYABLE = {Outcome.HTTP_ERROR, Outcome.NETWORK_ERROR, Outcome.EMPTY}


class PageAttempt(NamedTuple):
    outcome: Outcome
    page: Optional[PageResult]
    attempts: int
    error: Optional[str]
    raw_text: Optional[str]


async def fetch_with_retries(
    source: BaseSource,
    session: Any,
    filters: BaseModel,
    *,
    job_id: str,
    page_no: int,
    count: int,
    token: Optional[str],
    max_retries: int,
) -> PageAttempt:
    attempt = 0
    while True:
        attempt += 1
        page, error, raw_text = None, None, None
        try:
            page = await source.fetch_page(session, filters, count, token)
            outcome = classify(page)
            raw_text = page.raw_text
        except SourceParseError as parse_error:
            outcome, error, raw_text = Outcome.PARSE_ERROR, str(parse_error), parse_error.raw_text
        except Exception as network_error:
            outcome, error = Outcome.NETWORK_ERROR, f"{type(network_error).__name__}: {network_error}"

        await events.emit(Topic.FETCH_EVENTS, job_id, {
            "job_id": job_id,
            "page_no": page_no,
            "attempt": attempt,
            "status": outcome,
            "http_status": page.status_code if page else None,
            "review_count": len(page.reviews) if page else 0,
            "latency_ms": page.latency_ms if page else None,
            "token_in": token,
            "token_out": page.next_token if page else None,
            "error": error,
        })

        allowed = 1 if (outcome == Outcome.EMPTY and page_no == 1) else max_retries
        if outcome not in RETRYABLE or attempt > allowed:
            return PageAttempt(outcome, page, attempt, error, raw_text)
        await asyncio.sleep(2 ** (attempt - 1))
