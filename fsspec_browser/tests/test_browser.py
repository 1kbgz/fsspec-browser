"""Tests for the Python browser launcher."""


def test_run_passes_explicit_args(monkeypatch):
    from fsspec_browser import browser

    calls = []
    monkeypatch.setattr(browser, "_run_browser", lambda argv: calls.append(argv))

    assert browser.run(["--help"]) == 0
    assert calls == [["--help"]]


def test_run_uses_sys_argv(monkeypatch):
    from fsspec_browser import browser

    calls = []
    monkeypatch.setattr(browser.sys, "argv", ["fsspec-browser", "/tmp"])
    monkeypatch.setattr(browser, "_run_browser", lambda argv: calls.append(argv))

    assert browser.run() == 0
    assert calls == [["/tmp"]]


def test_main_reports_errors(monkeypatch, capsys):
    from fsspec_browser import browser

    def fail(_argv):
        raise RuntimeError("boom")

    monkeypatch.setattr(browser, "_run_browser", fail)

    assert browser.main([]) == 1
    assert "boom" in capsys.readouterr().err
