from job_machine.package.answer_vault import parse_answer_vault

VAULT = """# Application Answer Vault

| Field | Value | State | Rule |
|---|---|---|---|
| Full name | Andrey Samoylov | locked | Use Latin spelling |
| English | B2 / upper-intermediate | locked | Never upgrade to C1 |
| Work authorization | Unknown for each destination | blocked | Never answer authorized |
| Salary expectation | Not locked | blocked | Ask when mandatory |
| Marketing/talent-pool consent | No by default | optional-policy | Separate from processing |
| Junk row | x | bogus | ignored |
"""


def test_parses_known_states_only():
    rows = parse_answer_vault(VAULT)
    by_field = {r.field: r for r in rows}
    assert by_field["English"].state == "locked"
    assert by_field["English"].value == "B2 / upper-intermediate"
    assert by_field["Work authorization"].state == "blocked"
    assert by_field["Marketing/talent-pool consent"].state == "optional-policy"
    assert "Junk row" not in by_field  # неизвестный state отброшен


def test_handles_empty_and_none():
    assert parse_answer_vault("") == []
    assert parse_answer_vault("no table here") == []
