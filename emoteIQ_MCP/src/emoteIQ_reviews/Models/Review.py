from datetime import datetime
from typing import Any, Optional
from pydantic import Field, BaseModel, ConfigDict
from ..Config import Source


class Review(BaseModel):
    """One review in the common shape, whatever the source."""
    
    model_config = ConfigDict(extra="forbid")
    
    id: str
    source: Source
    target_id: str
    author: Optional[str] = None
    score: Optional[int] = None
    text: Optional[str] = None
    date: Optional[datetime] = None
    likes: Optional[int] = None
    reply_text: Optional[str] = None
    reply_date: Optional[datetime] = None
    url: Optional[str] = None
    extra: dict[str, Any] = Field(default_factory=dict)