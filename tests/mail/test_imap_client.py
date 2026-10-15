from job_machine.mail.imap_client import fetch_new_messages, list_recent_headers


class FakeIMAP:
    def __init__(self, messages: dict[int, bytes]):
        self._messages = messages
        self.selected = None

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        return "OK", [b"1"]

    def uid(self, command, *args):
        if command == "search":
            uids = sorted(self._messages.keys())
            return "OK", [" ".join(str(u) for u in uids).encode()]
        if command == "fetch":
            uid = int(args[0])
            raw = self._messages.get(uid)
            if raw is None:
                return "NO", [None]
            return "OK", [(b"1 (RFC822 {n})", raw)]
        raise ValueError(command)


def _raw_email(subject: str, body: str) -> bytes:
    return (
        f"From: hr@acme.com\r\nSubject: {subject}\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}"
    ).encode("utf-8")


def test_fetch_new_messages_filters_by_last_uid():
    imap = FakeIMAP({5: _raw_email("Old", "old body"),
                     6: _raw_email("Update on your application",
                                   "Unfortunately we will not proceed.")})
    result = fetch_new_messages(imap, last_uid=5)
    assert len(result) == 1
    assert result[0].uid == 6
    assert "Unfortunately" in result[0].body
    assert result[0].subject == "Update on your application"


def test_fetch_new_messages_respects_limit():
    imap = FakeIMAP({i: _raw_email(f"Subj {i}", "body") for i in range(1, 6)})
    result = fetch_new_messages(imap, last_uid=0, limit=2)
    assert [r.uid for r in result] == [1, 2]


def test_list_recent_headers_returns_headers_without_touching_cursor():
    imap = FakeIMAP({i: _raw_email(f"Subj {i}", "body") for i in range(1, 4)})
    result = list_recent_headers(imap, limit=30)
    assert [r["uid"] for r in result] == [1, 2, 3]
    assert result[0]["subject"] == "Subj 1"
    assert result[0]["from_addr"] == "hr@acme.com"


def test_list_recent_headers_respects_limit_to_most_recent():
    imap = FakeIMAP({i: _raw_email(f"Subj {i}", "body") for i in range(1, 6)})
    result = list_recent_headers(imap, limit=2)
    assert [r["uid"] for r in result] == [4, 5]


def test_list_recent_headers_empty_mailbox():
    imap = FakeIMAP({})
    assert list_recent_headers(imap) == []
