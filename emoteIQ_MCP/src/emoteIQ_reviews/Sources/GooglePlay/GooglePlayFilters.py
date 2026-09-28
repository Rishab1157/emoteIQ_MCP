from enum import StrEnum, IntEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GooglePlaySort(StrEnum):
    NEWEST = "NEWEST"
    RATING = "RATING"
    HELPFULNESS = "HELPFULNESS"
    
class GooglePlaySentiment(IntEnum):
    POSITIVE = 1
    CRITICAL = 2


class GooglePlayFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    app_id: str
    lang: str = "en"
    country: str = "us"
    sort: GooglePlaySort = GooglePlaySort.NEWEST
    stars: Optional[int] = Field(default=None, ge=1, le=5)
    sentiment: Optional[GooglePlaySentiment] = None
    
    @model_validator(mode="after")
    def stars_or_sentiment(self) -> "GooglePlayFilters":
        if self.stars is not None and self.sentiment is not None:
            raise ValueError("Use either 'stars' or 'sentiment', not both: Google applies only sentiment.")
        return self
