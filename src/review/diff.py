"""The changes under review: a commit range, its diff parsed per file with
new-side line numbers, and that diff split into model-sized batches.

Validation of AI findings depends on this module: a finding is only kept
if it points at a line this diff added (see agents/review_graph.py).
"""
import os
import re
import subprocess

from history import git
from layers import is_ignored
from snapshots import SOURCE_EXTENSIONS, _SKIP_DIRS

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's well-known empty tree object
DEFAULT_COMMITS = int(os.environ.get("REVIEW_DEFAULT_COMMITS", "5"))
MAX_FILES = int(os.environ.get("REVIEW_MAX_FILES", "12"))
# Model calls per review: bounds the cost of one big push.
MAX_BATCHES = int(os.environ.get("REVIEW_MAX_BATCHES", "8"))
CONTEXT_LINES = 10
MAX_FILE_DIFF_CHARS = 200_000   # a diff this large is generated or vendored code
BATCH_CHARS = 8_000             # ~2.3k tokens: with the prompt and a 4.5k answer budget, fits Groq's 8k tokens/minute

_GENERATED_DIRS = {"dist", "build", "vendor", "third_party", "coverage", "migrations"}
_GENERATED_SUFFIXES = (".min.js", ".bundle.js", ".d.ts", "_pb2.py")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


# ------------------------------------------------------------------ range

def _rev_exists(repo: str, rev: str) -> bool:
    try:
        git(repo, "cat-file", "-e", f"{rev}^{{commit}}")
        return True
    except subprocess.CalledProcessError:
        return False


def resolve_range(repo: str, head: str = "HEAD", base: str = None, commits: int = None) -> dict:
    """{"base", "head", "empty_base", "fallback"}. An explicit base that is
    missing, all zeros (a branch's first push) or not an ancestor of head
    (a force push) falls back to the last `commits` commits."""
    head_sha = git(repo, "rev-parse", f"{head}^{{commit}}").strip()
    fallback = None
    if base and set(base) != {"0"} and _rev_exists(repo, base):
        base_sha = git(repo, "rev-parse", f"{base}^{{commit}}").strip()
        try:
            git(repo, "merge-base", "--is-ancestor", base_sha, head_sha)
            return {"base": base_sha, "head": head_sha, "empty_base": False, "fallback": None}
        except subprocess.CalledProcessError:
            fallback = f"{base[:7]} is not an ancestor of HEAD (force push?)"
    elif base and set(base) != {"0"}:
        fallback = f"base {base[:12]} is not a commit in this history"
    n = max(1, commits or DEFAULT_COMMITS)
    chain = git(repo, "rev-list", "--first-parent", f"--max-count={n + 1}", head_sha).split()
    if len(chain) > n:
        return {"base": chain[n], "head": head_sha, "empty_base": False, "fallback": fallback}
    return {"base": EMPTY_TREE, "head": head_sha, "empty_base": True, "fallback": fallback}


def commits_in_range(repo: str, base: str, head: str) -> list:
    """Oldest first: {sha, short, author, date, subject, files}."""
    span = head if base == EMPTY_TREE else f"{base}..{head}"
    raw = git(repo, "log", "--no-merges", "--reverse", "--name-only", "--format=%x1e%H%x1f%an%x1f%aI%x1f%s", span)
    out = []
    for block in raw.split("\x1e"):
        if not block.strip():
            continue
        header, _, names = block.partition("\n")
        sha, author, date, subject = (header.split("\x1f") + ["", "", "", ""])[:4]
        out.append({"sha": sha, "short": sha[:7], "author": author, "date": date, "subject": subject,
                    "files": [n for n in names.splitlines() if n.strip()]})
    return out


# ------------------------------------------------------------------ diff

def _reviewable(path: str) -> str:
    """'' when the file should be reviewed, else the reason it isn't."""
    parts = path.split("/")
    if not path.endswith(SOURCE_EXTENSIONS):
        return "not source code"
    if path.endswith(_GENERATED_SUFFIXES) or any(p in _GENERATED_DIRS for p in parts[:-1]):
        return "generated or vendored"
    if any(p in _SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
        return "skipped folder"
    return ""


def _unquote(path: str) -> str:
    """git quotes paths containing quotes, backslashes or control characters
    (non-ASCII stays as-is under core.quotepath=off)."""
    if len(path) >= 2 and path[0] == path[-1] == '"':
        path = re.sub(r'\\(["\\tn])', lambda m: {"t": "\t", "n": "\n"}.get(m.group(1), m.group(1)), path[1:-1])
    return path


def parse_diff(text: str) -> list:
    """Unified diff -> [{"path", "old_path", "status", "hunks": [{"header",
    "lines": [(kind, new_no, text)]}], "added": [new line numbers]}]. kind is
    "+" (added), " " (context) or "-" (removed; new_no is None)."""
    files, current, hunk, new_no = [], None, None, 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = {"path": None, "old_path": None, "status": "modified", "hunks": [], "added": [], "binary": False}
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif hunk is None and line.startswith("new file mode"):
            current["status"] = "added"
        elif hunk is None and line.startswith("deleted file mode"):
            current["status"] = "deleted"
        elif hunk is None and line.startswith("rename from "):
            current["old_path"] = _unquote(line[len("rename from "):])
            current["status"] = "renamed"
        elif hunk is None and line.startswith("rename to "):
            current["path"] = _unquote(line[len("rename to "):])
        elif hunk is None and line.startswith("Binary files "):
            current["binary"] = True
        elif hunk is None and line.startswith("--- "):
            old = _unquote(line[4:])
            if old != "/dev/null" and current["old_path"] is None:
                current["old_path"] = old[2:] if old.startswith("a/") else old
        elif hunk is None and line.startswith("+++ "):
            new = _unquote(line[4:])
            if new != "/dev/null":
                current["path"] = new[2:] if new.startswith("b/") else new
        elif line.startswith("@@"):
            m = _HUNK.match(line)
            if not m:
                continue
            new_no = int(m.group(1))
            hunk = {"header": line, "lines": []}
            current["hunks"].append(hunk)
        elif hunk is not None:
            if line.startswith("+"):
                hunk["lines"].append(("+", new_no, line[1:]))
                current["added"].append(new_no)
                new_no += 1
            elif line.startswith("-"):
                hunk["lines"].append(("-", None, line[1:]))
            elif line.startswith(" ") or line == "":
                hunk["lines"].append((" ", new_no, line[1:]))
                new_no += 1
            # "\ No newline at end of file" carries no line
    for f in files:
        if f["path"] is None:
            f["path"] = f["old_path"]
    return files


def collect(repo: str, base: str, head: str, ignore=None, max_files: int = MAX_FILES, include=None) -> dict:
    """{"files": reviewed file diffs (most changed first, tests last),
    "skipped": [{"path", "reason"}]}. include limits the files to the
    analysis scope."""
    raw = git(repo, "diff", "-M", f"-U{CONTEXT_LINES}", "--no-color", "--no-ext-diff", base, head)
    reviewed, skipped = [], []
    for f in parse_diff(raw):
        reason = ("deleted" if f["status"] == "deleted" else "binary" if f["binary"]
                  else "no added lines" if not f["added"] else _reviewable(f["path"]))
        if not reason and include is not None and not include(f["path"]):
            reason = "outside the analyzed part of the repository"
        if not reason and sum(len(t) for h in f["hunks"] for _, _, t in h["lines"]) > MAX_FILE_DIFF_CHARS:
            reason = "diff too large (likely generated)"
        if reason:
            skipped.append({"path": f["path"], "reason": reason})
            continue
        f["is_test"] = is_ignored(f["path"], ignore or [])
        reviewed.append(f)
    reviewed.sort(key=lambda f: (f["is_test"], -len(f["added"]), f["path"]))
    for f in reviewed[max_files:]:
        skipped.append({"path": f["path"], "reason": f"over the {max_files}-file limit"})
    return {"files": reviewed[:max_files], "skipped": skipped}


# ------------------------------------------------------------------ batches for the model

def render_hunk(hunk: dict) -> str:
    """Each line prefixed with its new-side number; removed lines get none."""
    out = [hunk["header"]]
    for kind, no, text in hunk["lines"]:
        out.append(f"{'':>5} - {text}" if kind == "-" else f"{no:>5} {kind} {text}")
    return "\n".join(out)


def batches(files: list, budget: int = BATCH_CHARS) -> list:
    """Groups rendered file diffs into requests of at most ~budget chars. A
    file bigger than the budget is split across requests by hunks; each
    part keeps the file's name."""
    parts = []
    for f in files:
        chunk = []
        size = 0
        for h in f["hunks"]:
            text = render_hunk(h)
            if chunk and size + len(text) > budget:
                parts.append((f["path"], "\n".join(chunk)))
                chunk, size = [], 0
            chunk.append(text[:budget])
            size += len(text)
        if chunk:
            parts.append((f["path"], "\n".join(chunk)))
    out, current, size = [], [], 0
    for path, text in parts:
        if current and size + len(text) > budget:
            out.append(current)
            current, size = [], 0
        current.append({"path": path, "diff": text})
        size += len(text)
    if current:
        out.append(current)
    return out


def within_budget(files: list, max_batches: int = MAX_BATCHES, budget: int = BATCH_CHARS) -> tuple:
    """(batches, files kept, files dropped): the files (in priority order)
    whose diffs fit in max_batches requests."""
    kept, dropped = [], []
    for f in files:
        if len(batches(kept + [f], budget)) <= max_batches:
            kept.append(f)
        else:
            dropped.append(f)
    return batches(kept, budget), kept, dropped


def file_at(repo: str, rev: str, path: str):
    """File text at a revision, or None if it doesn't exist there."""
    try:
        return git(repo, "show", f"{rev}:{path}")
    except subprocess.CalledProcessError:
        return None
