from typing import Optional

from curl_cffi.requests import AsyncSession

from ...Config import Source, get_source_config
from ..BaseSource import BaseSource, PageResult, SourceParseError
from .GooglePlayClient import fetch_page, open_session
from .GooglePlayFilters import GooglePlayFilters
from .GooglePlayParser import GooglePlayParseError, parse_review, read_page

class GooglePlaySource(BaseSource):
    source = Source.GOOGLE_PLAY
    filters_model = GooglePlayFilters
    
    def __init__(self) -> None:
        self.config = get_source_config(Source.GOOGLE_PLAY)
        
    def open_session(self) -> AsyncSession:
        return open_session(self.config)
    
    async def fetch_page(
        self,
        session: AsyncSession,
        filters: GooglePlayFilters,
        count: int,
        token: Optional[str] = None,
    ) -> PageResult:
        result = await fetch_page(
            count=count, session=session, config=self.config, filters=filters, token=token
        )
        try:
            raws, next_token = read_page(result.text)
            reviews = [parse_review(raw, filters.app_id, self.config.base_url) for raw in raws]
        except (GooglePlayParseError, ValueError) as error:
            raise SourceParseError(str(error), result.text, result.status_code) from error
        return PageResult(
            reviews=reviews,
            next_token=next_token,
            raw_text=result.text,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
        )