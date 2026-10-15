import pytest

from job_machine.db import migrate
from job_machine.mail import service, store
from job_machine.mail.models import EmailInput, ReplyClassification


def _apply(conn):
    for m in migrate.pending(migrate.discover_migrations("db/migrations"),
                             migrate.applied_migrations(conn)):
        migrate.apply_migration(conn, m)
    conn.commit()


def _seed_application(conn, candidate_id="andrey-s"):
    with conn.cursor() as cur:
        cur.execute(
            "insert into vacancy (vacancy_id, company, title, canonical_url) "
            "values (gen_random_uuid(), 'Acme', 'QA Lead', 'https://x') "
            "returning vacancy_id")
        vacancy_id = cur.fetchone()[0]
        cur.execute(
            "insert into application (application_id, vacancy_id, candidate_id, state) "
            "values (gen_random_uuid(), %s, %s, 'submitted') returning application_id",
            (vacancy_id, candidate_id))
        return str(cur.fetchone()[0])


class FakeIMAP:
    def __init__(self, emails):
        self._emails = emails

    def logout(self):
        pass


class FakeSender:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return 1


def _fetcher(emails):
    def fn(imap, last_uid, limit=25):
        return [e for e in emails if e.uid > last_uid]
    return fn


class FakeLLM:
    def __init__(self, verdicts: dict[int, ReplyClassification]):
        self._verdicts = verdicts

    def classify_reply(self, email, applications):
        return self._verdicts[email.uid]


@pytest.mark.db
def test_poll_applies_rejected_and_advances_cursor(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()

    email_1 = EmailInput(uid=1, from_addr="hr@acme.com", subject="Update",
                          body="Unfortunately, no.")
    llm = FakeLLM({1: ReplyClassification(application_id=aid, candidate_id="andrey-s",
                                          category="rejected", confidence=0.9)})
    sender = FakeSender()

    result = service.poll_and_classify(
        conn, imap=FakeIMAP([email_1]), llm=llm, sender=sender,
        mailbox="workcockpit@gmail.com", owner_chat_id="1",
        fetch_fn=_fetcher([email_1]))

    assert result["applied"] == 1
    assert result["needs_review"] == 0
    assert store.get_cursor(conn, "workcockpit@gmail.com") == 1
    with conn.cursor() as cur:
        cur.execute("select outcome_status from application where application_id=%s", (aid,))
        assert cur.fetchone()[0] == "rejected"


@pytest.mark.db
def test_poll_marks_needs_review_and_notifies_summary(db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()

    email_1 = EmailInput(uid=1, from_addr="hr@unknown.com", subject="Question",
                          body="Can you clarify your visa status?")
    llm = FakeLLM({1: ReplyClassification(application_id=None, candidate_id=None,
                                          category="other", confidence=0.3)})
    sender = FakeSender()

    result = service.poll_and_classify(
        conn, imap=FakeIMAP([email_1]), llm=llm, sender=sender,
        mailbox="workcockpit@gmail.com", owner_chat_id="1",
        fetch_fn=_fetcher([email_1]))

    assert result["applied"] == 0
    assert result["needs_review"] == 1
    assert len(sender.sent) == 1
    assert "Question" in sender.sent[0][1]


@pytest.mark.db
def test_poll_ignores_hallucinated_application_id_and_advances_cursor(db_schema):
    """LLM выдаёт application_id, которого нет среди активных заявок (галлюцинация).
    Без allow-list фильтра запись падает на FK inbound_email.application_id и
    курсор навсегда застревает на этом письме (poison-pill)."""
    conn, _ = db_schema
    _apply(conn)
    conn.commit()

    fake_aid = "11111111-1111-1111-1111-111111111111"
    email_1 = EmailInput(uid=1, from_addr="hr@acme.com", subject="Update",
                          body="Unfortunately, no.")
    llm = FakeLLM({1: ReplyClassification(application_id=fake_aid, candidate_id="andrey-s",
                                          category="rejected", confidence=0.95)})
    sender = FakeSender()

    result = service.poll_and_classify(
        conn, imap=FakeIMAP([email_1]), llm=llm, sender=sender,
        mailbox="workcockpit@gmail.com", owner_chat_id="1",
        fetch_fn=_fetcher([email_1]))

    assert result["applied"] == 0
    assert result["needs_review"] == 1
    assert store.get_cursor(conn, "workcockpit@gmail.com") == 1


@pytest.mark.db
def test_poll_one_bad_email_does_not_block_the_rest_of_the_batch(db_schema):
    conn, _ = db_schema
    _apply(conn)
    aid = _seed_application(conn)
    conn.commit()

    email_1 = EmailInput(uid=1, from_addr="hr@x.com", subject="Bad",
                          body="Update on your application to a ghost company.")
    email_2 = EmailInput(uid=2, from_addr="hr@acme.com", subject="Update",
                          body="Unfortunately, no.")
    llm = FakeLLM({
        1: ReplyClassification(application_id="22222222-2222-2222-2222-222222222222",
                               candidate_id="andrey-s", category="rejected",
                               confidence=0.95),
        2: ReplyClassification(application_id=aid, candidate_id="andrey-s",
                               category="rejected", confidence=0.9),
    })
    sender = FakeSender()

    result = service.poll_and_classify(
        conn, imap=FakeIMAP([email_1, email_2]), llm=llm, sender=sender,
        mailbox="workcockpit@gmail.com", owner_chat_id="1",
        fetch_fn=_fetcher([email_1, email_2]))

    assert result["applied"] == 1
    assert result["needs_review"] == 1
    assert store.get_cursor(conn, "workcockpit@gmail.com") == 2


@pytest.mark.db
def test_poll_is_idempotent_on_rerun(db_schema):
    conn, _ = db_schema
    _apply(conn)
    conn.commit()

    email_1 = EmailInput(uid=1, from_addr="hr@x.com", subject="S", body="B")
    llm = FakeLLM({1: ReplyClassification(application_id=None, candidate_id=None,
                                          category="other", confidence=0.1)})
    sender = FakeSender()
    fetch = _fetcher([email_1])

    first = service.poll_and_classify(conn, imap=FakeIMAP([email_1]), llm=llm,
                                      sender=sender, mailbox="workcockpit@gmail.com",
                                      owner_chat_id="1", fetch_fn=fetch)
    second = service.poll_and_classify(conn, imap=FakeIMAP([email_1]), llm=llm,
                                       sender=sender, mailbox="workcockpit@gmail.com",
                                       owner_chat_id="1", fetch_fn=fetch)
    assert first["needs_review"] == 1
    assert second["needs_review"] == 0
