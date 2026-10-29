# oz-audits-cli

**Visibility: public.**

Read OpenZeppelin audit reports on `audits.openzeppelin.com` and submit official
responses to their issues, from the terminal. It renders the site in a headless
installed Chrome with the session cookies of your signed-in Chrome.

## Install

```bash
uv run claudine/scripts/link_clis.py   # links bin/oz-audits into ~/.local/bin
```

`uv` resolves the dependencies on first run (PEP 723). Google Chrome must be
installed.

## Usage

```bash
oz-audits login --browser chrome --org <org>     # import the signed-in Chrome session
oz-audits ls                                     # audits on the org page
oz-audits read <url-or-path> -o audit.txt        # rendered page text
oz-audits links <url-or-path>                    # internal links on a page
oz-audits search <url-or-path> "critical"        # lines matching a keyword
oz-audits html <url-or-path> -o page.html        # rendered HTML
oz-audits submit <issue-url> --response "..." --pr <pr-url> --dry-run
oz-audits edit <issue-url> --response "..." --pr <pr-url> --dry-run   # replace a posted response
oz-audits remove <issue-url>
oz-audits auth-status --json                     # vault sync metadata, no secrets
```

See [SKILL.md](SKILL.md) for the full manual.

## Tests

```bash
for t in tests/test_*.py; do uv run --script "$t"; done
```

## Privacy Policy

The Claude Desktop extension built from this repository keeps your data on your
Mac and talks only to the service it connects to. Full policy:
<https://clementwalter.github.io/claude-extensions/privacy/>
