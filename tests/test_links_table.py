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
"""Link tables list every site link, issue rows included, and keep each href whole so it can be passed to `read`."""

import sys
from pathlib import Path

import pytest
from rich.console import Console

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402

HREF = "/your-org/your-org-28-batcher-v3-async-redemption"


def test_href_is_not_truncated_at_80_columns():
    links = [{"text": "Your Org - #28 (Batcher v3 - Async Redemption)", "href": HREF}]
    console = Console(width=80, record=True)
    console.print(cli._links_table("Audit Links", "Title", "Path", links))
    assert HREF in console.export_text()


ISSUE = "/your-org/your-audit/issue/your-issue-1a2b3c4d"


def test_textless_issue_anchor_is_listed_under_its_href():
    assert cli._internal_links([{"text": "", "href": ISSUE}]) == [{"text": ISSUE, "href": ISSUE}]


def test_textless_anchor_defers_to_a_labelled_one():
    anchors = [{"text": "", "href": ISSUE}, {"text": "M-01 Your issue", "href": ISSUE}]
    assert cli._internal_links(anchors) == [{"text": "M-01 Your issue", "href": ISSUE}]


def test_repeated_textless_anchor_is_listed_once():
    assert cli._internal_links([{"text": "", "href": ISSUE}] * 3) == [{"text": ISSUE, "href": ISSUE}]


def test_same_href_with_distinct_labels_keeps_both():
    anchors = [{"text": "OpenZeppelin Your Org", "href": "/your-org"}, {"text": "Audits", "href": "/your-org"}]
    assert len(cli._internal_links(anchors)) == 2


def test_absolute_site_url_is_shown_as_site_path():
    anchors = [{"text": "Issue", "href": f"https://audits.openzeppelin.com{ISSUE}"}]
    assert cli._internal_links(anchors) == [{"text": "Issue", "href": ISSUE}]


@pytest.mark.parametrize("href", [
    "https://example.com/your-org",
    "//cdn.example.com/asset.js",
    "mailto:security@example.com",
    "#introduction",
    "relative/path",
    "javascript:void(0)",
])
def test_off_site_or_relative_href_is_dropped(href):
    assert cli._internal_links([{"text": "x", "href": href}]) == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
