"""Per-source snapshots; failed reads never renew TTL."""
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import threading
import time
from typing import Callable
from job_machine.ops.client import redact

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BlockResult:
    state: str
    data: object | None
    fetched_at: datetime | None
    error: str | None
    expires_at: float | None = None


class SnapshotStore:
    def __init__(self, *, monotonic=None, wall_clock=None):
        self.monotonic = monotonic or time.monotonic
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.Lock()
        self.generation = 0
        self.snapshots = {}

    def read(self, name: str, loader: Callable[[], object]) -> BlockResult:
        with self.lock:
            self.generation += 1
            generation = self.generation
        try:
            data = loader()
        except (RuntimeError, ValueError, TypeError, KeyError, OverflowError) as exc:
            error = redact(str(exc))
            logger.warning('Dashboard runtime read failed at %s: %s', name, error)
            with self.lock:
                cached = self.snapshots.get(name)
                if cached is not None and self.monotonic() - cached[1] <= 300:
                    return BlockResult('stale', cached[3], cached[2], error, cached[1] + 300)
            return BlockResult('unavailable', None, None, error)
        with self.lock:
            cached = self.snapshots.get(name)
            if cached is None or generation > cached[0]:
                cached = (generation, self.monotonic(), self.wall_clock(), data)
                self.snapshots[name] = cached
            return BlockResult('live', cached[3], cached[2], None, cached[1] + 300)

    def expire(self, blocks: dict[str, BlockResult]) -> dict[str, BlockResult]:
        """Other loaders may have consumed a snapshot's remaining lifetime."""
        now = self.monotonic()
        return {name: (BlockResult('unavailable', None, None, block.error)
                       if block.expires_at is not None and now > block.expires_at else block)
                for name, block in blocks.items()}


def page_outcome(blocks: dict[str, BlockResult]) -> tuple[int, str]:
    subject = [blocks[name].state for name in ('summary','blockers','ready','observations')]
    if not any(state in {'live','stale'} for state in subject):
        return 503, 'unavailable'
    if 'live' not in subject:
        return 200, 'stale'
    if any(blocks[name].state != 'live' for name in ('summary','blockers','ready','observations','status')):
        return 200, 'partial'
    return 200, 'live'
