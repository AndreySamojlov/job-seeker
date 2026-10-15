import httpx
import pytest

from job_machine.http.retry import (
    RetryPolicy,
    request_with_retry,
)


class _FakeClient:
    """Отдаёт заранее заданную последовательность ответов/исключений."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _resp(status, headers=None):
    return httpx.Response(status, headers=headers or {},
                          request=httpx.Request("GET", "https://x/y"))


def _recorder():
    slept = []
    return slept, lambda s: slept.append(s)


def test_retries_503_then_succeeds():
    client = _FakeClient([_resp(503), _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 2
    assert len(slept) == 1


def test_exhausts_attempts_returns_last_response():
    client = _FakeClient([_resp(503), _resp(503), _resp(503)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 503
    assert client.calls == 3  # max_attempts
    assert len(slept) == 2    # max_attempts - 1


def test_retries_transport_error_then_succeeds():
    err = httpx.ConnectError("boom", request=httpx.Request("GET", "https://x/y"))
    client = _FakeClient([err, _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 2
    assert len(slept) == 1


def test_reraises_transport_error_after_exhaustion():
    err = httpx.ConnectError("boom", request=httpx.Request("GET", "https://x/y"))
    client = _FakeClient([err, err, err])
    slept, sleep = _recorder()
    with pytest.raises(httpx.ConnectError):
        request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert client.calls == 3


def test_does_not_retry_404():
    client = _FakeClient([_resp(404)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 404
    assert client.calls == 1
    assert slept == []


def test_does_not_retry_200():
    client = _FakeClient([_resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 1
    assert slept == []


def test_honors_retry_after_header():
    client = _FakeClient([_resp(429, headers={"Retry-After": "2"}), _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert slept == [2.0]


def test_caps_delay_at_max_delay():
    # base*2^n быстро превысит max_delay → спим ровно max_delay
    policy = RetryPolicy(max_attempts=4, base_delay=10.0, max_delay=3.0)
    client = _FakeClient([_resp(503), _resp(503), _resp(503), _resp(200)])
    slept, sleep = _recorder()
    request_with_retry(client, "GET", "https://x/y", policy=policy, sleep=sleep)
    assert all(s <= 3.0 for s in slept)
    assert slept == [3.0, 3.0, 3.0]


def test_negative_retry_after_is_clamped_to_zero():
    # Кривой/clock-skew Retry-After: -5 не должен уйти в time.sleep(-5) (ValueError)
    client = _FakeClient([_resp(429, headers={"Retry-After": "-5"}), _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert slept == [0.0]


def test_retry_after_honored_above_max_delay_up_to_ceiling():
    # Сервер просит 60с — уважаем целиком (не капаем до max_delay=8), но <= retry_after_max
    policy = RetryPolicy(max_delay=8.0, retry_after_max=120.0)
    client = _FakeClient([_resp(503, headers={"Retry-After": "60"}), _resp(200)])
    slept, sleep = _recorder()
    request_with_retry(client, "GET", "https://x/y", policy=policy, sleep=sleep)
    assert slept == [60.0]


def test_retry_after_capped_at_ceiling():
    # Огромный Retry-After не должен подвесить воркер — кап на retry_after_max
    policy = RetryPolicy(retry_after_max=120.0)
    client = _FakeClient([_resp(503, headers={"Retry-After": "9999"}), _resp(200)])
    slept, sleep = _recorder()
    request_with_retry(client, "GET", "https://x/y", policy=policy, sleep=sleep)
    assert slept == [120.0]


def test_post_not_retried_on_read_timeout():
    # POST не идемпотентен: read-timeout мог сработать ПОСЛЕ доставки запроса →
    # повтор задвоит side-effect. Не ретраим, пробрасываем.
    err = httpx.ReadTimeout("slow", request=httpx.Request("POST", "https://x/y"))
    client = _FakeClient([err, _resp(200)])
    slept, sleep = _recorder()
    with pytest.raises(httpx.ReadTimeout):
        request_with_retry(client, "POST", "https://x/y", sleep=sleep)
    assert client.calls == 1
    assert slept == []


def test_post_retried_on_connect_error():
    # Connect-фаза: сервер запрос не получил → повтор POST безопасен
    err = httpx.ConnectError("down", request=httpx.Request("POST", "https://x/y"))
    client = _FakeClient([err, _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "POST", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 2


def test_get_retried_on_read_timeout():
    # GET идемпотентен → read-timeout ретраим
    err = httpx.ReadTimeout("slow", request=httpx.Request("GET", "https://x/y"))
    client = _FakeClient([err, _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "GET", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 2


def test_post_still_retried_on_503_status():
    # Статусный ретрай метод-агностичен: 503 = сервер явно не обработал запрос
    client = _FakeClient([_resp(503), _resp(200)])
    slept, sleep = _recorder()
    resp = request_with_retry(client, "POST", "https://x/y", sleep=sleep)
    assert resp.status_code == 200
    assert client.calls == 2


def test_max_attempts_zero_raises_value_error():
    client = _FakeClient([_resp(200)])
    _, sleep = _recorder()
    with pytest.raises(ValueError, match="max_attempts"):
        request_with_retry(client, "GET", "https://x/y",
                           policy=RetryPolicy(max_attempts=0), sleep=sleep)
