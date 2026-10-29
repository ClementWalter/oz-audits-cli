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
"""A link table keeps every href whole on a narrow terminal, so it can be passed to `read`."""

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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
