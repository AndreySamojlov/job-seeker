import pytest


def test_budget_is_shared_across_source_build_and_json():
    from job_machine.board.read_budget import ReadBudget, ReadDeadline
    now = [0]
    budget = ReadBudget(now_ms=lambda: now[0])
    now[0] = 14_001
    assert budget.source_remaining_ms() == 999
    assert budget.statement_timeout_ms() == 999
    assert budget.timeout_seconds(3) == .999
    now[0] = 15_000
    with pytest.raises(ReadDeadline):
        budget.source_remaining_ms()
    budget.check_response_deadline()
    now[0] = 20_000
    with pytest.raises(ReadDeadline):
        budget.check_response_deadline()
