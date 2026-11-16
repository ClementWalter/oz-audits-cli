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
"""Commands accept the audit URL a user copies from the browser, not only a site path. No browser, no network."""

import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402

ISSUE_URL = "https://audits.openzeppelin.com/your-org/your-audit/issue/your-issue?tab=all#response"
ISSUE_PATH = "/your-org/your-audit/issue/your-issue"


@pytest.mark.parametrize("given", [
    "https://audits.openzeppelin.com/your-org/your-org-1/issues",
    "https://audits.openzeppelin.com/your-org/your-org-1/issues/",
    "https://audits.openzeppelin.com/your-org/your-org-1/issues?page=2",
    "https://audits.openzeppelin.com/your-org/your-org-1/issues#H-01",
    "http://audits.openzeppelin.com/your-org/your-org-1/issues",
    "audits.openzeppelin.com/your-org/your-org-1/issues",
    "  https://audits.openzeppelin.com/your-org/your-org-1/issues/?a=1#b  ",
    "/your-org/your-org-1/issues",
    "/your-org/your-org-1/issues/",
    "your-org/your-org-1/issues",
    "/your-org/your-org-1/issues?page=2#H-01",
])
def test_site_path_normalizes(given):
    assert cli._site_path(given) == "/your-org/your-org-1/issues"


@pytest.mark.parametrize("given", ["https://audits.openzeppelin.com", "https://audits.openzeppelin.com/", "/"])
def test_site_root_normalizes_to_slash(given):
    assert cli._site_path(given) == "/"


def test_site_path_is_idempotent():
    assert cli._site_path(cli._site_path(ISSUE_URL)) == ISSUE_PATH


@pytest.mark.parametrize("given", [
    "https://example.com/your-org",
    "https://audits.openzeppelin.com.evil.example/your-org",
])
def test_foreign_url_is_rejected(given):
    with pytest.raises(click.BadParameter, match="not on https://audits.openzeppelin.com"):
        cli._site_path(given)


@pytest.fixture
def fetched(monkeypatch):
    """Paths the page commands hand to fetch_page, with a stub session and page."""
    paths: list[str] = []

    def fetch_page(cookie, path, wait_ms=8000):
        paths.append(path)
        return {"text": "", "html": "", "links": [], "url": ""}

    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr(cli, "with_session", lambda config, run: run("cookie"))
    monkeypatch.setattr(cli, "fetch_page", fetch_page)
    return paths


@pytest.mark.parametrize("args", [
    ["read", ISSUE_URL],
    ["html", ISSUE_URL],
    ["links", ISSUE_URL],
    ["search", ISSUE_URL, "x"],
])
def test_page_command_fetches_site_path_of_full_url(fetched, args):
    CliRunner().invoke(cli.cli, args)
    assert fetched == [ISSUE_PATH]


@pytest.fixture
def written(monkeypatch):
    """Paths the write commands hand to their browser step, with a stub session."""
    paths: list[str] = []
    monkeypatch.setattr(cli, "load_config", lambda: {})
    monkeypatch.setattr(cli, "with_session", lambda config, run: run("cookie"))
    monkeypatch.setattr(cli, "_submit", lambda cookie, path, *rest, **kw: paths.append(path))
    monkeypatch.setattr(cli, "_remove", lambda cookie, path, wait: paths.append(path))
    return paths


@pytest.mark.parametrize("args", [
    ["submit", ISSUE_URL, "-r", "Acknowledged, not resolved", "-m", "ok", "--dry-run"],
    ["edit", ISSUE_URL, "-r", "Acknowledged, not resolved", "-m", "ok", "--dry-run"],
    ["remove", ISSUE_URL, "--yes"],
])
def test_write_command_targets_site_path_of_full_url(written, args):
    CliRunner().invoke(cli.cli, args)
    assert written == [ISSUE_PATH]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
