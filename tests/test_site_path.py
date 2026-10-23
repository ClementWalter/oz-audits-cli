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
