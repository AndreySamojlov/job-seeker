"""HTTP-клиент MCP к job-package воркеру.

MCP-сервер локально не имеет /data: local run_package_build пишет артефакты на
локальный FS процесса (на Windows — с backslash-путями), нечитаемые job-fill
на lab-do (у него /data → PACKAGE_BASE_DIR=/data/applications). Делегируем
вызов /package/build воркеру — тот пишет на разделяемый /data.

Порт job-package пробросить туннелем (например, 8093:<container-ip>:8080 —
контейнер не публикует порт на host, см. app.py PORT=8080).
"""
import httpx


class PackageWorkerClient:
    def __init__(self, base_url: str, http: httpx.Client | None = None,
                 timeout: float = 120.0):
        self._http = http or httpx.Client(base_url=base_url, timeout=timeout)

    def run_package_build(self, limit: int = 10,
                          candidate_id: str | None = None) -> int:
        """POST /package/build — собрать пакеты на воркере (у него /data).

        candidate_id прокидывается в тело: воркер скоупит package-очередь этим
        кандидатом."""
        resp = self._http.post(
            "/package/build", json={"limit": limit, "candidate_id": candidate_id})
        resp.raise_for_status()
        return resp.json()["built"]

    def close(self) -> None:
        self._http.close()
