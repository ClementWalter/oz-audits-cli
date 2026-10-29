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
"""`submit` and `edit` drive the same form through the buttons the site labels for each."""

import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))
import oz_audits_cli as cli  # noqa: E402


@pytest.mark.parametrize(
    ("edit", "labels"),
    [
        (False, ("Submit Official Response", "Submit Response")),
        (True, ("Edit Official Response", "Update Response")),
    ],
)
def test_dialog_buttons(edit, labels):
    assert cli.DIALOG_BUTTONS[edit] == labels


def test_edit_rejects_resolved_without_reference():
    result = CliRunner().invoke(cli.cli, ["edit", "/org/audit/issue/x", "-m", "Fixed."])
    assert "requires --pr or --commit" in result.output


def test_edit_takes_the_submit_options():
    submit = {p.name for p in cli.submit.params}
    assert {p.name for p in cli.edit.params} == submit


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
