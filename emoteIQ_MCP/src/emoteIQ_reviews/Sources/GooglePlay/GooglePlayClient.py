import time
from typing import NamedTuple, Optional

from curl_cffi.requests import AsyncSession

from ...Config.GooglePlayConfig import GooglePlayConfig
from .GooglePlayFilters import GooglePlayFilters
from .GooglePlayRequest import HEADERS, build_request

class FetchResult(NamedTuple):
    status_code: int
    text: str
    latency_ms: int
    
def open_session(config: GooglePlayConfig) -> AsyncSession:
    return AsyncSession(impersonate=config.impersonate)

async def fetch_page(
    count: int,
    session: AsyncSession,
    config: GooglePlayConfig,
    filters: GooglePlayFilters,
    token: Optional[str] = None
) -> FetchResult:
    request = build_request(config.base_url, filters, count, token)
    started = time.perf_counter()
    response = await session.post(
        request.url, 
        data=request.body, 
        headers=HEADERS,
        timeout=config.request_timeout_s
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    return FetchResult(status_code=response.status_code, text=response.text, latency_ms=latency_ms)