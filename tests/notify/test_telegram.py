import json

import httpx

from job_machine.notify.telegram import TelegramSender


def test_send_message_posts_and_returns_message_id():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = TelegramSender("TESTTOKEN", http=client)
    mid = sender.send_message("272425172", "<b>hi</b>")
    assert mid == 42
    assert seen["path"] == "/botTESTTOKEN/sendMessage"
    assert seen["body"]["chat_id"] == "272425172"
    assert seen["body"]["text"] == "<b>hi</b>"
    assert seen["body"]["parse_mode"] == "HTML"


def test_send_message_raises_on_http_error():
    def handler(request):
        return httpx.Response(500, json={"ok": False})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sender = TelegramSender("T", http=client)
    try:
        sender.send_message("1", "x")
        assert False, "ожидали исключение"
    except httpx.HTTPError:
        pass
