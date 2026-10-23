#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "browser-cookie3",
#     "click",
#     "playwright",
#     "rich",
# ]
# ///
"""CLI to read OpenZeppelin audit reports using browser cookies for auth.

Uses installed Google Chrome through Playwright to render the audit site
with session cookies imported from Chrome or supplied through stdin.
"""

import json
import logging
import sys
from pathlib import Path

import click
from playwright.sync_api import Error as PlaywrightError, sync_playwright
from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)

BASE_URL = "https://audits.openzeppelin.com"
CONFIG_DIR = Path.home() / ".config" / "oz-audits"
CONFIG_FILE = CONFIG_DIR / "config.json"

VAULT_DOCUMENT = "oz-audits config.json"
console = Console()


# -- Config management --------------------------------------------------------


def load_config() -> dict:
    """Prefer vault credentials, retaining local configuration during outages."""
    config = vault_config()
    if config:
        return config
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def auth_broker(operation: str, config: dict | None = None) -> dict:
    """Use the shared vault broker without exposing credentials in arguments."""
    import shutil
    import subprocess

    helper = shutil.which("claudine-secret") or str(Path.home() / ".local/bin/claudine-secret")
    args = [helper, "auth", operation, "oz-audits"]
    if operation == "status":
        args.append("--json")
    try:
        result = subprocess.run(
            args, input=json.dumps(config) if config is not None else None,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode not in (0, 3) or not result.stdout.strip():
            return {}
        payload = json.loads(result.stdout)
        if operation == "load" and result.returncode != 0:
            return {}
        return payload if isinstance(payload, dict) else {}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {}


def vault_config() -> dict:
    """Prefer pending credentials and 1Password through the shared broker."""
    # A login made while the broker was absent must not revert to stale vault data.
    if CONFIG_FILE.with_suffix(".pending").exists() and CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return auth_broker("load")


def save_config(config: dict) -> None:
    """Keep a protected working copy and sync successful login credentials."""
    import os
    import tempfile

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    marker = CONFIG_FILE.with_suffix(".pending")
    marker.touch(mode=0o600)
    # Atomic replacement prevents truncated credentials after a crash.
    descriptor, temporary = tempfile.mkstemp(prefix=".auth-", dir=CONFIG_FILE.parent)
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(json.dumps(config, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, CONFIG_FILE)
    finally:
        Path(temporary).unlink(missing_ok=True)
    metadata = auth_broker("save", config)
    if metadata.get("source") == "vault" and not metadata.get("pending"):
        marker.unlink(missing_ok=True)
    else:
        logging.getLogger(__name__).warning("Login saved locally; 1Password synchronization is pending.")



def _parse_cookie_header(cookie_str: str) -> list[dict]:
    """Convert a raw Cookie header string into Playwright cookie dicts.

    Playwright needs structured cookies with name, value, domain, path.
    Cookies prefixed with __Secure- or __Host- require the secure flag.
    """
    cookies = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name = name.strip()
        cookie = {
            "name": name,
            "value": value.strip(),
            "domain": "audits.openzeppelin.com",
            "path": "/",
        }
        # Secure-prefixed cookies require the secure flag per spec
        if name.startswith("__Secure-") or name.startswith("__Host-"):
            cookie["secure"] = True
        cookies.append(cookie)
    return cookies


# -- Browser helpers ----------------------------------------------------------


def _launch_browser(playwright):
    """Use installed Chrome independently of Playwright's browser cache."""
    logger.info("Launching Chrome…")
    try:
        return playwright.chromium.launch(channel="chrome", headless=True)
    except PlaywrightError as exc:
        logger.debug("Chrome launch failed", exc_info=True)
        raise click.ClickException(
            "Could not launch Google Chrome. Install Chrome, then retry. "
            "Use --verbose for browser diagnostics."
        ) from exc


def _check_page(page) -> None:
    """Reject sign-in redirects and application error screens before extracting data."""
    if "/sign-in" in page.url:
        raise click.ClickException(
            "Authentication failed — redirected to sign-in. "
            "Sign in at https://audits.openzeppelin.com in Chrome, "
            "then run 'login --browser chrome'."
        )
    if page.get_by_role("heading", name="This page couldn’t load", exact=True).count() or (
        page.get_by_text("This page couldn’t load", exact=True).count()
    ):
        raise click.ClickException(
            "The audit site returned 'This page couldn’t load'. "
            "Check the page in Chrome; if it works there, refresh credentials "
            "with 'login --browser chrome'."
        )


def _chrome_cookie_header(cookie_file: str | None = None) -> str:
    """Import only OZ cookies so unrelated browser credentials stay out of the vault."""
    import browser_cookie3

    try:
        jar = browser_cookie3.chrome(cookie_file=cookie_file, domain_name="audits.openzeppelin.com")
    except Exception as exc:
        logger.debug("Chrome cookie import failed", exc_info=True)
        raise click.ClickException(
            "Could not read Chrome cookies. Unlock the browser credential store, "
            "or use 'login --cookie-stdin --org <org>' with a Cookie header from DevTools."
        ) from exc
    header = "; ".join(
        f"{cookie.name}={cookie.value}" for cookie in jar
        if cookie.domain.lstrip(".") == "audits.openzeppelin.com" and not cookie.is_expired()
    )
    if not header:
        raise click.ClickException(
            "No OZ cookies found in Chrome. Sign in at https://audits.openzeppelin.com, "
            "then retry; use --cookie-file for another Chrome profile."
        )
    return header


def _site_path(path: str) -> str:
    """Accept a full audits.openzeppelin.com URL as well as a site path."""
    path = path.strip()
    if path.startswith(BASE_URL):
        path = path[len(BASE_URL):]
    elif path.startswith("http"):
        raise click.BadParameter(f"{path} is not on {BASE_URL}; pass /<org>/<audit-slug>")
    return path if path.startswith("/") else f"/{path}"


def fetch_page(cookie_str: str, path: str, wait_ms: int = 8000) -> dict:
    """Render a page using Playwright and return text + links.

    Launches installed Chrome headlessly, injects session cookies, navigates
    to the page, waits for JS to render, then extracts content.
    Returns dict with 'text', 'html', 'links', 'url' keys.
    """
    url = f"{BASE_URL}{_site_path(path)}"
    cookies = _parse_cookie_header(cookie_str)

    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        logger.debug("Navigating to %s", url)
        page.goto(url, wait_until="domcontentloaded")
        # Wait for JS to render the SPA content
        page.wait_for_timeout(wait_ms)

        final_url = page.url
        _check_page(page)

        # Extract rendered text content
        text = page.evaluate("() => document.body.innerText")
        html = page.content()

        # Extract all internal links
        links = page.evaluate(
            """() => {
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({text: a.innerText.trim(), href: a.getAttribute('href')}))
                    .filter(l => l.text && (l.href.startsWith('/') || l.href.includes('audits.openzeppelin.com')))
            }"""
        )

        browser.close()

    return {"text": text, "html": html, "links": links, "url": final_url}


# -- CLI commands -------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging.")
def cli(verbose: bool):
    """Read OpenZeppelin audit reports.

    First run 'login' to store your browser cookies and organization
    slug, then use 'ls', 'read', 'links', or 'search' to explore
    audit content.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def _require_org(config: dict) -> str:
    """Return the organization slug from config or raise a clear error.

    The slug is the URL path segment under audits.openzeppelin.com that
    identifies your organization's project area (e.g. the "<org>" in
    https://audits.openzeppelin.com/<org>). Stored via the 'login' command.
    """
    org = config.get("org", "").strip().strip("/")
    if not org:
        raise click.ClickException(
            "No organization slug configured. Run 'login' and set one."
        )
    return org


@cli.command()
@click.option("--cookie-stdin", is_flag=True, help="Read the Cookie header from stdin without echoing it.")
@click.option("--org", default=None, help="Organization slug, e.g. your-org.")
@click.option("--browser", type=click.Choice(["chrome"]), help="Import the signed-in Chrome session.")
@click.option("--cookie-file", type=click.Path(exists=True, dir_okay=False), help="Chrome Cookies database for a specific profile; requires --browser chrome.")
def login(cookie_stdin: bool, org: str | None, browser: str | None, cookie_file: str | None):
    """Store browser cookies and organization slug for authentication.

    Examples: login --browser chrome --org your-org

    Or pipe a Cookie header to: login --cookie-stdin --org your-org

    Manual steps:
      1. Open https://audits.openzeppelin.com in your browser and log in
      2. Open DevTools (F12) > Network tab
      3. Refresh the page, click any request to audits.openzeppelin.com
      4. In the request headers, find the "Cookie:" header
      5. Copy the FULL cookie string and paste it here
      6. Enter your organization slug (the path segment in the URL,
         e.g. the "<org>" in audits.openzeppelin.com/<org>)
    """
    if cookie_stdin and browser:
        raise click.UsageError("Choose either --browser chrome or --cookie-stdin.")
    if cookie_file and not browser:
        raise click.UsageError("--cookie-file requires --browser chrome.")
    config = load_config()
    if (cookie_stdin or browser) and not (org or config.get("org")):
        raise click.ClickException("Provide --org with --cookie-stdin or --browser chrome.")

    console.print("[bold]OpenZeppelin Audits CLI — Login[/]\n")
    if not (cookie_stdin or browser):
        console.print("Sign in at https://audits.openzeppelin.com in Chrome.")
        console.print("Copy the full Cookie header from a site request in DevTools → Network.")

    existing = config.get("cookie", "")
    if existing and not (cookie_stdin or browser):
        console.print(
            "[dim]Press Enter to keep existing cookie, or paste a new one.[/]"
        )

    if browser:
        cookie = _chrome_cookie_header(cookie_file)
    elif cookie_stdin:
        cookie = sys.stdin.read().strip()
    else:
        cookie = click.prompt(
            "Paste Cookie header value", default=existing if existing else None,
            show_default=False, hide_input=True,
        )
    if not cookie.strip():
        raise click.ClickException("Cookie header is empty; copy it from your signed-in Chrome session.")

    existing_org = config.get("org", "")
    org = org or existing_org or click.prompt(
        "Organization slug (path segment, e.g. 'your-org')",
        default=existing_org if existing_org else None,
        show_default=bool(existing_org),
    )

    config["cookie"] = cookie.strip()
    config["org"] = org.strip().strip("/")

    # Validate by fetching the organization's project page
    console.print("\n[yellow]Validating (launching Chrome)…[/]")
    fetch_page(config["cookie"], f"/{config['org']}", wait_ms=5000)
    # Invalid sessions must not replace working local or vault credentials.
    save_config(config)

    console.print("[green bold]Logged in successfully![/]")
    console.print(f"[dim]Config saved to {CONFIG_FILE}[/]")


@cli.command(name="ls")
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
def list_audits(wait: int):
    """List available audits on your organization's project page."""
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    org = _require_org(config)
    result = fetch_page(cookie, f"/{org}", wait_ms=wait)

    if result["links"]:
        table = Table(title="Audit Links")
        table.add_column("Title", style="cyan")
        table.add_column("Path", style="green")
        for link in result["links"]:
            table.add_row(link["text"], link["href"])
        console.print(table)

    console.print("\n[bold]Page Content:[/bold]\n")
    text = result["text"]
    console.print(text[:5000] if len(text) > 5000 else text)


@cli.command()
@click.argument("path")
@click.option(
    "--output", "-o", type=click.Path(), default=None,
    help="Save output to file instead of printing.",
)
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
def read(path: str, output: str | None, wait: int):
    """Read a specific audit page by its path.

    PATH is the URL path relative to the base, e.g. /<org>/some-audit-id.
    """
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    if not path.startswith("/"):
        path = f"/{path}"

    result = fetch_page(cookie, path, wait_ms=wait)
    text = result["text"]

    if output:
        out_path = Path(output)
        out_path.write_text(text, encoding="utf-8")
        console.print(f"[green]Saved to {out_path}[/green]")
    else:
        console.print(text)


@cli.command()
@click.argument("path")
@click.option(
    "--output", "-o", type=click.Path(), default=None,
    help="Save raw HTML to file.",
)
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
def html(path: str, output: str | None, wait: int):
    """Fetch rendered HTML of a page.

    PATH is the URL path relative to the base, e.g. /<org>.
    """
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    if not path.startswith("/"):
        path = f"/{path}"

    result = fetch_page(cookie, path, wait_ms=wait)

    if output:
        out_path = Path(output)
        out_path.write_text(result["html"], encoding="utf-8")
        console.print(f"[green]Saved HTML to {out_path}[/green]")
    else:
        console.print(result["html"])


@cli.command()
@click.argument("path")
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
def links(path: str, wait: int):
    """List all internal links on a page."""
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    if not path.startswith("/"):
        path = f"/{path}"

    result = fetch_page(cookie, path, wait_ms=wait)
    found = result["links"]

    if not found:
        console.print("[yellow]No internal links found on this page.[/yellow]")
        return

    table = Table(title=f"Links on {path}")
    table.add_column("Text", style="cyan")
    table.add_column("Href", style="green")
    for link in found:
        table.add_row(link["text"], link["href"])
    console.print(table)


@cli.command()
@click.argument("path")
@click.argument("query")
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
def search(path: str, query: str, wait: int):
    """Search page content for a keyword.

    Prints lines from the extracted text that contain QUERY (case-insensitive).
    """
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    if not path.startswith("/"):
        path = f"/{path}"

    result = fetch_page(cookie, path, wait_ms=wait)
    text = result["text"]

    query_lower = query.lower()
    matches = [line for line in text.splitlines() if query_lower in line.lower()]

    if not matches:
        console.print(f"[yellow]No matches for '{query}' on {path}[/yellow]")
        return

    console.print(f"[bold]{len(matches)} matches for '{query}':[/bold]\n")
    for line in matches:
        console.print(line)


# Valid values for the "Proposed Resolution" dropdown as rendered in the UI.
RESOLUTION_CHOICES = (
    "Resolved",
    "Partially Resolved",
    "Acknowledged, will resolve",
    "Acknowledged, not resolved",
)


@cli.command()
@click.argument("path")
@click.option(
    "--resolution",
    "-r",
    type=click.Choice(RESOLUTION_CHOICES, case_sensitive=False),
    default="Resolved",
    help="Proposed Resolution dropdown value.",
)
@click.option(
    "--response",
    "-m",
    required=True,
    help="Response Details body text (plain text, newlines preserved).",
)
@click.option(
    "--pr",
    default=None,
    help="Pull Request URL (e.g. https://github.com/org/repo/pull/123).",
)
@click.option(
    "--commit",
    "-c",
    multiple=True,
    help="Commit URL or hash. Repeat to add multiple commits.",
)
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
@click.option(
    "--dry-run",
    is_flag=True,
    help="Fill the form but do not click Submit. Saves a screenshot for verification.",
)
@click.option(
    "--screenshot",
    type=click.Path(),
    default=None,
    help="Save a screenshot of the filled form (helpful with --dry-run).",
)
def submit(
    path: str,
    resolution: str,
    response: str,
    pr: str | None,
    commit: tuple[str, ...],
    wait: int,
    dry_run: bool,
    screenshot: str | None,
):
    """Submit an official response to an OZ audit issue.

    PATH is the issue URL path, e.g.
    /<org>/<audit-slug>/issue/<issue-slug>

    At least one of --pr or --commit must be supplied (the form enforces this).
    Use --dry-run to fill the form without submitting (useful for preview).
    """
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    # The form requires at least one of PR URL or commit hashes.
    if not pr and not commit:
        raise click.ClickException(
            "At least one of --pr or --commit must be provided."
        )

    if not path.startswith("/"):
        path = f"/{path}"

    url = f"{BASE_URL}{_site_path(path)}"
    cookies = _parse_cookie_header(cookie)

    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        logger.debug("Navigating to %s", url)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(wait)

        _check_page(page)

        # The Audit Experience Survey is a fixed-position widget that intercepts
        # pointer events over the bottom-right corner. Hide it so Playwright can
        # reliably click the dialog controls beneath it.
        page.evaluate(
            """() => {
                const s = document.querySelector('div.fixed.bottom-6.right-6');
                if (s) s.style.display = 'none';
            }"""
        )

        # Open the submission dialog.
        submit_btn = page.query_selector(
            'button:has-text("Submit Official Response")'
        )
        if submit_btn is None:
            browser.close()
            raise click.ClickException(
                "Could not find 'Submit Official Response' button on page. "
                "Verify the path points to an issue page and that your account "
                "has permission to respond."
            )
        submit_btn.click(force=True)
        page.wait_for_selector('[role="dialog"]', timeout=10_000)
        page.wait_for_timeout(1000)

        # Select the Proposed Resolution. The dropdown default is already
        # "Resolved" — skip the click if that matches to avoid flicker.
        current = page.evaluate(
            "() => document.querySelector('[role=\"dialog\"] [role=\"combobox\"] span')?.innerText?.trim()"
        )
        if (current or "").lower() != resolution.lower():
            page.query_selector('[role="dialog"] [role="combobox"]').click()
            page.wait_for_timeout(500)
            # Match option by case-insensitive text.
            page.evaluate(
                """(target) => {
                    const opts = Array.from(document.querySelectorAll('[role="option"]'));
                    const hit = opts.find(o => o.innerText.trim().toLowerCase() === target.toLowerCase());
                    if (hit) hit.click();
                }""",
                resolution,
            )
            page.wait_for_timeout(500)

        # Fill the Response Details TipTap editor. It's contenteditable so we
        # focus it and type the text (newlines included).
        editor = page.query_selector('[role="dialog"] [contenteditable="true"]')
        if editor is None:
            browser.close()
            raise click.ClickException("Response editor not found in dialog.")
        editor.click()
        page.wait_for_timeout(200)
        # Clear any placeholder state, then insert the response text.
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        # type() preserves newlines and is safer than setting innerHTML for
        # TipTap's internal document model.
        editor.type(response, delay=1)
        page.wait_for_timeout(300)

        # Fill the Pull Request URL if provided.
        if pr:
            pr_input = page.query_selector('[role="dialog"] input#pr-link')
            if pr_input is None:
                browser.close()
                raise click.ClickException("PR input not found in dialog.")
            pr_input.fill(pr)
            page.wait_for_timeout(200)

        # Add each commit. The dialog ships with one empty input + "Add commit"
        # button; we fill the first empty input, then click Add commit for
        # subsequent entries.
        for idx, c in enumerate(commit):
            # The commit inputs are identified by their placeholder.
            inputs = page.query_selector_all(
                '[role="dialog"] input[placeholder*="commit"]'
            )
            if idx >= len(inputs):
                # Need to add a new input row.
                add_btn = page.query_selector(
                    '[role="dialog"] button:has-text("Add commit")'
                )
                if add_btn is None:
                    browser.close()
                    raise click.ClickException("Add commit button not found.")
                add_btn.click()
                page.wait_for_timeout(300)
                inputs = page.query_selector_all(
                    '[role="dialog"] input[placeholder*="commit"]'
                )
            inputs[idx].fill(c)
            page.wait_for_timeout(200)

        # Screenshot the filled form for audit trail / dry-run verification.
        if screenshot:
            page.screenshot(path=screenshot, full_page=True)
            console.print(f"[green]Screenshot saved to {screenshot}[/green]")

        if dry_run:
            console.print(
                "[yellow bold]Dry run — form filled but NOT submitted.[/]"
            )
            browser.close()
            return

        # Click the final Submit Response button inside the dialog. It becomes
        # enabled once the required fields are populated; wait briefly to let
        # the form validate.
        page.wait_for_timeout(500)
        final_btn = page.query_selector(
            '[role="dialog"] button:has-text("Submit Response")'
        )
        if final_btn is None:
            browser.close()
            raise click.ClickException("Final Submit Response button not found.")
        # Check disabled state — if disabled, the required fields aren't valid.
        is_disabled = page.evaluate(
            """(btn) => btn.disabled || btn.hasAttribute('disabled')""",
            final_btn,
        )
        if is_disabled:
            browser.close()
            raise click.ClickException(
                "Submit Response button is disabled — response text or PR/commit "
                "may not have been registered by the form. Try --dry-run with "
                "--screenshot to inspect."
            )
        final_btn.click()

        # Wait for the dialog to close (indicates submission).
        try:
            page.wait_for_selector(
                '[role="dialog"]', state="detached", timeout=15_000
            )
            console.print(
                f"[green bold]Submitted response for[/] {path}"
            )
        except Exception:
            # Dialog did not close — capture current state for debugging.
            err_shot = screenshot or f"/tmp/oz_submit_error_{path.split('/')[-1]}.png"
            page.screenshot(path=err_shot, full_page=True)
            console.print(
                f"[red]Dialog did not close after submit. Screenshot: {err_shot}[/]"
            )
        finally:
            browser.close()


@cli.command()
@click.argument("path")
@click.option("--wait", "-w", default=8000, help="Wait ms for JS render.")
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip the 'are you sure?' CLI confirmation prompt.",
)
def remove(path: str, wait: int, yes: bool):
    """Remove a previously-submitted official response from an issue.

    PATH is the issue URL path, e.g.
    /<org>/<audit-slug>/issue/<issue-slug>

    Only works when a response is already on file — the sidebar shows a
    "Remove Response" button in that case. If no response is present, the
    command exits with a clear message and does not alter state.
    """
    config = load_config()
    cookie = config.get("cookie", "")
    if not cookie:
        raise click.ClickException("Not logged in. Run 'login' first.")

    if not yes and not click.confirm(
        f"Permanently remove the official response on {path}?", default=False
    ):
        console.print("[yellow]Aborted.[/]")
        return

    if not path.startswith("/"):
        path = f"/{path}"

    url = f"{BASE_URL}{_site_path(path)}"
    cookies = _parse_cookie_header(cookie)

    with sync_playwright() as p:
        browser = _launch_browser(p)
        context = browser.new_context()
        context.add_cookies(cookies)
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(wait)

        _check_page(page)

        # Same fixed-position widget that blocks clicks on submit — hide it.
        page.evaluate(
            """() => {
                const s = document.querySelector('div.fixed.bottom-6.right-6');
                if (s) s.style.display = 'none';
            }"""
        )

        remove_btn = page.query_selector('button:has-text("Remove Response")')
        if remove_btn is None:
            browser.close()
            console.print(
                "[yellow]No 'Remove Response' button found — no response is "
                "currently on file for this issue.[/]"
            )
            return

        remove_btn.click(force=True)

        # Removal may open a confirmation dialog (role=dialog or alertdialog)
        # with a destructive "Remove" / "Delete" / "Confirm" action button.
        # Wait briefly for the dialog, then click any button whose text starts
        # with Remove/Delete/Confirm/Yes. If no dialog appears, the click above
        # may have been the whole flow — we still wait for the "Remove Response"
        # button to disappear as proof of success.
        try:
            page.wait_for_selector(
                '[role="dialog"], [role="alertdialog"]', timeout=3000
            )
            page.wait_for_timeout(500)
            confirm_btn = page.evaluate_handle(
                """() => {
                    const d = document.querySelector('[role="dialog"], [role="alertdialog"]');
                    if (!d) return null;
                    const candidates = Array.from(d.querySelectorAll('button'));
                    // Prefer destructive/primary action words first, avoid Cancel.
                    const priority = ['remove', 'delete', 'confirm', 'yes'];
                    for (const word of priority) {
                        const hit = candidates.find(b => {
                            const t = b.innerText.trim().toLowerCase();
                            return t && t.includes(word) && !t.includes('cancel');
                        });
                        if (hit) return hit;
                    }
                    return null;
                }"""
            )
            if confirm_btn:
                try:
                    confirm_btn.as_element().click()
                except Exception:
                    pass
        except Exception:
            # No confirmation dialog — the click itself was the full action.
            pass

        # Success indicator: the "Submit Official Response" button is back
        # (or "Remove Response" is gone). Poll briefly.
        page.wait_for_timeout(2000)
        still_present = page.query_selector('button:has-text("Remove Response")')
        if still_present is None:
            console.print(f"[green bold]Removed response for[/] {path}")
        else:
            err_shot = f"/tmp/oz_remove_error_{path.split('/')[-1]}.png"
            page.screenshot(path=err_shot, full_page=True)
            console.print(
                f"[red]Remove did not take effect. Screenshot: {err_shot}[/]"
            )
        browser.close()


@cli.command("auth-status")
@click.option("--json", "as_json", is_flag=True, help="Return credential metadata without secrets.")
def auth_status(as_json: bool) -> None:
    """Inspect vault synchronization. Example: auth-status --json."""
    metadata = auth_broker("status") or {
        "connector": "oz-audits", "account": "default", "source": "unavailable",
        "configured": False, "pending": False, "last_sync": None,
    }
    metadata["legacy_available"] = CONFIG_FILE.exists()
    if CONFIG_FILE.with_suffix(".pending").exists():
        metadata.update(source="pending", pending=True, configured=CONFIG_FILE.exists())
    click.echo(json.dumps(metadata) if as_json else
               f"{metadata['source']}; pending={metadata['pending']}; local={metadata['legacy_available']}")


@cli.command("auth-sync")
def auth_sync() -> None:
    """Retry pending vault sync or import local credentials. Example: auth-sync."""
    # Broker pending data is newer than any compatibility copy.
    config = vault_config()
    if not config and CONFIG_FILE.exists():
        config = json.loads(CONFIG_FILE.read_text())
    if not config:
        raise click.ClickException("No credentials available to synchronize; connect this tool in Brain.")
    metadata = auth_broker("save", config)
    if not metadata:
        raise click.ClickException("Credential broker unavailable; local login is preserved.")
    if metadata.get("source") == "vault" and not metadata.get("pending"):
        CONFIG_FILE.with_suffix(".pending").unlink(missing_ok=True)
    click.echo(json.dumps(metadata))
    if metadata.get("pending"):
        raise click.exceptions.Exit(3)


from onebrain_policy import install as _install_onebrain_policy  # noqa: E402

_install_onebrain_policy(cli, "oz-audits")

if __name__ == "__main__":
    cli()
