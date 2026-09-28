import asyncio
from typing import NamedTuple, Optional

from ..Config import app_config, get_source_config
from ..Events.EventLog import Topic, events
from ..Models import Blocker, Job, JobStatus
from ..Sources import get_source
from ..Storage.Batches import expire_batches, save_batch
from ..Storage.Jobs import finish_job, get_job, save_progress
from ..Storage.RawPages import expire_raw_pages, pending_review_ids, save_raw_page
from ..Storage.Reviews import save_reviews
from .Batcher import Batcher
from .Classify import Outcome
from .Fetcher import PageAttempt, fetch_with_retries


class Stop(NamedTuple):
    status: JobStatus
    blocker: Optional[Blocker] = None
    error: Optional[str] = None
    
    
class JobRunner:
    def __init__(self, job: Job, batcher: Batcher) -> None:
        self.job = job
        self.batcher = batcher
        self.source = get_source(job.source)
        self.config = get_source_config(job.source)
        self.filters = self.source.parse_filters(job.filters)
        self.fetched = job.fetched
        self.batched = job.batched
        self.pages = job.pages
        self.token = job.continuation_token if job.pages else job.start_token
        
    @classmethod
    async def load(cls, job_id: str) -> "JobRunner":
        job = await get_job(job_id)
        if job is None:
            raise ValueError(f"Job {job_id!r} not found")
        pending = await pending_review_ids(job.id, job.batched, job.fetched)
        batcher = Batcher(
            job.batch_size,
            next_batch_no=-(-job.batched // job.batch_size) + 1,
            pending=pending,
        )
        return cls(job, batcher)
    
    async def wait_for_reader(self) -> bool:
        cap = app_config.fetch_ahead_pages * self.config.page_size
        while True:
            job = await get_job(self.job.id)
            if job.status != JobStatus.RUNNING:
                return False
            unread = self.fetched - job.served_batches * job.batch_size
            if unread < cap:
                return True
            await asyncio.sleep(1)
    
    async def run_pages(self) -> Stop:
        async with self.source.open_session() as session:
            while self.fetched < self.job.limit:
                if not await self.wait_for_reader():
                    return Stop(JobStatus.CANCELLED)
                
                page_no = self.pages + 1
                count = min(self.config.page_size, self.job.limit - self.fetched)
                attempt = await fetch_with_retries(
                    self.source, session, self.filters,
                    job_id=self.job.id, page_no=page_no, count=count,
                    token=self.token, max_retries=self.config.max_retries,
                )
                
                if attempt.outcome in (Outcome.OK, Outcome.END):
                    reached_limit = self.fetched + len(attempt.page.reviews) >= self.job.limit
                    final = attempt.outcome == Outcome.END or reached_limit
                    await self.store_page(page_no, attempt, final)
                    if final:
                        return Stop(JobStatus.COMPLETED)
                elif attempt.outcome == Outcome.EMPTY and page_no == 1:
                    self.token = None
                    return Stop(JobStatus.COMPLETED)
                elif attempt.outcome == Outcome.PARSE_ERROR:
                    await save_raw_page(
                        self.job.id, self.source.source, page_no,
                        start_pos=self.fetched, count=0,
                        token_in=self.token, token_out=None,
                        status_code=0, raw_text=attempt.raw_text or "", review_ids=[],
                    )
                    return Stop(JobStatus.FAILED, error=attempt.error)
                else:
                    blocker = Blocker(reason=attempt.outcome, page_no=page_no, attempts=attempt.attempts)
                    return Stop(JobStatus.BLOCKED, blocker=blocker)
        return Stop(JobStatus.COMPLETED)
    
    async def store_page(self, page_no: int, attempt: PageAttempt, final: bool) -> None:
        page = attempt.page
        review_ids = [review.id for review in page.reviews]
        
        await save_raw_page(
            self.job.id, self.source.source, page_no,
            start_pos=self.fetched, count=len(review_ids),
            token_in=self.token, token_out=page.next_token,
            status_code=page.status_code, raw_text=page.raw_text, review_ids=review_ids,
        )
        await save_reviews(page.reviews)
        for batch in self.batcher.add(review_ids, final=final):
            await save_batch(self.job.id, batch.batch_no, batch.review_ids)
            self.batched += len(batch.review_ids)
            
        self.fetched += len(review_ids)
        self.pages = page_no
        self.token = page.next_token
        await save_progress(self.job.id, self.fetched, self.batched, self.pages, self.token)

    async def run(self) -> Stop:
        await events.emit(Topic.JOB_EVENTS, self.job.root_job_id, {
            "job_id": self.job.id, "root_job_id": self.job.root_job_id,
            "parent_job_id": self.job.parent_job_id, "event": "started",
            "source": self.job.source, "limit": self.job.limit, "fetched": self.fetched,
        })
        try:
            stop = await self.run_pages()
        except Exception as error:
            stop = Stop(JobStatus.FAILED, error=f"{type(error).__name__}: {error}")
        await self.finish(stop)
        return stop

    async def finish(self, stop: Stop) -> None:
        for batch in self.batcher.add([], final=True):
            await save_batch(self.job.id, batch.batch_no, batch.review_ids)
            self.batched += len(batch.review_ids)
        await save_progress(self.job.id, self.fetched, self.batched, self.pages, self.token)
        await finish_job(self.job.id, stop.status, blocker=stop.blocker, error=stop.error)
        await expire_batches(self.job.id)
        await expire_raw_pages(self.job.id)

        if stop.status == JobStatus.BLOCKED:
            await events.emit(Topic.FETCH_FAILURES, self.job.id, {
                "job_id": self.job.id, "page_no": stop.blocker.page_no, "token": self.token,
                "source": self.job.source, "filters": self.job.filters,
                "reason": stop.blocker.reason, "attempts": stop.blocker.attempts,
            })
        if stop.status == JobStatus.FAILED:
            await events.emit(Topic.PARSE_ERRORS, self.job.id, {
                "job_id": self.job.id, "page_no": self.pages + 1, "error": stop.error,
            })
        await events.emit(Topic.JOB_EVENTS, self.job.root_job_id, {
            "job_id": self.job.id, "root_job_id": self.job.root_job_id,
            "event": stop.status, "fetched": self.fetched, "batches": self.batcher.next_batch_no - 1,
            "continuation_token": self.token,
        })