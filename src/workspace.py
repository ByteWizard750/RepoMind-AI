"""The analysis workspace: a clone of the repository currently loaded in the
graph, kept on disk (with the analysis results in memory) so the lazily
loaded features — documentation, violation explanations, ADRs, historical
diagrams — can read source and git history after /analyze returns.

One analysis runs at a time. Every lazy request names the analysis_id it
belongs to; a stale id is rejected rather than served another repo's data.
A workspace replaced by a newer analysis is deleted once its last reader
finishes, so a long-running request never has files vanish under it.

The running analysis reports its stage (status()) and can be cancelled
(cancel()): the clone is killed at once, later stages stop at their next
checkpoint (check_cancelled()). Cloning is bounded by CLONE_TIMEOUT_SECONDS
and, for remote repositories, fetches only the history that is mined.
"""
import glob
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager

import preflight
import scope
from history import HISTORY_MAX_COMMITS

WORKSPACE_PREFIX = "repomind_ws_"
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}  # fail instead of prompting for credentials
CLONE_TIMEOUT_SECONDS = int(os.environ.get("CLONE_TIMEOUT_SECONDS", 600))
# One more than the mined commits, so mining can still tell history was cut off. 0 = full history.
CLONE_DEPTH = int(os.environ.get("CLONE_DEPTH", HISTORY_MAX_COMMITS + 1))
PROBE_TIMEOUT_SECONDS = 60


class AnalysisBusy(RuntimeError):
    pass


class StaleAnalysis(RuntimeError):
    pass


class CloneError(RuntimeError):
    pass


class AnalysisCancelled(RuntimeError):
    pass


class Workspace:
    def __init__(self, path: str, repo_url: str):
        self.id = uuid.uuid4().hex[:12]
        self.path = path
        self.repo_url = repo_url      # the repository itself (links, GitHub issues)
        self.ref = None               # branch from a folder URL
        self.subdir = ""              # folder from a folder URL
        self.scope = None             # scope.Scope, set by the analysis
        self.notices = []
        self.github = None            # preflight facts (size, languages) when available
        self.head_sha = None
        self.clone_seconds = 0.0
        self.results = {}
        self.readers = 0
        self.retired = False

    @property
    def key_url(self) -> str:
        """The cache identity: the repository, plus the scope when the
        analysis covers only part of it (a folder, or large-repo mode)."""
        signature = self.scope.signature() if self.scope is not None else ""
        return f"{self.repo_url}#scope-{signature}" if signature else self.repo_url


_state_lock = threading.Lock()
_analysis_lock = threading.Lock()
_current = None
_cancel = threading.Event()
_progress = {"running": False, "repo_url": None, "stage": None, "detail": "", "started": None, "cancelling": False}


# --------------------------------------------------------------------------
# Progress and cancellation of the running analysis
# --------------------------------------------------------------------------

def report(stage: str, detail: str = "") -> None:
    with _state_lock:
        _progress.update(stage=stage, detail=detail)


def check_cancelled() -> None:
    if _cancel.is_set():
        raise AnalysisCancelled("Analysis cancelled.")


def cancel() -> bool:
    """Asks the running analysis to stop. False when none is running."""
    with _state_lock:
        if not _progress["running"]:
            return False
        _progress["cancelling"] = True
    _cancel.set()
    return True


def status() -> dict:
    with _state_lock:
        out = dict(_progress)
    out["elapsed"] = round(time.time() - out.pop("started"), 1) if out["started"] else None
    return out


# --------------------------------------------------------------------------
# Disk housekeeping
# --------------------------------------------------------------------------

def _remove_readonly(func, path, _exc_info):
    # git marks files under .git/ read-only on Windows.
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_tree(path: str) -> None:
    for attempt in range(3):
        try:
            shutil.rmtree(path, onerror=_remove_readonly)
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.5 * (attempt + 1))  # antivirus/indexer briefly holding a file on Windows
    shutil.rmtree(path, ignore_errors=True)


STALE_AFTER_SECONDS = 24 * 3600
_SWEPT_PREFIXES = (WORKSPACE_PREFIX, "repomind_snap_", "repomind_probe_")


def sweep_stale() -> int:
    """Deletes workspaces and snapshot scratch dirs left behind by a crashed
    run. Only folders untouched for a day are removed: another RepoMind
    process (a second server, the tests) may be using a recent one."""
    removed = 0
    cutoff = time.time() - STALE_AFTER_SECONDS
    for prefix in _SWEPT_PREFIXES:
        for path in glob.glob(os.path.join(tempfile.gettempdir(), prefix + "*")):
            try:
                stale = os.path.isdir(path) and os.path.getmtime(path) < cutoff
            except OSError:
                continue
            if stale and (_current is None or path != _current.path):
                remove_tree(path)
                removed += 1
    return removed


# --------------------------------------------------------------------------
# Cloning
# --------------------------------------------------------------------------

def _kill_tree(proc) -> None:
    """git clone runs helpers (remote-https, index-pack); kill them all."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


_PROGRESS_SPLIT = re.compile(rb"[\r\n]+")


def run_git_streaming(args: list, timeout: float, on_line=None) -> tuple:
    """Runs git, feeding each stderr line (progress included) to on_line.
    Kills the whole process tree on timeout or cancellation.
    Returns (returncode, stderr lines)."""
    extra = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_GIT_ENV, **extra)
    lines = []

    def read():
        buffer = b""
        for chunk in iter(lambda: proc.stderr.read1(4096), b""):
            parts = _PROGRESS_SPLIT.split(buffer + chunk)
            buffer = parts.pop()
            for raw in parts:
                line = raw.decode("utf-8", errors="replace").strip()
                if line:
                    lines.append(line)
                    del lines[:-50]
                    if on_line:
                        on_line(line)
        if buffer.strip():
            lines.append(buffer.decode("utf-8", errors="replace").strip())

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    deadline = time.time() + timeout
    try:
        while proc.poll() is None:
            if _cancel.is_set():
                _kill_tree(proc)
                raise AnalysisCancelled("Analysis cancelled.")
            if time.time() > deadline:
                _kill_tree(proc)
                raise TimeoutError
            time.sleep(0.2)
    finally:
        reader.join(timeout=5)
    return proc.returncode, lines


def _progress_detail(line: str) -> str:
    # "Receiving objects:  45% (1234/2700), 12.30 MiB | 3.20 MiB/s" -> shown as-is, minus "remote: ".
    return re.sub(r"^remote:\s*", "", line)[:120]


def _clone(url: str, dest: str, ref: str = None) -> str:
    args = ["git", "clone", "--single-branch", "--no-tags", "--progress"]
    if ref:
        args += ["--branch", ref]
    if CLONE_DEPTH > 0 and re.match(r"^https?://", url, re.IGNORECASE):
        args.append(f"--depth={CLONE_DEPTH}")
    if os.environ.get("CLONE_FILTER"):
        args.append(f"--filter={os.environ['CLONE_FILTER']}")
    # "--" so a URL can never be parsed as a git option (e.g. --upload-pack=...).
    args += ["--", url, dest]
    last = {"line": ""}

    def on_line(line):
        last["line"] = line
        report("Cloning the repository", _progress_detail(line))

    try:
        code, lines = run_git_streaming(args, CLONE_TIMEOUT_SECONDS, on_line)
    except TimeoutError:
        minutes = CLONE_TIMEOUT_SECONDS / 60
        progress = f" (last progress: {_progress_detail(last['line'])})" if last["line"] else ""
        raise CloneError(f"Cloning didn't finish within {minutes:g} minute{'s' if minutes != 1 else ''}{progress}. "
                         "The repository is too large to analyze live; try a smaller repository.")
    if code != 0:
        errors = [ln for ln in lines if ln.lower().startswith(("fatal:", "error:"))] or lines
        raise CloneError(f"Couldn't clone {url}: {errors[-1] if errors else 'git clone failed'}. "
                         "Check the URL and that the repository is public.")
    head = subprocess.run(["git", "-C", dest, "rev-parse", "HEAD"], capture_output=True, text=True, env=_GIT_ENV)
    if head.returncode != 0:
        raise CloneError("The repository has no commits yet, so there is nothing to analyze.")
    return head.stdout.strip()


def probe_listing(url: str, ref: str = None):
    """The file paths at the branch tip, without downloading any file
    contents (a depth-1 clone of commits and folder trees only: kilobytes,
    even for a repository of gigabytes). None when it can't be done."""
    tmp = tempfile.mkdtemp(prefix="repomind_probe_")
    try:
        args = ["git", "clone", "--depth=1", "--filter=blob:none", "--no-checkout", "--single-branch",
                "--no-tags", "--quiet"] + (["--branch", ref] if ref else []) + ["--", url, tmp]
        try:
            code, _ = run_git_streaming(args, PROBE_TIMEOUT_SECONDS)
        except TimeoutError:
            return None
        if code != 0:
            return None
        out = subprocess.run(["git", "-C", tmp, "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                             capture_output=True, env=_GIT_ENV)
        if out.returncode != 0:
            return None
        return [path for path in out.stdout.decode("utf-8", errors="replace").split("\0") if path]
    finally:
        remove_tree(tmp)


_REMOTE_URL = re.compile(r"^https?://[^\s/]+/\S+$", re.IGNORECASE)


def validate_repo_url(url: str) -> None:
    """Only remote http(s) repositories: anything else could make the server
    clone its own filesystem. REPOMIND_ALLOW_LOCAL_REPOS=1 (tests, evaluation)
    additionally allows an existing local directory."""
    if _REMOTE_URL.match(url):
        return
    if os.environ.get("REPOMIND_ALLOW_LOCAL_REPOS") == "1" and os.path.isdir(url):
        return
    raise CloneError("Enter a public repository URL starting with https://, e.g. https://github.com/user/repo.")


def _prepare(ws, url: str) -> None:
    """Folder URL resolution and the GitHub pre-check, before cloning."""
    report("Checking the repository")
    try:
        target = preflight.resolve(url)
        ws.repo_url, ws.ref, ws.subdir = target["clone_url"], target["ref"], target["subdir"]
        ws.github = preflight.github_facts(ws.repo_url)
        if ws.github:
            notice = preflight.language_check(ws.github["languages"])
            if notice:
                ws.notices.append(notice)
    except preflight.PreflightError as exc:
        raise CloneError(str(exc))
    check_cancelled()
    if ws.github is None and _REMOTE_URL.match(ws.repo_url):
        # No GitHub API answer (rate limit, another host): list the files
        # instead, so a repository with nothing to analyze is rejected before
        # a clone that may take minutes. Inconclusive probes change nothing.
        report("Checking the repository", "listing its files")
        listing = probe_listing(ws.repo_url, ws.ref)
        if listing is not None:
            scope.check_listing(listing, ws.subdir)
        check_cancelled()


def _retire(ws) -> None:
    ws.retired = True
    if ws.readers == 0:
        remove_tree(ws.path)


@contextmanager
def new_analysis(repo_url: str):
    """Clones repo_url into a fresh workspace and yields it. The workspace
    becomes current only if the body completes; on failure it is deleted."""
    global _current
    validate_repo_url(repo_url)
    if not _analysis_lock.acquire(blocking=False):
        raise AnalysisBusy("Another analysis is already running. Wait for it to finish, or cancel it.")
    _cancel.clear()
    with _state_lock:
        _progress.update(running=True, repo_url=repo_url, stage="Starting", detail="", started=time.time(),
                         cancelling=False)
    try:
        with _state_lock:
            previous, _current = _current, None
            if previous is not None:
                _retire(previous)
        ws = Workspace(tempfile.mkdtemp(prefix=WORKSPACE_PREFIX), repo_url)
        try:
            _prepare(ws, repo_url)
            size = ws.github["size_mb"] if ws.github else None
            report("Cloning the repository", f"{size:,.0f} MB on GitHub" if size and size >= 50 else "")
            t0 = time.time()
            ws.head_sha = _clone(ws.repo_url, ws.path, ws.ref)
            ws.clone_seconds = round(time.time() - t0, 2)
            check_cancelled()
            yield ws
        except BaseException:
            remove_tree(ws.path)
            raise
        with _state_lock:
            _current = ws
    finally:
        with _state_lock:
            _progress.update(running=False, stage=None, detail="", started=None, cancelling=False)
        _cancel.clear()
        _analysis_lock.release()


@contextmanager
def use(analysis_id: str):
    """Yields the current workspace if analysis_id is still current."""
    with _state_lock:
        ws = _current
        if ws is None or ws.id != analysis_id:
            if _analysis_lock.locked():
                raise StaleAnalysis("A new analysis is running; this result is out of date.")
            raise StaleAnalysis("This analysis is no longer current. Run the analysis again.")
        ws.readers += 1
    try:
        yield ws
    finally:
        with _state_lock:
            ws.readers -= 1
            if ws.retired and ws.readers == 0:
                remove_tree(ws.path)


def is_current(analysis_id: str) -> bool:
    with _state_lock:
        return _current is not None and _current.id == analysis_id


def shutdown() -> None:
    global _current
    with _state_lock:
        if _current is not None:
            _retire(_current)
            _current = None
