#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest==9.1.1",
#     "browser-cookie3==0.20.1",
#     "click==8.5.0",
#     "playwright==1.64.1",
#     "rich==15.0.0",
# ]
#
# [tool.uv]
# exclude-newer = "2026-10-27T00:00:00Z"
# ///
"""Chrome launch and login failures must preserve working credentials."""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from http.cookiejar import CookieJar, Cookie

import click
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402


def test_launch_uses_installed_chrome():
    launch = Mock()
    cli._launch_browser(SimpleNamespace(chromium=SimpleNamespace(launch=launch)))
    assert launch.call_args.kwargs == {"channel": "chrome", "headless": True}


def test_missing_chrome_has_actionable_error():
    launch = Mock(side_effect=cli.PlaywrightError("Executable doesn't exist"))
    with pytest.raises(click.ClickException, match="Install Chrome"):
        cli._launch_browser(SimpleNamespace(chromium=SimpleNamespace(launch=launch)))


@pytest.fixture
def login_dependencies(monkeypatch):
    monkeypatch.setattr(cli, "load_config", lambda: {})
    save = Mock()
    monkeypatch.setattr(cli, "save_config", save)
    return save


def test_failed_login_does_not_save(monkeypatch, login_dependencies):
    monkeypatch.setattr(cli, "fetch_page", Mock(side_effect=click.ClickException("Expired cookie")))
    CliRunner().invoke(cli.cli, ["login", "--cookie-stdin", "--org", "example"], input="session=invalid")
    assert not login_dependencies.called


def test_failed_login_exits_nonzero(monkeypatch, login_dependencies):
    monkeypatch.setattr(cli, "fetch_page", Mock(side_effect=click.ClickException("Expired cookie")))
    result = CliRunner().invoke(cli.cli, ["login", "--cookie-stdin", "--org", "example"], input="session=invalid")
    assert result.exit_code == 1


def test_validated_login_saves(monkeypatch, login_dependencies):
    monkeypatch.setattr(cli, "fetch_page", Mock(return_value={"text": "Audits"}))
    CliRunner().invoke(cli.cli, ["login", "--cookie-stdin", "--org", "example"], input="session=valid\n")
    assert login_dependencies.call_args.args == ({"cookie": "session=valid", "org": "example"},)


def test_empty_stdin_exits_without_prompting(login_dependencies):
    result = CliRunner().invoke(cli.cli, ["login", "--cookie-stdin", "--org", "example"], input="")
    assert "Cookie header is empty" in result.output


def test_stdin_requires_organization(login_dependencies):
    result = CliRunner().invoke(cli.cli, ["login", "--cookie-stdin"], input="session=valid")
    assert "Provide --org" in result.output


def test_chrome_import_filters_unrelated_domains(monkeypatch):
    import browser_cookie3
    jar = CookieJar()
    jar.set_cookie(Cookie(0, "session", "oz", None, False, "audits.openzeppelin.com", True, False, "/", True, True, None, False, None, None, {}))
    jar.set_cookie(Cookie(0, "session", "other", None, False, "fakeaudits.openzeppelin.com", True, False, "/", True, True, None, False, None, None, {}))
    monkeypatch.setattr(browser_cookie3, "chrome", lambda **kwargs: jar)
    assert cli._chrome_cookie_header() == "session=oz"


def test_chrome_import_failure_is_actionable(monkeypatch):
    import browser_cookie3
    monkeypatch.setattr(browser_cookie3, "chrome", Mock(side_effect=RuntimeError("Keychain locked")))
    with pytest.raises(click.ClickException, match="Could not read Chrome cookies"):
        cli._chrome_cookie_header()


def test_browser_login_validates_imported_cookies(monkeypatch, login_dependencies):
    monkeypatch.setattr(cli, "_chrome_cookie_header", lambda path: "session=chrome")
    fetch = Mock()
    monkeypatch.setattr(cli, "fetch_page", fetch)
    CliRunner().invoke(cli.cli, ["login", "--browser", "chrome", "--org", "example"])
    assert fetch.call_args.args == ("session=chrome", "/example")


@pytest.mark.parametrize("arguments", [
    ["--browser", "chrome", "--cookie-stdin"],
    ["--cookie-file", __file__],
])
def test_conflicting_login_sources_fail(arguments, login_dependencies):
    assert CliRunner().invoke(cli.cli, ["login", *arguments]).exit_code == 2


def test_sign_in_redirect_is_an_error():
    with pytest.raises(click.ClickException, match="Session expired"):
        cli._check_page(SimpleNamespace(url=cli.BASE_URL + "/sign-in"))


@pytest.fixture
def error_screen_page():
    """The SPA error screen shown both for stale sessions and for genuine failures."""
    page = Mock(url=cli.BASE_URL + "/example/audit")
    page.get_by_role.return_value.count.return_value = 1
    return page


def test_rejected_api_call_reports_expired_session(error_screen_page):
    with pytest.raises(click.ClickException, match="Session expired"):
        cli._check_page(error_screen_page, [cli.BASE_URL + "/api/trpc/users.me"])


def test_expired_session_message_names_login_refresh(error_screen_page):
    with pytest.raises(click.ClickException, match="oz-audits login --browser chrome"):
        cli._check_page(error_screen_page, [cli.BASE_URL + "/api/trpc/users.me"])


def test_error_screen_without_auth_failure_keeps_page_error(error_screen_page):
    with pytest.raises(click.ClickException, match="This page couldn’t load"):
        cli._check_page(error_screen_page, [])


@pytest.mark.parametrize("status", [401, 403])
def test_api_rejection_is_auth_failure(status):
    response = SimpleNamespace(status=status, url=cli.BASE_URL + "/api/trpc/users.me?batch=1")
    assert cli._is_auth_failure(response)


def test_api_server_error_is_not_auth_failure():
    response = SimpleNamespace(status=500, url=cli.BASE_URL + "/api/trpc/users.me?batch=1")
    assert not cli._is_auth_failure(response)


def test_non_api_forbidden_is_not_auth_failure():
    response = SimpleNamespace(status=403, url="https://cdn.example.com/asset.js")
    assert not cli._is_auth_failure(response)


def test_watcher_records_rejected_api_call():
    page = Mock()
    failures = cli._watch_auth_failures(page)
    record = page.on.call_args.args[1]
    record(SimpleNamespace(status=401, url=cli.BASE_URL + "/api/trpc/users.me"))
    assert failures == [cli.BASE_URL + "/api/trpc/users.me"]


def test_watcher_ignores_successful_api_call():
    page = Mock()
    failures = cli._watch_auth_failures(page)
    record = page.on.call_args.args[1]
    record(SimpleNamespace(status=200, url=cli.BASE_URL + "/api/auth/get-session"))
    assert failures == []


def test_application_error_is_not_a_success():
    page = Mock(url=cli.BASE_URL + "/example")
    page.get_by_role.return_value.count.return_value = 0
    page.get_by_text.return_value.count.return_value = 1
    with pytest.raises(click.ClickException, match="This page couldn’t load"):
        cli._check_page(page)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
