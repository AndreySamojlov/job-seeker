"""One monotonic budget for admission, source work and response serialization."""
from time import monotonic


def monotonic_ms():
    return monotonic() * 1000


class ReadDeadline(TimeoutError):
    pass


class ReadBudget:
    def __init__(self, *, now_ms=monotonic_ms, started_ms=None,
                 source_timeout_ms=15000, response_timeout_ms=20000):
        self.now_ms = now_ms
        self.started_ms = now_ms() if started_ms is None else started_ms
        self.source_deadline = self.started_ms + source_timeout_ms
        self.response_deadline = self.started_ms + response_timeout_ms

    def source_remaining_ms(self):
        remaining = int(self.source_deadline - self.now_ms())
        if remaining <= 0:
            raise ReadDeadline('Source deadline exceeded')
        return remaining

    def response_remaining_ms(self):
        remaining = int(self.response_deadline - self.now_ms())
        if remaining <= 0:
            raise ReadDeadline('Response deadline exceeded')
        return remaining

    def check_response_deadline(self):
        self.response_remaining_ms()

    def statement_timeout_ms(self):
        return min(10000, self.source_remaining_ms())

    def timeout_seconds(self, cap):
        return min(cap, self.source_remaining_ms() / 1000)
