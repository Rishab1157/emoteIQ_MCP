from abc import ABC, abstractmethod
from typing import Any, NamedTuple, Optional

from pydantic import BaseModel
from ..Config import Source
from ..Models import Review


class SourceParseError(Exception):
    def __init__(self, message: str, raw_text: str, status_code: int) -> None:
        super().__init__(message)
        self.raw_text = raw_text
        self.status_code = status_code


class PageResult(NamedTuple):
    reviews: list[Review]
    next_token: Optional[str]   
    raw_text: str
    status_code: int             
    latency_ms: int
    
class BaseSource(ABC):
    source: Source
    filters_model: type[BaseModel]
    
    def parse_filters(self, filters: dict[str, Any]) -> BaseModel:
        return self.filters_model.model_validate(filters)
    
    @abstractmethod
    def open_session(self) -> Any: ...
    
    @abstractmethod
    async def fetch_page(
        self, session: Any, filters: BaseModel, count: int, token: Optional[str] = None
    ) -> PageResult: ...