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
    with pytest.raises(click.ClickException, match="Authentication failed"):
        cli._check_page(SimpleNamespace(url=cli.BASE_URL + "/sign-in"))


def test_application_error_is_not_a_success():
    page = Mock(url=cli.BASE_URL + "/example")
    page.get_by_role.return_value.count.return_value = 0
    page.get_by_text.return_value.count.return_value = 1
    with pytest.raises(click.ClickException, match="This page couldn’t load"):
        cli._check_page(page)
