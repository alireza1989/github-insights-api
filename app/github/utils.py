"""Shared utilities for the GitHub integration layer."""

from __future__ import annotations

import re

_REPO_RE = re.compile(r"^[\w.\-]+/[\w.\-]+$")
_GITHUB_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([^/\s]+/[^/\s?#]+)"
)


def normalize_repo(value: str) -> str:
    """
    Accept a full GitHub URL or an owner/name string; always return owner/name.

    Examples:
        https://github.com/pallets/flask  →  pallets/flask
        github.com/pallets/flask          →  pallets/flask
        pallets/flask                     →  pallets/flask
    """
    value = value.strip()
    url_match = _GITHUB_URL_RE.match(value)
    if url_match:
        value = url_match.group(1)
        value = value.rstrip("/")
        value = re.sub(r"\.git$", "", value)
        # Drop any sub-paths (e.g. /issues, /pulls)
        parts = value.split("/")
        value = "/".join(parts[:2])

    if not _REPO_RE.match(value):
        raise ValueError(
            f"'{value}' is not a valid repo. "
            "Use 'owner/name' format or paste a full GitHub URL."
        )
    return value
