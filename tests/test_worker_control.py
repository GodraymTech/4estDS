from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from forestds.worker import control


def test_ensure_local_worker_starts_one_worker_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)

    monkeypatch.setattr(control, "_local_worker_roots", lambda: [])
    monkeypatch.setattr(control.paths, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(control.subprocess, "Popen", popen)
    monkeypatch.setattr(control.time, "sleep", lambda _: None)

    assert control.ensure_local_worker() is True

    command = popen.call_args.args[0]
    assert command[:4] == [control.sys.executable, "-m", "dramatiq", "forestds.worker.actors"]
    assert popen.call_args.kwargs["cwd"] == control._PROJECT_ROOT
    assert popen.call_args.kwargs["start_new_session"] is True


def test_ensure_local_worker_reuses_existing_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    popen = Mock()
    monkeypatch.setattr(control, "_local_worker_roots", lambda: [12345])
    monkeypatch.setattr(control.subprocess, "Popen", popen)

    assert control.ensure_local_worker() is False
    popen.assert_not_called()


def test_ensure_local_worker_reports_immediate_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = Mock()
    process.poll.return_value = 1

    monkeypatch.setattr(control, "_local_worker_roots", lambda: [])
    monkeypatch.setattr(control.paths, "logs_dir", lambda: tmp_path)
    monkeypatch.setattr(control.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(control.time, "sleep", lambda _: None)

    with pytest.raises(RuntimeError, match="启动失败"):
        control.ensure_local_worker()
