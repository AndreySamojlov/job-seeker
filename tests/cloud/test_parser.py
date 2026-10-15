from job_machine.cloud.parser import parse_experience_cloud

SAMPLE = """# Experience Cloud

bla bla honesty header

## Positions

| pid | company | title | start | end | location | summary |
|---|---|---|---|---|---|---|
| P-01 | NSD | Head of QA | 2024-09 | present | Moscow | turnaround |
| P-02 | Innotech | QA Lead | 2021-03 | 2024-09 | Moscow | banking |

## Achievements

| aid | pid | text | metric | status | claims | safe_use |
|---|---|---|---|---|---|---|
| A-01 | P-01 | Rebuilt org | ~100 people | approximate | C-004 | about 100 |

## Skills

| name | category | framing | evidence | safe_use |
|---|---|---|---|---|
| Python | skill | Fundamentals only | C-014 | never commercial |
| English | language | B2 | C-015 | forms |
"""


def test_parses_positions():
    c = parse_experience_cloud(SAMPLE)
    assert len(c.positions) == 2
    assert c.positions[0].pid == "P-01"
    assert c.positions[0].company == "NSD"
    assert c.positions[1].end == "2024-09"


def test_parses_achievements_with_fk():
    c = parse_experience_cloud(SAMPLE)
    assert len(c.achievements) == 1
    a = c.achievements[0]
    assert a.aid == "A-01" and a.pid == "P-01"
    assert a.status == "approximate" and a.claims == "C-004"


def test_parses_skills_with_category():
    c = parse_experience_cloud(SAMPLE)
    assert len(c.skills) == 2
    assert c.skills[0].name == "Python" and c.skills[0].category == "skill"
    assert c.skills[1].category == "language"


def test_ignores_prose_between_tables():
    c = parse_experience_cloud(SAMPLE)
    assert all(p.pid.startswith("P-") for p in c.positions)


# Возвращённые в source факты C-006 / C-023 / C-024 (§4.5). Фрагмент повторяет формат
# строк из experience-cloud.md; verbatim из career-evidence-vault.md.
RECOVERED = """## Achievements

| aid | pid | text | metric | status | claims | safe_use |
|---|---|---|---|---|---|---|
| A-16 | P-02 | Led a distributed QA organization across manual testing, automation, and release management | 15 people | verified | C-006 | resume and interview |
| A-17 | P-02 | Led Agile/Scrum delivery, including sprint planning and ceremonies | — | verified | C-023 | delivery-methodology leadership |
| A-18 | P-02 | Managed delivery and SLAs for external, customer-facing clients (professional-services context) | — | verified | C-024 | customer-facing delivery / service management |
"""


def test_parses_recovered_claims():
    cloud = parse_experience_cloud(RECOVERED)
    claim_ids = " ".join(a.claims for a in cloud.achievements).lower()
    assert "c-006" in claim_ids and "c-023" in claim_ids and "c-024" in claim_ids
    by_claim = {a.claims: a for a in cloud.achievements}
    assert by_claim["C-006"].metric == "15 people"       # QA-орг 15
    assert by_claim["C-006"].pid == "P-02"
    assert "Agile/Scrum" in by_claim["C-023"].text
    assert "SLAs" in by_claim["C-024"].text
