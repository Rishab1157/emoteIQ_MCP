import asyncio
import logging

from ..Storage.Jobs import running_job_ids
from .JobRunner import JobRunner

log = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, job_id: str) -> None:
        if job_id in self._tasks:
            return
        task = asyncio.create_task(self._run(job_id), name=f"job:{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job_id, None))

    def is_running(self, job_id: str) -> bool:
        return job_id in self._tasks

    async def resume_running(self) -> list[str]:
        job_ids = await running_job_ids()
        for job_id in job_ids:
            self.start(job_id)
        return job_ids

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)

    async def _run(self, job_id: str) -> None:
        try:
            runner = await JobRunner.load(job_id)
            await runner.run()
        except Exception:
            log.exception("Job %s crashed before it could finish", job_id)


tasks = TaskManager()
