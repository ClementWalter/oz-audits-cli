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
"""Commands accept the audit URL a user copies from the browser, not only a site path."""

import sys
from pathlib import Path

import click
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402


@pytest.mark.parametrize("given", [
    "https://audits.openzeppelin.com/your-org/your-org-1/issues",
    "/your-org/your-org-1/issues",
    "your-org/your-org-1/issues",
])
def test_site_path_normalizes(given):
    assert cli._site_path(given) == "/your-org/your-org-1/issues"


def test_foreign_url_is_rejected():
    with pytest.raises(click.BadParameter, match="not on https://audits.openzeppelin.com"):
        cli._site_path("https://example.com/your-org")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
