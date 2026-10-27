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
"""Only the resolutions whose dialog has PR and commit fields require or accept them."""

import sys
from pathlib import Path

import click
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402

PR = "https://github.com/org/repo/pull/1"


@pytest.mark.parametrize("resolution", ["Resolved", "partially resolved"])
def test_code_resolution_without_reference_is_rejected(resolution):
    with pytest.raises(click.ClickException, match="requires --pr or --commit"):
        cli._check_code_references(resolution, None, ())


@pytest.mark.parametrize("resolution", ["Resolved", "Partially Resolved"])
def test_code_resolution_accepts_pr(resolution):
    assert cli._check_code_references(resolution, PR, ()) is None


@pytest.mark.parametrize("resolution", ["Acknowledged, will resolve", "acknowledged, not resolved"])
def test_acknowledged_resolution_needs_no_reference(resolution):
    assert cli._check_code_references(resolution, None, ()) is None


@pytest.mark.parametrize("resolution", ["Acknowledged, will resolve", "Acknowledged, not resolved"])
def test_acknowledged_resolution_rejects_commit(resolution):
    with pytest.raises(click.ClickException, match="has no PR or commit fields"):
        cli._check_code_references(resolution, None, ("abc1234",))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
