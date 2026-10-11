"""What part of a repository an analysis covers.

- A small repository is analyzed whole, exactly as before.
- A folder URL (https://github.com/owner/repo/tree/<branch>/<folder>)
  limits the analysis to that folder.
- Above LARGE_REPO_FILES source files (large-repo mode), tests, examples,
  stories and other code that isn't part of the architecture are left out.
  If that is still more than MAX_SOURCE_FILES, whole folders are taken,
  largest first, until the cap (in a monorepo the folders are packages,
  e.g. packages/trpc).

Every choice is reported back (Scope.summary), nothing is dropped silently,
and the same commit always gets the same scope. A repository with no
supported source code is rejected with what it is written in instead.
"""
import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field

from parser.js_extractor import _SKIP_DIRS

SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx")
LARGE_REPO_FILES = int(os.environ.get("LARGE_REPO_FILES", 3000))
MAX_SOURCE_FILES = int(os.environ.get("MAX_SOURCE_FILES", 3000))
LARGE_REPO_SNAPSHOTS = int(os.environ.get("LARGE_REPO_SNAPSHOTS", 6))
SUPPORTED_LANGUAGES = "Python, JavaScript and TypeScript"

_NOISE_DIRS = {"test", "tests", "__tests__", "__mocks__", "mocks", "spec", "specs", "e2e", "playwright", "cypress",
               "fixtures", "__fixtures__", "example", "examples", "sample", "samples", "demo", "demos", "docs",
               "stories", "storybook", ".storybook", "benchmark", "benchmarks", "bench", "dist", "build", "out",
               "coverage", "vendor", "third_party", "generated", "__generated__", "migrations", "scripts"}
_NOISE_FILE = re.compile(r"([.-](test|spec|stories|story|e2e|bench)\.[cm]?[jt]sx?$|^test_.*\.py$|_test\.py$|"
                         r"^conftest\.py$|\.min\.js$|\.config\.[cm]?[jt]s$)", re.IGNORECASE)
# Folders whose children are separate packages; their groups go one level deeper.
_CONTAINERS = {"packages", "apps", "libs", "services", "modules", "plugins", "projects", "workspaces"}

_LANGUAGE_BY_EXT = {
    ".c": "C", ".h": "C/C++", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".java": "Java",
    ".kt": "Kotlin", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
    ".m": "Objective-C", ".scala": "Scala", ".dart": "Dart", ".lua": "Lua", ".r": "R", ".jl": "Julia",
    ".ipynb": "Jupyter notebooks", ".vue": "Vue", ".svelte": "Svelte", ".ex": "Elixir", ".hs": "Haskell",
    ".sol": "Solidity", ".sh": "shell scripts", ".md": "Markdown", ".html": "HTML", ".css": "CSS",
}


class UnsupportedRepo(ValueError):
    pass


def is_source(path: str) -> bool:
    return path.endswith(SOURCE_EXTENSIONS) and not path.endswith(".d.ts")


def is_noise(path: str) -> bool:
    parts = path.split("/")
    return any(p.lower() in _NOISE_DIRS for p in parts[:-1]) or bool(_NOISE_FILE.search(parts[-1]))


def _in_group(path: str, group: str) -> bool:
    """A group is a folder ("packages/trpc": everything under it) or the
    files directly inside one folder ("packages/*", "*" for the top)."""
    if group.endswith("*"):
        return path.rsplit("/", 1)[0] == group[:-2] if "/" in path else group == "*"
    return path.startswith(group + "/")


@dataclass
class Scope:
    subdir: str = ""            # repo-relative folder from a folder URL, "" for the whole repository
    large: bool = False         # large-repo mode
    skip_noise: bool = False
    groups: tuple = ()          # chosen folders; empty means all of them
    files_total: int = 0        # source files under subdir
    files_included: int = 0
    noise_skipped: int = 0
    groups_skipped: list = field(default_factory=list)   # [(group, files)], largest first

    @property
    def limited(self) -> bool:
        return bool(self.subdir or self.large)

    def includes(self, path: str) -> bool:
        if self.subdir and not path.startswith(self.subdir + "/"):
            return False
        if self.skip_noise and is_noise(path):
            return False
        return not self.groups or any(_in_group(path, g) for g in self.groups)

    def include_fn(self):
        """The parser filter: None for an unlimited scope."""
        return self.includes if self.limited else None

    def signature(self) -> str:
        if not self.limited:
            return ""
        raw = json.dumps([self.subdir, self.large, self.skip_noise, sorted(self.groups)])
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    def summary(self) -> dict:
        return {
            "mode": "large" if self.large else ("folder" if self.subdir else "full"),
            "subdir": self.subdir or None,
            "files_total": self.files_total,
            "files_included": self.files_included,
            "noise_skipped": self.noise_skipped,
            "groups": sorted(self.groups),
            "groups_skipped": [{"group": g, "files": n} for g, n in self.groups_skipped],
        }


def iter_source(repo_path: str, subdir: str = ""):
    """Repo-relative paths of supported source files, walked exactly like
    the parsers walk (same skipped folders)."""
    start = os.path.join(repo_path, *subdir.split("/")) if subdir else repo_path
    for root, dirs, files in os.walk(start):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), repo_path).replace(os.sep, "/")
            if is_source(rel):
                yield rel


def _initial_group(path: str, base_depth: int) -> str:
    dirs = path.split("/")[:-1]
    rel = dirs[base_depth:]
    if not rel:
        return "/".join(dirs + ["*"])
    depth = base_depth + (2 if rel[0].lower() in _CONTAINERS and len(rel) >= 2 else 1)
    return "/".join(dirs[:depth])


def _split(path: str, group: str) -> str:
    dirs = path.split("/")[:-1]
    depth = len(group.split("/")) + 1
    return "/".join(dirs[:depth]) if len(dirs) >= depth else group + "/*"


def pick_groups(paths: list, cap: int, base: str = "") -> tuple:
    """Folders to analyze when there are more than `cap` files: groups are
    split until each fits, then taken largest first while they fit.
    Returns (chosen groups, skipped [(group, files)])."""
    base_depth = len(base.split("/")) if base else 0
    assign = {p: _initial_group(p, base_depth) for p in paths}
    while True:
        counts = Counter(assign.values())
        too_big = {g for g, n in counts.items() if n > cap and not g.endswith("*")}
        if not too_big:
            break
        for p, g in assign.items():
            if g in too_big:
                assign[p] = _split(p, g)
    counts = Counter(assign.values())
    chosen, skipped, total = [], [], 0
    for g, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        if total + n <= cap:
            chosen.append(g)
            total += n
        else:
            skipped.append((g, n))
    if not chosen and skipped:          # one folder with more files than the cap: take it anyway
        chosen.append(skipped.pop(0)[0])
    return tuple(chosen), skipped


def _visible(path: str) -> bool:
    """Not inside a folder the parsers skip (node_modules, .git, dot folders)."""
    return not any(d in _SKIP_DIRS or d.startswith(".") for d in path.split("/")[:-1])


def describe_languages(paths) -> str:
    """'C++ (412 .cpp files, 80 .h files)' for the rejection message."""
    counts = Counter()
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if _visible(path) and ext in _LANGUAGE_BY_EXT and ext not in (".md", ".html", ".css"):
            counts[ext] += 1
    if not counts:
        return ""
    top = counts.most_common(3)
    language = _LANGUAGE_BY_EXT[top[0][0]]
    return f"{language} ({', '.join(f'{n} {ext} file' + ('s' if n != 1 else '') for ext, n in top)})"


def check_listing(paths: list, subdir: str = "") -> int:
    """Raises UnsupportedRepo when the repository's file list (e.g. from a
    contents-free probe clone, before the real clone) has no supported
    source code under subdir; else returns the source file count."""
    under = [p for p in paths if not subdir or p.startswith(subdir + "/")]
    if subdir and not under:
        raise UnsupportedRepo(f"The folder {subdir} doesn't exist in this branch of the repository.")
    sources = [p for p in under if is_source(p) and _visible(p)]
    if not sources:
        _reject(under, subdir)
    return len(sources)


def _reject(paths, subdir: str):
    where = f"the folder {subdir}" if subdir else "this repository"
    written_in = describe_languages(paths)
    raise UnsupportedRepo(
        f"RepoMind found no Python, JavaScript or TypeScript files in {where}"
        + (f" — it is written in {written_in}" if written_in else "")
        + f". RepoMind currently analyzes {SUPPORTED_LANGUAGES} code.")


def _all_files(repo_path: str, subdir: str = ""):
    start = os.path.join(repo_path, *subdir.split("/")) if subdir else repo_path
    for root, dirs, files in os.walk(start):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            yield os.path.relpath(os.path.join(root, name), repo_path).replace(os.sep, "/")


def choose(repo_path: str, subdir: str = "", large_files: int = None, cap: int = None) -> Scope:
    large_files = LARGE_REPO_FILES if large_files is None else large_files
    cap = MAX_SOURCE_FILES if cap is None else cap
    if subdir and not os.path.isdir(os.path.join(repo_path, *subdir.split("/"))):
        raise UnsupportedRepo(f"The folder {subdir} doesn't exist in this branch of the repository.")
    paths = sorted(iter_source(repo_path, subdir))
    if not paths:
        _reject(_all_files(repo_path, subdir), subdir)
    scope = Scope(subdir=subdir, files_total=len(paths), files_included=len(paths))
    if len(paths) <= large_files:
        return scope

    scope.large = True
    kept = [p for p in paths if not is_noise(p)]
    if kept:                              # a repository of nothing but tests keeps them
        scope.skip_noise = True
        scope.noise_skipped = len(paths) - len(kept)
    else:
        kept = paths
    if len(kept) > cap:
        scope.groups, scope.groups_skipped = pick_groups(kept, cap, subdir)
        kept = [p for p in kept if any(_in_group(p, g) for g in scope.groups)]
    scope.files_included = len(kept)
    return scope
