import asyncio
from threading import Event

import pytest


def test_cancel_retains_slot_until_worker_finishes():
    from job_machine.board.read_runtime import ReadCoordinator, PreparedReport, ReadBusy
    async def run():
        gate, entered = Event(), Event()
        coordinator = ReadCoordinator(max_inflight=2)
        def work(budget):
            entered.set()
            gate.wait(5)
            return PreparedReport(b'{}')
        first = asyncio.create_task(coordinator.run(work))
        await asyncio.to_thread(entered.wait, 2)
        second = asyncio.create_task(coordinator.run(work))
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        try:
            with pytest.raises(ReadBusy):
                await coordinator.run(work)
        finally:
            gate.set()
            await second
            await coordinator.aclose()
        with pytest.raises(RuntimeError):
            await coordinator.run(work)
    asyncio.run(run())


def test_deadline_retains_slot_and_exception_releases_it():
    from job_machine.board.read_runtime import ReadCoordinator, PreparedReport, ReadBusy
    from job_machine.board.read_budget import ReadDeadline
    async def run():
        gate = Event()
        coordinator = ReadCoordinator(max_inflight=1, timeout_ms=10)
        try:
            with pytest.raises(ReadDeadline):
                await coordinator.run(lambda b: (gate.wait(2), PreparedReport(b'{}'))[1])
            with pytest.raises(ReadBusy):
                await coordinator.run(lambda b: PreparedReport(b'{}'))
        finally:
            gate.set()
            await coordinator.aclose()
        coordinator = ReadCoordinator()
        def broken(b): raise ValueError('synthetic')
        with pytest.raises(ValueError):
            await coordinator.run(broken)
        assert (await coordinator.run(lambda b: PreparedReport(b'{}'))).body == b'{}'
        await coordinator.aclose()
    asyncio.run(run())
