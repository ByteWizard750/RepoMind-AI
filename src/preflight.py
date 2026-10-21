"""Before cloning: what the URL points at, and whether it's worth cloning.

- Folder URLs (https://github.com/owner/repo/tree/<branch>/<folder>) are
  split into the repository to clone, the branch and the folder. Branch
  names may contain "/", so the branch is the longest one the remote
  actually has that the path starts with.
- For github.com, one API call each for the repository and its languages:
  a repository with no Python/JavaScript/TypeScript at all is rejected
  before a possibly long clone, and a mostly-other-language one gets a
  notice. The API is advisory: rate limits, network errors or a non-GitHub
  host just skip it (the post-clone scope check is the authority).
"""
import os
import re
import subprocess

import httpx

from review.github_issues import API_URL, repo_slug

PREFLIGHT_TIMEOUT_SECONDS = 6
LS_REMOTE_TIMEOUT_SECONDS = 30
_SUPPORTED = ("Python", "JavaScript", "TypeScript")
_TREE_URL = re.compile(r"^(https?://(?:www\.)?github\.com/[^/\s]+/[^/\s]+?)(?:\.git)?/tree/(\S+?)/?$", re.IGNORECASE)
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class PreflightError(ValueError):
    pass


def split_tree_url(url: str):
    """(repository URL, "branch/and/folder" rest) for a GitHub folder URL,
    else (url, None)."""
    m = _TREE_URL.match(url.strip())
    return (m.group(1), m.group(2)) if m else (url, None)


def split_ref(rest: str, branches: list):
    """The longest branch that `rest` starts with, and the folder after it."""
    for branch in sorted(branches, key=len, reverse=True):
        if rest == branch:
            return branch, ""
        if rest.startswith(branch + "/"):
            return branch, rest[len(branch) + 1:].strip("/")
    return None, None


def remote_branches(url: str) -> list:
    try:
        out = subprocess.run(["git", "ls-remote", "--heads", "--", url], capture_output=True, text=True,
                             env=_GIT_ENV, timeout=LS_REMOTE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise PreflightError(f"GitHub didn't answer within {LS_REMOTE_TIMEOUT_SECONDS}s while looking up the branch.")
    if out.returncode != 0:
        raise PreflightError(f"Couldn't read the branches of {url}. Check the URL and that the repository is public.")
    return [line.split("refs/heads/", 1)[1] for line in out.stdout.splitlines() if "refs/heads/" in line]


def resolve(url: str) -> dict:
    """{"clone_url", "ref" (branch or None), "subdir" ("" for the whole repo)}."""
    base, rest = split_tree_url(url)
    if rest is None:
        return {"clone_url": url, "ref": None, "subdir": ""}
    branch, subdir = split_ref(rest, remote_branches(base))
    if branch is None:
        raise PreflightError(f"The branch in this URL doesn't exist in {base}.")
    return {"clone_url": base, "ref": branch, "subdir": subdir}


def _headers() -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"   # 5,000 requests/hour instead of 60
    return headers


def github_facts(clone_url: str, transport=None):
    """Size and languages from the GitHub API, or None when unavailable."""
    slug = repo_slug(clone_url)
    if not slug:
        return None
    try:
        with httpx.Client(base_url=API_URL, headers=_headers(), timeout=PREFLIGHT_TIMEOUT_SECONDS,
                          transport=transport) as client:
            repo = client.get(f"/repos/{slug}")
            if repo.status_code == 404:
                raise PreflightError(f"GitHub says {slug} doesn't exist or isn't public.")
            if repo.status_code != 200:
                return None
            langs = client.get(f"/repos/{slug}/languages")
            languages = langs.json() if langs.status_code == 200 else None
            info = repo.json()
    except (httpx.HTTPError, ValueError) as exc:
        if isinstance(exc, PreflightError):
            raise
        return None
    return {"size_mb": round(info.get("size", 0) / 1024, 1), "default_branch": info.get("default_branch"),
            "languages": languages if isinstance(languages, dict) else None}


def language_check(languages: dict):
    """Raises for a repository with no supported code; returns a notice
    when supported code is a small part of it, else None."""
    if not languages:
        return None
    total = sum(languages.values())
    supported = sum(languages.get(name, 0) for name in _SUPPORTED)
    ranked = sorted(languages.items(), key=lambda item: -item[1])
    if total and supported == 0:
        shown = ", ".join(f"{name} ({round(100 * n / total)}%)" for name, n in ranked[:3])
        raise PreflightError(f"This repository is written in {shown}. "
                             "RepoMind currently analyzes Python, JavaScript and TypeScript code.")
    share = supported / total if total else 1
    if share < 0.5:
        main = ranked[0][0]
        return (f"Only {round(100 * share)}% of this repository's code is Python, JavaScript or TypeScript "
                f"(it is mostly {main}); RepoMind analyzes only that part.")
    return None
