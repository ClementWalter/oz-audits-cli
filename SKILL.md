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

Invoke it as **`oz-audits`**, on `$PATH` via a symlink in `~/.local/bin` onto
this repo's `bin/oz-audits`, so it always runs the current checkout.

```bash
oz-audits read https://audits.openzeppelin.com/<org>/<audit-slug>/issues
```

Every path argument takes either a site path (`/<org>/<audit-slug>`) or the full
URL copied from the browser. If `oz-audits` is not on `$PATH`, run `bin/oz-audits`
resolved against this skill's directory (PEP 723, `uv` resolves deps inline), or
link it once:

```bash
ln -sfn <skill-dir>/bin/oz-audits ~/.local/bin/oz-audits
```

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

When diagnosing failures, compare the same page in signed-in Chrome. A redirect
to sign-in or “This page couldn’t load” fails the CLI command; if Chrome works,
refresh the CLI session with `login --browser chrome`. Missing Chrome produces
an installation error; downloading Playwright Chromium is unnecessary.

## Read commands

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

## Write commands

```bash
# Submit an official response to an issue.
# At least one of --pr or --commit is required.
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --resolution "Resolved" \
  --response "Fixed in the linked PR." \
  --pr https://github.com/org/repo/pull/123 \
  --commit abc1234

# Preview without submitting (fills form, saves screenshot)
oz-audits submit /<org>/<audit-slug>/issue/<issue-slug> \
  --response "..." --pr https://... \
  --dry-run --screenshot /tmp/preview.png

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

`--commit` can be passed multiple times to attach several commit references.

## Getting the Cookie header

1. Open https://audits.openzeppelin.com in your browser and log in
2. Open DevTools (F12) → **Network** tab
3. Refresh the page, click any request to `audits.openzeppelin.com`
4. In the request headers, copy the full **Cookie:** header value
5. Paste it when `login` prompts

## Key Details

- **Auth**: OZ cookies imported from Chrome, or a Cookie header from DevTools
- **Config**: `~/.config/oz-audits/config.json` (keys: `cookie`, `org`)
- **Base URL**: `https://audits.openzeppelin.com`
- **Validation**: Login validates by fetching `/<org>` and checking for sign-in
  redirect
- **Write commands** use Playwright to drive the dialog UI (select resolution,
  fill TipTap editor, add PR URL and commits, submit) and wait for the dialog to
  close as proof of success.

## Credentials from the 1Password vault

The shared `claudine-secret auth` broker loads and synchronizes credentials with
1Password. Broker credentials take precedence over the local compatibility file
`~/.config/oz-audits/config.json`, except when a local `.pending` marker records
an unsynchronized login. The local file is saved with mode `0600`; it contains
the Cookie header and organization slug. Broker outages retain that working
copy.

Use `auth-status --json` for synchronization metadata without exposing secrets,
and `auth-sync` to retry pending synchronization. These commands do not validate
the website session; use `ls` to check access.
