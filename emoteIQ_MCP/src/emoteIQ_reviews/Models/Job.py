from datetime import datetime
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..Config import Source


class JobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Blocker(BaseModel):
    reason: str
    page_no: int
    attempts: int
    retry_after_s: Optional[int] = None


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str = Field(alias="_id")
    source: Source
    filters: dict[str, Any]
    limit: int
    batch_size: int

    parent_job_id: Optional[str] = None
    root_job_id: str
    continued_by: Optional[str] = None

    status: JobStatus = JobStatus.RUNNING
    start_token: Optional[str] = None
    continuation_token: Optional[str] = None

    fetched: int = 0
    batched: int = 0
    pages: int = 0
    served_batches: int = 0
    blocker: Optional[Blocker] = None
    error: Optional[str] = None

    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.status == JobStatus.RUNNING
