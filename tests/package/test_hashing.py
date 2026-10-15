from job_machine.package import hashing
from job_machine.package.models import DisclosedAnswer, DisclosedConsent


def _answers(pairs):
    return [DisclosedAnswer(field=f, value=v) for f, v in pairs]


def test_answers_hash_order_independent():
    a = _answers([("English", "B2"), ("Phone", "+7")])
    b = _answers([("Phone", "+7"), ("English", "B2")])
    assert hashing.answers_hash(a) == hashing.answers_hash(b)


def test_answers_hash_value_sensitive():
    a = _answers([("English", "B2")])
    b = _answers([("English", "C1")])
    assert hashing.answers_hash(a) != hashing.answers_hash(b)


def test_payload_hash_reproducible_and_field_sensitive():
    answers = _answers([("English", "B2")])
    consents = [DisclosedConsent(field="Talent pool", decision="No")]
    h1 = hashing.payload_hash("https://acme/apply", "resumehash", answers, consents)
    h2 = hashing.payload_hash("https://acme/apply", "resumehash", answers, consents)
    assert h1 == h2 and len(h1) == 64
    # любая компонента меняет хеш
    assert h1 != hashing.payload_hash("https://other/apply", "resumehash", answers, consents)
    assert h1 != hashing.payload_hash("https://acme/apply", "DIFF", answers, consents)
    assert h1 != hashing.payload_hash("https://acme/apply", "resumehash", answers, [])
