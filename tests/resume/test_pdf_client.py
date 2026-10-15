import httpx

from job_machine.resume.pdf_client import PdfClient


def test_render_posts_html_and_returns_bytes():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["json"] = httpx.Request("POST", request.url, content=request.content).content
        import json
        seen["html"] = json.loads(request.content)["html"]
        return httpx.Response(200, content=b"%PDF-1.4 data",
                              headers={"content-type": "application/pdf"})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://job-browser:8080", transport=transport)
    client = PdfClient(base_url="http://job-browser:8080", http=http)
    pdf = client.render("<html><h1>CV</h1></html>")
    assert pdf.startswith(b"%PDF")
    assert seen["url"].endswith("/pdf")
    assert "<h1>CV</h1>" in seen["html"]
