---
name: oz-audits-cli
description:
  "Read and respond to OpenZeppelin audit reports (audits.openzeppelin.com) via
  the `oz-audits` command, using browser cookies. Use
  when the user asks to read, fetch, list, search, or submit/remove official
  responses on OZ audit reports."
allowed-tools:
  - Bash
  - Read
---

# OpenZeppelin Audits Reader

Read OpenZeppelin audit reports and submit official responses using installed
Google Chrome and session cookies. The CLI launches a separate headless Chrome;
it does not depend on Playwright's downloaded Chromium or control your open
tabs.

## How to invoke

Invoke it as **`oz-audits`**, on `$PATH` via `uv run claudine/scripts/link_clis.py`
(it links this repo's `bin/oz-audits` into `~/.local/bin`, so it always runs the
current checkout). If `oz-audits` is missing from `$PATH`, run
`<skill-dir>/bin/oz-audits` directly (PEP 723, `uv` resolves deps inline).

```bash
oz-audits read https://audits.openzeppelin.com/<org>/<audit-slug>/issues
```

Every path argument takes either a site path (`/<org>/<audit-slug>`) or the full
URL copied from the browser.

## Authentication

```bash
# Sign in at https://audits.openzeppelin.com in Chrome first, then import it.
oz-audits login --browser chrome --org your-org
```

Use the organization slug from the signed-in URL. An existing configured slug
can be reused without `--org`. For another Chrome profile, pass `--cookie-file`
with that profile's Cookies database. Login validates the imported session
before saving; an invalid session leaves stored credentials untouched.

If cookie extraction is unavailable, `login` prompts for a hidden Cookie header,
or `login --cookie-stdin --org your-org` reads it from stdin. Never put cookies
in command arguments or logs. Login does not complete the website's sign-in
flow.

`login` is optional when Chrome is signed in: a page command with no stored
session reads Chrome's default profile, and one whose stored session expired
retries once with Chrome's current session; the session that worked is saved.
`$OZ_AUDITS_ORG` (the Claude Desktop extension's Organization setting) wins over
the stored slug. `remove` without `--yes` and without a terminal is a dry run.

### Getting the Cookie header

1. Open https://audits.openzeppelin.com in your browser and log in
2. Open DevTools (F12) → **Network** tab
3. Refresh the page, click any request to `audits.openzeppelin.com`
4. In the request headers, copy the full **Cookie:** header value
5. Paste it when `login` prompts

### Credentials from the 1Password vault

The shared `claudine-secret auth` broker loads and synchronizes credentials with
1Password. Broker credentials take precedence over the local compatibility file
`~/.config/oz-audits/config.json`, except when a local `.pending` marker records
an unsynchronized login. The local file is saved with mode `0600`; it contains
the Cookie header and organization slug. Broker outages retain that working
copy.

Use `auth-status --json` for synchronization metadata without exposing secrets,
and `auth-sync` to retry pending synchronization. These commands do not validate
the website session; use `ls` to check access.

## Output conventions

- stdout carries data only: page text (`read`, `ls`), raw HTML (`html`),
  matching lines (`search`), link tables (`ls`, `links`), and the
  `auth-status` / `auth-sync` line or JSON.
- Status, confirmations and errors go to stderr, so `oz-audits read … > a.txt`
  captures the page alone.
- `auth-status --json` and `auth-sync` print JSON; the page commands print text
  (there is no `--json` on them, the site renders free-form text).
- `-o FILE` on `read` / `html` writes the file and reports the path on stderr.

## Commands

### Read

```bash
# List audits on your organization's project page
oz-audits ls

# Read a specific audit page as text
oz-audits read /<org>/some-audit-id

# Save to file
oz-audits read /<org>/some-audit-id -o audit.txt

# List all links on a page
oz-audits links /<org>

# Search page content for a keyword
oz-audits search /<org> "critical"

# Dump raw HTML (debugging)
oz-audits html /<org> -o page.html
```

Replace `<org>` with your organization slug as it appears in the
audits.openzeppelin.com URL.

### Write

```bash
# Submit an official response to an issue.
# Resolved and Partially Resolved require --pr or --commit.
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --resolution "Resolved" \
  --response "Fixed in the linked PR." \
  --pr https://github.com/org/repo/pull/123 \
  --commit abc1234

# Preview without submitting (fills form, saves screenshot)
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --response "..." --pr https://... \
  --dry-run --screenshot /tmp/preview.png

# Won't fix: the acknowledged resolutions have no PR or commit fields
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --resolution "Acknowledged, not resolved" \
  --response "Won't fix: ..."

# Remove a previously-submitted response (with CLI confirmation)
oz-audits remove /<org>/<audit-slug>/issue/<issue-slug>

# Skip the confirmation prompt
oz-audits remove /<org>/<audit-slug>/issue/<issue-slug> -y
```

Valid `--resolution` values (case-insensitive):

- `Resolved` (default)
- `Partially Resolved`
- `Acknowledged, will resolve`
- `Acknowledged, not resolved`

Only `Resolved` and `Partially Resolved` show the PR and commit fields, so the
CLI requires one of `--pr`/`--commit` for them and rejects both for the
acknowledged resolutions. `--commit` can be passed multiple times to attach
several commit references.

## Recipes

```bash
# Which issues are in this audit, and what does the critical one say?
oz-audits links /<org>/<audit-slug>
oz-audits read /<org>/<audit-slug>/issue/<issue-slug>

# Find every mention of a keyword in a report, then save the whole report
oz-audits search /<org>/<audit-slug> "reentrancy"
oz-audits read /<org>/<audit-slug> -o audit.txt

# Answer an issue: preview first, read the screenshot, then submit for real
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --response "Fixed in the linked PR." --pr https://github.com/org/repo/pull/123 \
  --dry-run --screenshot /tmp/preview.png
```

## Gotchas

- `Session expired: the audit site rejected the stored credentials`: the site
  redirected to sign-in or its API answered 401/403. Sign in at
  https://audits.openzeppelin.com in Chrome and re-run the command (it retries
  with Chrome's session), or run `oz-audits login --browser chrome`.
- `This page couldn’t load` with a valid session: not an auth problem. Check
  the audit path and open the same page in signed-in Chrome.
- Missing Chrome produces an installation error; downloading Playwright
  Chromium is unnecessary.
- `submit` sends for real unless `--dry-run`; always preview first and show the
  user the screenshot. `remove` asks for confirmation unless `-y`.
- Never put cookies in command arguments or logs; use `--browser chrome` or
  `--cookie-stdin`.

### Key details

- **Auth**: OZ cookies imported from Chrome, or a Cookie header from DevTools
- **Config**: `~/.config/oz-audits/config.json` (keys: `cookie`, `org`)
- **Base URL**: `https://audits.openzeppelin.com`
- **Validation**: Login validates by fetching `/<org>` and checking for a sign-in
  redirect or API calls rejected with 401/403 (expired session)
- **Write commands** use Playwright to drive the dialog UI (select resolution,
  fill TipTap editor, add PR URL and commits, submit) and wait for the dialog to
  close as proof of success.
