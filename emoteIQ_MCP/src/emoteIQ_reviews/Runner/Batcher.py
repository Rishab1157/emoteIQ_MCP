from typing import NamedTuple, Optional


class Batch(NamedTuple):
    batch_no: int
    review_ids: list[str]


class Batcher:
    def __init__(self, batch_size: int, next_batch_no: int = 1, pending: Optional[list[str]] = None) -> None:
        self.batch_size = batch_size
        self.next_batch_no = next_batch_no
        self.pending = list(pending or [])

    def add(self, review_ids: list[str], final: bool = False) -> list[Batch]:
        self.pending.extend(review_ids)
        batches = []
        while len(self.pending) >= self.batch_size:
            batches.append(self._cut(self.batch_size))
        if final and self.pending:
            batches.append(self._cut(len(self.pending)))
        return batches

    def _cut(self, size: int) -> Batch:
        ids, self.pending = self.pending[:size], self.pending[size:]
        batch = Batch(batch_no=self.next_batch_no, review_ids=ids)
        self.next_batch_no += 1
        return batch
