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
"""Where the session and organization come from without a terminal login. No browser, no network."""

import sys
from pathlib import Path
from unittest.mock import Mock

import click
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402


@pytest.fixture
def saved(monkeypatch):
    """Configs passed to save_config, in order."""
    configs: list[dict] = []
    monkeypatch.setattr(cli, "save_config", configs.append)
    return configs


@pytest.fixture
def chrome(monkeypatch, tmp_path):
    """Make Chrome hold `header`, or no OZ session when it is None."""
    store = tmp_path / "Library/Application Support/Google/Chrome/Default/Cookies"
    store.parent.mkdir(parents=True)
    store.touch()
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)

    def install(header: str | None):
        def read(cookie_file=None):
            if header is None:
                raise click.ClickException("No OZ cookies found in Chrome.")
            return header

        monkeypatch.setattr(cli, "_chrome_cookie_header", read)

    return install


def expired_unless(good: str):
    """A page fetch that only `good` cookies pass."""

    def run(cookie: str) -> str:
        if cookie != good:
            raise click.ClickException(cli.SESSION_EXPIRED_MESSAGE)
        return f"page read with {cookie}"

    return run


def test_saved_session_is_used(saved, chrome):
    chrome("session=chrome")
    assert cli.with_session({"cookie": "session=saved"}, lambda cookie: cookie) == "session=saved"


def test_missing_session_is_read_from_chrome(saved, chrome):
    chrome("session=chrome")
    assert cli.with_session({}, lambda cookie: cookie) == "session=chrome"


def test_chrome_session_is_saved_after_it_works(saved, chrome):
    chrome("session=chrome")
    cli.with_session({"org": "example"}, lambda cookie: cookie)
    assert saved == [{"org": "example", "cookie": "session=chrome"}]


def test_chrome_session_that_fails_is_not_saved(saved, chrome):
    chrome("session=chrome")
    with pytest.raises(click.ClickException):
        cli.with_session({}, expired_unless("session=other"))
    assert saved == []


def test_no_session_anywhere_says_where_to_sign_in(saved, chrome):
    chrome(None)
    with pytest.raises(click.ClickException, match="Sign in at https://audits.openzeppelin.com in Google Chrome"):
        cli.with_session({}, lambda cookie: cookie)


def test_no_chrome_profile_skips_the_keychain(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    monkeypatch.setattr(cli.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(cli, "_chrome_cookie_header", Mock(side_effect=AssertionError("must not ask the keychain")))
    with pytest.raises(click.ClickException, match="Not signed in"):
        cli._chrome_session()


def test_expired_saved_session_is_retried_with_chrome(saved, chrome):
    chrome("session=fresh")
    assert cli.with_session({"cookie": "session=old"}, expired_unless("session=fresh")) == "page read with session=fresh"


def test_fresh_chrome_session_replaces_the_expired_one(saved, chrome):
    chrome("session=fresh")
    cli.with_session({"cookie": "session=old"}, expired_unless("session=fresh"))
    assert saved == [{"cookie": "session=fresh"}]


def test_expired_session_also_stale_in_chrome_is_reported(saved, chrome):
    chrome("session=old")
    with pytest.raises(click.ClickException, match="Session expired"):
        cli.with_session({"cookie": "session=old"}, expired_unless("session=fresh"))


def test_expired_session_without_chrome_is_reported(saved, chrome):
    chrome(None)
    with pytest.raises(click.ClickException, match="Session expired"):
        cli.with_session({"cookie": "session=old"}, expired_unless("session=fresh"))


def test_other_page_errors_are_not_retried(saved, chrome):
    chrome("session=fresh")
    run = Mock(side_effect=click.ClickException("This page couldn’t load"))
    with pytest.raises(click.ClickException):
        cli.with_session({"cookie": "session=old"}, run)
    assert run.call_count == 1


def test_org_setting_wins_over_the_saved_org(monkeypatch):
    monkeypatch.setenv(cli.ORG_SETTING, "from-setting")
    assert cli._require_org({"org": "saved"}) == "from-setting"


@pytest.mark.parametrize("value", ["", "${user_config.org}"])
def test_unfilled_org_setting_falls_back_to_the_saved_org(monkeypatch, value):
    monkeypatch.setenv(cli.ORG_SETTING, value)
    assert cli._require_org({"org": "/saved/"}) == "saved"


def test_missing_org_names_the_extension_setting(monkeypatch):
    monkeypatch.delenv(cli.ORG_SETTING, raising=False)
    with pytest.raises(click.ClickException, match="fill 'Organization' in the OpenZeppelin Audits extension's settings"):
        cli._require_org({})


def test_remove_without_yes_and_without_a_terminal_is_a_dry_run(monkeypatch):
    monkeypatch.setattr(cli, "with_session", Mock(side_effect=AssertionError("must not open the page")))
    result = CliRunner().invoke(cli.cli, ["remove", "/org/audit/issue/x"])
    assert "Dry run: would remove" in result.output


def test_save_is_silent_without_a_broker(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cli, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(cli, "auth_broker", lambda *a: {})
    monkeypatch.setattr(cli, "broker_helper", lambda: str(tmp_path / "absent"))
    cli.save_config({"secret": "credential"})
    assert "1Password" not in caplog.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
