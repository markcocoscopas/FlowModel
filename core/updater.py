"""
core/updater.py
~~~~~~~~~~~~~~~
In-app update checker and one-click updater.

Checks the GitHub releases API for a newer version.  If one is found,
a banner appears in the sidebar offering a one-click update.

The update downloads only the SOURCE FILES (~1 MB) via GitHub's zipball
endpoint — the bundled Python runtime (python/) is never touched, so the
update is fast and safe to apply while the app is running.

After applying, the user is prompted to close and reopen the launcher.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger(__name__)

GITHUB_REPO  = "markcocoscopas/squad-flow-metrics"
GITHUB_API   = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
APP_ROOT     = Path(__file__).parent.parent
VERSION_FILE = APP_ROOT / "version.txt"

# These paths inside the zip are never overwritten during an update
_SKIP_PREFIXES = (
    "python/",       # bundled Python runtime (Windows only)
)


def current_version() -> str:
    """Return the current version string from version.txt, e.g. '1.0.4'."""
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse 'v1.0.4' or '1.0.4' into (1, 0, 4) for comparison."""
    v = v.lstrip("v").strip()
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0, 0, 0)


def check_for_update(timeout: int = 5) -> tuple[bool, str, str]:
    """
    Query GitHub for the latest release.

    Returns
    -------
    (update_available, latest_tag, release_notes_url)

    On any network error returns (False, '', '') so the app starts
    cleanly with no internet connection.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API,
            headers={"User-Agent": f"squad-flow-metrics/{current_version()}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())

        latest_tag  = data.get("tag_name", "")
        release_url = data.get("html_url", "")

        if not latest_tag:
            return False, "", ""

        available = _parse_version(latest_tag) > _parse_version(current_version())
        return available, latest_tag, release_url

    except Exception as exc:
        log.debug("Update check skipped (%s)", exc)
        return False, "", ""


def download_and_apply(progress_fn=None) -> tuple[bool, str]:
    """
    Download the latest release source zip (~1 MB) and overwrite app files.

    Parameters
    ----------
    progress_fn : optional callable(message: str) — called with status text
                  so the UI can display a spinner message.

    Returns
    -------
    (success: bool, message: str)
    """
    def _progress(msg: str) -> None:
        log.info("Updater: %s", msg)
        if progress_fn:
            progress_fn(msg)

    try:
        _progress("Checking latest release…")
        req = urllib.request.Request(
            GITHUB_API,
            headers={"User-Agent": f"squad-flow-metrics/{current_version()}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        new_tag = data.get("tag_name", "")

        if not new_tag:
            return False, "Could not find release tag."

        # Prefer the zipball_url from the API response — it is the official
        # redirect-aware endpoint and avoids GitHub CDN 403s that can affect
        # the direct /archive/refs/tags/... URL.
        archive_url = (
            data.get("zipball_url")
            or f"https://api.github.com/repos/{GITHUB_REPO}/zipball/{new_tag}"
        )

        _progress(f"Downloading {new_tag} (source files only, ~1 MB)…")

        req = urllib.request.Request(
            archive_url,
            headers={
                "User-Agent": f"squad-flow-metrics/{current_version()}",
                "Accept":     "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            zip_bytes = resp.read()

        _progress("Applying update…")

        updated = 0
        skipped = 0

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            members = zf.namelist()

            # GitHub zipball wraps everything in "owner-repo-sha/" — strip it
            prefix = ""
            if members:
                first = members[0]
                if "/" in first:
                    prefix = first.split("/")[0] + "/"

            for member in members:
                # Strip the top-level GitHub prefix
                rel = member[len(prefix):] if member.startswith(prefix) else member

                if not rel or rel.endswith("/"):
                    continue  # skip directory entries

                # Never touch the bundled Python runtime or launcher files
                if any(rel.startswith(p) for p in _SKIP_PREFIXES):
                    skipped += 1
                    continue

                try:
                    dest = APP_ROOT / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(member))
                    updated += 1
                except Exception as exc:
                    log.warning("Could not write %s: %s", rel, exc)

        # Write new version number
        new_ver = new_tag.lstrip("v")
        VERSION_FILE.write_text(new_ver + "\n", encoding="utf-8")

        msg = f"Updated to {new_tag} — {updated} files replaced."
        _progress(msg)
        return True, msg

    except Exception as exc:
        log.exception("Update failed")
        return False, f"Update failed: {exc}"
