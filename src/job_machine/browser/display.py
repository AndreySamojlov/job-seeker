"""Управление Xvfb + x11vnc + websockify для headful handoff-браузера.

Идемпотентный старт/стоп трёх подпроцессов — заменяет безусловный запуск из
entrypoint.sh. Вызывается лениво из SessionManager только на реальный /handoff.
"""
import os
import subprocess
import time


class DisplayManager:
    def __init__(self, display=None, vnc_port=5900, novnc_port=6080,
                 novnc_web="/usr/share/novnc"):
        """display — X11-дисплей (например ":99"); по умолчанию из DISPLAY env, иначе ":99".
        vnc_port — RFB-порт x11vnc. novnc_port — WebSocket-порт websockify.
        novnc_web — путь к статике noVNC."""
        self._display = display or os.environ.get("DISPLAY", ":99")
        self._vnc_port = vnc_port
        self._novnc_port = novnc_port
        self._novnc_web = novnc_web
        self._xvfb = None
        self._x11vnc = None
        self._websockify = None

    def is_running(self) -> bool:
        return self._xvfb is not None

    def start(self, timeout: float = 5.0) -> None:
        """Поднять Xvfb → дождаться готовности сокета → x11vnc → websockify.

        No-op, если уже запущено. Кидает RuntimeError (и подчищает за собой),
        если Xvfb-сокет не появился за `timeout` секунд.
        """
        if self.is_running():
            return
        self._xvfb = subprocess.Popen(
            ["Xvfb", self._display, "-screen", "0", "1280x1024x24"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._wait_for_socket(timeout)
        try:
            self._x11vnc = subprocess.Popen(
                ["x11vnc", "-display", self._display, "-forever", "-shared", "-nopw",
                 "-rfbport", str(self._vnc_port)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self._websockify = subprocess.Popen(
                ["websockify", f"--web={self._novnc_web}", str(self._novnc_port),
                 f"localhost:{self._vnc_port}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception:
            self.stop()
            raise

    def _wait_for_socket(self, timeout: float) -> None:
        display_num = self._display.lstrip(":")
        sock_path = f"/tmp/.X11-unix/X{display_num}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.exists(sock_path):
                return
            time.sleep(0.1)
        self.stop()
        raise RuntimeError(f"Xvfb socket {sock_path} not ready after {timeout}s")

    def stop(self) -> None:
        """Погасить все три процесса (SIGTERM → SIGKILL по таймауту). No-op если не запущено."""
        procs = [p for p in (self._websockify, self._x11vnc, self._xvfb) if p is not None]
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        self._xvfb = None
        self._x11vnc = None
        self._websockify = None
