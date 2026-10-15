from job_machine.triage.vault import parse_vault

SAMPLE = """# Career Evidence Vault

## Claims

| ID | Claim | Status | Proof / provenance | Safe use |
|---|---|---|---|---|
| C-001 | 13+ years in technology | verified | resume-evidence-profile | Resume, outreach |
| C-014 | Python fundamentals; no commercial programming | verified | direct user statement | Never claim hands-on commercial coding |

## STAR Story Index

| Story ID | x | y | z |
|---|---|---|---|
| S-001 | a | b | c |
"""


def test_parse_vault_extracts_only_claim_rows():
    claims = parse_vault(SAMPLE)
    assert [c.claim_id for c in claims] == ["C-001", "C-014"]
    assert claims[0].claim_text == "13+ years in technology"
    assert claims[0].status == "verified"
    assert claims[1].safe_use == "Never claim hands-on commercial coding"


def test_parse_vault_skips_header_and_separator():
    claims = parse_vault(SAMPLE)
    assert all(c.claim_id.startswith("C-") for c in claims)
    assert len(claims) == 2
