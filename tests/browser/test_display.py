"""Тесты DisplayManager (Xvfb/x11vnc/websockify) — без реального Xvfb (subprocess.Popen замокан)."""
from unittest.mock import MagicMock, patch

import pytest

from job_machine.browser.display import DisplayManager


def _fake_popen(*args, **kwargs):
    return MagicMock(pid=1234)


@patch("job_machine.browser.display.os.path.exists", return_value=True)
@patch("job_machine.browser.display.subprocess.Popen", side_effect=_fake_popen)
def test_start_launches_xvfb_x11vnc_websockify(mock_popen, mock_exists):
    mgr = DisplayManager()
    mgr.start()
    assert mock_popen.call_count == 3
    assert mgr.is_running() is True


@patch("job_machine.browser.display.os.path.exists", return_value=True)
@patch("job_machine.browser.display.subprocess.Popen", side_effect=_fake_popen)
def test_start_is_idempotent(mock_popen, mock_exists):
    mgr = DisplayManager()
    mgr.start()
    mgr.start()
    assert mock_popen.call_count == 3  # второй start() — no-op, ничего не лончит заново


@patch("job_machine.browser.display.os.path.exists", return_value=True)
@patch("job_machine.browser.display.subprocess.Popen", side_effect=_fake_popen)
def test_stop_terminates_all_three_processes(mock_popen, mock_exists):
    mgr = DisplayManager()
    mgr.start()
    procs = [mgr._websockify, mgr._x11vnc, mgr._xvfb]
    mgr.stop()
    for proc in procs:
        proc.terminate.assert_called_once()
    assert mgr.is_running() is False


@patch("job_machine.browser.display.subprocess.Popen", side_effect=_fake_popen)
def test_stop_before_start_is_noop(mock_popen):
    mgr = DisplayManager()
    mgr.stop()  # не должно падать
    assert mock_popen.call_count == 0


@patch("job_machine.browser.display.os.path.exists", return_value=False)
@patch("job_machine.browser.display.subprocess.Popen", side_effect=_fake_popen)
def test_start_raises_and_cleans_up_if_socket_never_appears(mock_popen, mock_exists):
    mgr = DisplayManager()
    with pytest.raises(RuntimeError, match="socket"):
        mgr.start(timeout=0.2)
    assert mgr.is_running() is False


@patch("job_machine.browser.display.os.path.exists", return_value=True)
@patch("job_machine.browser.display.subprocess.Popen")
def test_start_cleans_up_xvfb_if_x11vnc_fails_to_launch(mock_popen, mock_exists):
    xvfb_proc = MagicMock(pid=1234)
    mock_popen.side_effect = [xvfb_proc, OSError("x11vnc not found")]
    mgr = DisplayManager()
    with pytest.raises(OSError, match="x11vnc not found"):
        mgr.start()
    xvfb_proc.terminate.assert_called_once()
    assert mgr.is_running() is False
