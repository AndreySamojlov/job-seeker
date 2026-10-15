"""Admission before executor submission; cancellation never creates capacity."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import BoundedSemaphore

from job_machine.board.read_budget import ReadBudget, ReadDeadline


class ReadBusy(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedReport:
    body: bytes


class ReadCoordinator:
    def __init__(self, max_inflight=2, timeout_ms=20000):
        self._slots = BoundedSemaphore(max_inflight)
        self._executor = ThreadPoolExecutor(max_workers=max_inflight, thread_name_prefix='board-read')
        self._closed = False
        self.timeout_ms = timeout_ms

    async def run(self, work, *, budget=None):
        if self._closed:
            raise RuntimeError('Read coordinator closed')
        budget = budget or ReadBudget(response_timeout_ms=self.timeout_ms)
        if not self._slots.acquire(blocking=False):
            raise ReadBusy('Read capacity exhausted')
        try:
            future = self._executor.submit(work, budget)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        wrapped = asyncio.wrap_future(future)
        # Consume errors even when the HTTP waiter has already gone away.
        wrapped.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
        try:
            result = await asyncio.wait_for(asyncio.shield(wrapped), budget.response_remaining_ms() / 1000)
        except TimeoutError:
            raise ReadDeadline('Response deadline exceeded') from None
        budget.check_response_deadline()
        return result

    async def aclose(self):
        self._closed = True
        await asyncio.to_thread(self._executor.shutdown, wait=True, cancel_futures=True)
