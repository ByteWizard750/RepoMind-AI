"""Pull request and issue text as ADR evidence.

Commit messages rarely say why; the pull request a commit came from, or the
issue it fixes, often does. For the commits chosen as evidence, this finds
the GitHub pull requests and issues they belong to and fetches their title
and description:

- from the commit message: squash merges end their subject with "(#123)",
  and messages reference issues ("Fixes #45");
- from the merge commits (which history mining leaves out): the commits a
  "Merge pull request #123" merge brought in belong to #123 — read with git,
  only for merges near the evidence;
- the text comes from the GitHub API (one request per pull request or issue,
  `GITHUB_TOKEN` when set), cached on disk, capped per analysis. Rate limits,
  network errors and non-GitHub repositories just mean no text; the lookup
  reports whether it was complete so incomplete records aren't cached.

The text is repository content like any commit message: it reaches the model
as data, and a description that mentions an excluded path (the ADR folders the
evaluation hides) is withheld so it can't leak the answer.
"""
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

import httpx

import cache
from history import git
from review.github_issues import API_URL, repo_slug

ENABLED = os.environ.get("ADR_PR_LOOKUP", "1").strip().lower() not in ("0", "false", "no")
MAX_FETCH_WITH_TOKEN = int(os.environ.get("ADR_PR_MAX_FETCH", "60"))
MAX_FETCH_ANONYMOUS = 12            # GitHub allows 60 unauthenticated requests an hour, shared with the pre-clone check
TIMEOUT_SECONDS = 8
CACHE_DAYS = 30
BODY_CHARS = 1200
REFS_PER_COMMIT = 3
MAX_MERGES = 2000
COMMITS_PER_MERGE = 300
MERGE_WINDOW = timedelta(days=60)   # a pull request is merged some time after its commits

_SQUASH = re.compile(r"\(#(\d{1,7})\)\s*$")
_MERGE = re.compile(r"^Merge pull request #(\d{1,7})\b")
_REF = re.compile(r"(?<![\w&/])#(\d{1,7})\b")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_BLANK_LINES = re.compile(r"\n\s*\n+")


def message_refs(commit: dict) -> list:
    """Pull request / issue numbers a commit message points at, most specific first."""
    refs = []
    for pattern, text in ((_SQUASH, commit.get("subject", "")), (_MERGE, commit.get("subject", ""))):
        m = pattern.search(text)
        if m:
            refs.append(int(m.group(1)))
    for m in _REF.finditer(f"{commit.get('subject', '')}\n{commit.get('body', '')}"):
        refs.append(int(m.group(1)))
    out = []
    for n in refs:
        if n not in out:
            out.append(n)
    return out[:REFS_PER_COMMIT]


def clean_body(body: str) -> str:
    text = _IMAGE.sub("", _HTML_COMMENT.sub("", body or ""))
    text = _BLANK_LINES.sub("\n", text).strip()
    return text if len(text) <= BODY_CHARS else text[:BODY_CHARS].rstrip() + "…"


def _parse_date(value: str):
    try:
        # git's %cI writes UTC as "Z", which fromisoformat accepts only from Python 3.11
        return datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (TypeError, ValueError, AttributeError):
        return None


class PullRequestSource:
    """Finds and fetches the pull requests / issues behind commits. Thread-safe:
    the ADRs of one analysis are reconstructed in parallel and share one."""

    def __init__(self, repo_url: str, repo_path: str, token: str = None, transport=None, exclude_paths=(),
                 max_fetch: int = None):
        self.slug = repo_slug(repo_url) if ENABLED else None
        self.repo_path = repo_path
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "").strip()
        self.transport = transport
        self.exclude_paths = [p.rstrip("/*") for p in exclude_paths if p.rstrip("/*")]
        self.max_fetch = max_fetch if max_fetch is not None else (
            MAX_FETCH_WITH_TOKEN if self.token else MAX_FETCH_ANONYMOUS)
        self._lock = threading.Lock()
        self._memo = {}               # number -> record or None (missing / withheld)
        self._merges = None           # [(date, first_parent, second_parent, number)], first-parent history
        self._expanded = set()
        self._pr_of = {}              # commit sha -> pull request number (from merge commits)
        self.fetched = self.from_cache = self.skipped = self.withheld = 0
        self.blocked = None           # why fetching stopped: "rate limit" / "network" / an HTTP status

    @property
    def available(self) -> bool:
        return self.slug is not None

    # ---------------------------------------------------------------- commit -> numbers

    def _load_merges(self):
        if self._merges is not None:
            return
        self._merges = []
        try:
            raw = git(self.repo_path, "log", "--merges", "--first-parent", "-n", str(MAX_MERGES),
                      "--format=%H%x1f%P%x1f%cI%x1f%s")
        except Exception:
            return
        for line in raw.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 4:
                continue
            sha, parents, date, subject = parts
            m = _MERGE.match(subject)
            parents = parents.split()
            if m and len(parents) == 2 and _parse_date(date):
                self._merges.append((_parse_date(date), parents[0], parents[1], int(m.group(1))))

    def _map_merges_near(self, commits: list):
        """Expands the merges that could have brought these commits in."""
        dates = [d for d in (_parse_date(c.get("date")) for c in commits) if d]
        if not dates:
            return
        self._load_merges()
        start, end = min(dates) - timedelta(days=1), max(dates) + MERGE_WINDOW
        for date, first, second, number in self._merges:
            if not (start <= date <= end) or number in self._expanded:
                continue
            self._expanded.add(number)
            try:
                shas = git(self.repo_path, "rev-list", "--no-merges", f"--max-count={COMMITS_PER_MERGE}",
                           f"{first}..{second}").split()
            except Exception:
                continue                     # a parent outside a shallow clone
            for sha in shas:
                self._pr_of.setdefault(sha, number)

    def refs(self, commit: dict) -> list:
        """Pull request first (from its merge commit), then the numbers in the message."""
        out = []
        number = self._pr_of.get(commit["hash"])
        if number:
            out.append(number)
        for n in message_refs(commit):
            if n not in out:
                out.append(n)
        return out[:REFS_PER_COMMIT]

    # ---------------------------------------------------------------- number -> text

    def _cache_path(self, number: int) -> str:
        return os.path.join(cache.CACHE_DIR, "github", self.slug.replace("/", "__"), f"{number}.json")

    def _from_disk(self, number: int):
        path = self._cache_path(number)
        try:
            if time.time() - os.path.getmtime(path) > CACHE_DAYS * 86_400:
                return None
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def _to_disk(self, number: int, record: dict):
        path = self._cache_path(number)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f)
        except OSError:
            pass

    def _request(self, number: int):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "repomind"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with httpx.Client(base_url=API_URL, headers=headers, timeout=TIMEOUT_SECONDS,
                              transport=self.transport) as client:
                return client.get(f"/repos/{self.slug}/issues/{number}")
        except httpx.HTTPError:
            self.blocked = "network"
            return None

    def fetch(self, number: int):
        """{number, kind, title, body, url, state} for a pull request or issue,
        or None (doesn't exist, withheld, or couldn't be fetched)."""
        with self._lock:
            if number in self._memo:
                return self._memo[number]
            record = self._from_disk(number)
            if record is not None:
                self.from_cache += 1
            elif self.blocked or self.fetched >= self.max_fetch:
                self.skipped += 1
                return None
            else:
                self.fetched += 1
                response = self._request(number)
                if response is None:
                    return None
                if response.status_code in (404, 410):
                    record = {"missing": True}
                elif response.status_code != 200:
                    rate_limited = response.status_code == 429 or (
                        response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0")
                    self.blocked = "rate limit" if rate_limited else f"HTTP {response.status_code}"
                    return None
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        self.blocked = "bad response"
                        return None
                    record = {"number": number, "kind": "pull request" if data.get("pull_request") else "issue",
                              "title": (data.get("title") or "").strip(), "body": clean_body(data.get("body")),
                              "url": data.get("html_url") or "", "state": data.get("state") or "",
                              "merged": bool((data.get("pull_request") or {}).get("merged_at"))}
                self._to_disk(number, record)
            if record.get("missing"):
                record = None
            elif any(p in f"{record['title']}\n{record['body']}" for p in self.exclude_paths):
                self.withheld += 1
                record = None
            self._memo[number] = record
            return record

    # ---------------------------------------------------------------- for the ADR agent

    def attach(self, commits: list) -> tuple:
        """(sha -> [records] for the commits that have pull request / issue
        text, complete). Not complete when a referenced number couldn't be
        fetched (cap, rate limit, network) — as opposed to not existing."""
        if not self.available or not commits:
            return {}, True
        with self._lock:
            self._map_merges_near(commits)
        out, complete = {}, True
        for c in commits:
            records = []
            for n in self.refs(c):
                record = self.fetch(n)
                if record:
                    records.append(record)
                elif n not in self._memo:
                    complete = False
            if records:
                out[c["hash"]] = records
        return out, complete

    def status(self) -> dict:
        complete = self.blocked is None and self.skipped == 0
        return {"source": f"github.com/{self.slug}" if self.slug else None, "complete": complete or not self.slug,
                "fetched": self.fetched, "from_cache": self.from_cache, "skipped": self.skipped,
                "withheld": self.withheld, "stopped": self.blocked, "token": bool(self.token)}
