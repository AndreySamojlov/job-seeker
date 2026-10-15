from job_machine.fill.gate import check_fill_gate, inspect_block_label


def test_gate_passes_when_summary_and_resume_match():
    r = check_fill_gate(
        summary_artifacts=[{"artifact_type": "approval_summary"}],
        resume_artifact={"content_hash": "abc"},
        disclosed_resume_hash="abc",
    )
    assert r is None


def test_gate_blocks_without_disclosed_summary():
    r = check_fill_gate(
        summary_artifacts=[{"artifact_type": "manifest"}],
        resume_artifact={"content_hash": "abc"},
        disclosed_resume_hash="abc",
    )
    assert r is not None
    assert r.guard_name == "NoFillBeforeDisclosedSummary"
    assert r.ok is False


def test_gate_blocks_on_resume_hash_mismatch():
    r = check_fill_gate(
        summary_artifacts=[{"artifact_type": "approval_summary"}],
        resume_artifact={"content_hash": "DIFFERENT"},
        disclosed_resume_hash="abc",
    )
    assert r is not None
    assert r.guard_name == "NoResumeUploadWithoutHashMatch"
    assert r.ok is False


def test_inspect_block_label_none_passes():
    assert inspect_block_label(None) is None


def test_inspect_block_label_known_is_stop():
    assert inspect_block_label("captcha") == "captcha"


def test_inspect_block_label_unknown_is_stop_failclosed():
    assert inspect_block_label("some_new_label") == "some_new_label"


def test_inspect_block_label_empty_string_is_stop():
    assert inspect_block_label("") == ""
