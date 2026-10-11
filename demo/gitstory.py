"""Builds a git repository commit by commit from a scripted story.

Each step writes, deletes or renames files and commits them with a fixed
author and date, so the history (and everything RepoMind derives from it:
snapshots, drift, decisions, contributors) is the same on every build.
"""
import os
import shutil
import stat
import subprocess

MARKER = ".repomind-demo"   # only folders carrying this file are ever deleted by a rebuild


def _git(repo, *args, env=None):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def _force_remove(func, path, _exc):
    os.chmod(path, stat.S_IWRITE)
    func(path)


def fresh_repo(path: str) -> None:
    """An empty repository at path. An existing folder is replaced only if a
    previous build created it (it carries MARKER); anything else is refused."""
    if os.path.exists(path):
        if not os.path.exists(os.path.join(path, MARKER)):
            raise SystemExit(f"{path} exists and wasn't created by this script; refusing to delete it.")
        shutil.rmtree(path, onerror=_force_remove)
    os.makedirs(path)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "core.autocrlf", "false")
    with open(os.path.join(path, MARKER), "w", encoding="utf-8") as f:
        f.write("Built by RepoMind's demo/build_demo_repos.py; a rebuild deletes and recreates this folder.\n")
    with open(os.path.join(path, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
        f.write(MARKER + "\n")


def write(repo: str, files: dict) -> None:
    for rel, text in files.items():
        target = os.path.join(repo, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


def commit(repo: str, when: str, author: tuple, message: str, files: dict = None, delete=(), rename=None) -> str:
    """when: ISO date ("2026-01-05T10:12:00+05:30"); author: (name, email)."""
    for old, new in (rename or {}).items():
        os.makedirs(os.path.dirname(os.path.join(repo, *new.split("/"))), exist_ok=True)
        _git(repo, "mv", old, new)
    for rel in delete:
        _git(repo, "rm", "-q", rel)
    write(repo, files or {})
    _git(repo, "add", "-A")
    name, email = author
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_AUTHOR_DATE": when,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email, "GIT_COMMITTER_DATE": when}
    _git(repo, "commit", "-q", "-m", message, env=env)
    return _git(repo, "rev-parse", "--short", "HEAD")


def play(repo: str, story: list) -> int:
    """story: [{"when", "author", "message", "files"?, "delete"?, "rename"?}, ...]."""
    for step in story:
        commit(repo, step["when"], step["author"], step["message"], step.get("files"), step.get("delete", ()),
               step.get("rename"))
    return len(story)
