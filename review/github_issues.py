"""Raising review findings as GitHub issues.

Safety rules, enforced here rather than left to callers:
  - Issues are filed only on repositories the token can push to or triage
    (or, inside GitHub Actions, the workflow's own repository), so reviewing
    someone else's public repo can never file issues on it.
  - Every issue carries a fingerprint marker. A finding whose fingerprint
    already has an issue — open, or closed by anyone — is never raised again,
    and closed issues are never reopened.
  - At most REVIEW_MAX_ISSUES issues per run, only at or above
    REVIEW_MIN_SEVERITY.
  - Open RepoMind issues whose problem is verifiably gone at head are
    commented on and closed (REVIEW_CLOSE_RESOLVED=0 turns this off).
  - AI-written text has @mentions neutralized; the token never appears in
    any output or error.
  - Anything that looks like a credential (long mixed letter/digit string
    literals, well-known key prefixes) is masked before it reaches an issue,
    so a "hard-coded secret" finding doesn't republish the secret.
"""
import base64
import json
import os
import re

import httpx

API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
LABEL = "repomind-review"
LABEL_COLOR = "5319e7"
MAX_ISSUES = int(os.environ.get("REVIEW_MAX_ISSUES", "10"))
MIN_SEVERITY = os.environ.get("REVIEW_MIN_SEVERITY", "medium").strip().lower()
MAX_EXISTING = 500
SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}

_KNOWN_KEY = re.compile(r"\b(AKIA|ASIA|ghp_|gho_|ghs_|github_pat_|sk_live_|sk_test_|rk_live_|xox[abpr]-|AIza|glpat-)"
                       r"([A-Za-z0-9_\-]{6,})")
_STRING_LITERAL = re.compile(r"""(["'`])([^"'`\s]{16,})\1""")
_META = re.compile(r"<!-- repomind:meta=([A-Za-z0-9+/=]+) -->")
_SLUG = re.compile(r"^(?:https?://(?:www\.)?github\.com/|git@github\.com:)([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)"
                   r"(?:\.git)?/?(?:[#?].*)?$")


class GitHubError(RuntimeError):
    pass


def repo_slug(url: str):
    """"owner/name" for a github.com repository URL, else None."""
    m = _SLUG.match((url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def close_resolved_enabled() -> bool:
    return os.environ.get("REVIEW_CLOSE_RESOLVED", "1").strip() not in ("0", "false", "no")


class Client:
    def __init__(self, token: str, transport=None):
        if not token:
            raise GitHubError("No GitHub token configured (set GITHUB_TOKEN).")
        self._http = httpx.Client(base_url=API_URL, timeout=20, transport=transport, headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "repomind-review"})

    def request(self, method: str, path: str, **kwargs):
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError(f"GitHub request failed: {type(exc).__name__}") from None
        if response.status_code >= 400:
            try:
                message = response.json().get("message", "")
            except ValueError:
                message = response.text[:200]
            raise GitHubError(f"GitHub {method} {path.split('?')[0]} returned {response.status_code}: {message}")
        return response.json() if response.content else {}

    def close(self):
        self._http.close()


# ------------------------------------------------------------------ access and existing issues

def access(client: Client, slug: str) -> dict:
    """{"ok", "reason", "html_url"}. Requires push/triage/maintain/admin; a
    GitHub Actions token is accepted for its own repository only."""
    try:
        repo = client.request("GET", f"/repos/{slug}")
    except GitHubError as exc:
        return {"ok": False, "reason": f"Can't read {slug} with this token ({exc}).", "html_url": None}
    if repo.get("has_issues") is False:
        return {"ok": False, "reason": f"Issues are disabled on {slug}.", "html_url": repo.get("html_url")}
    perms = repo.get("permissions")
    in_own_workflow = os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REPOSITORY") == slug
    if perms is None:
        ok = in_own_workflow
    else:
        ok = any(perms.get(p) for p in ("admin", "maintain", "push", "triage")) or in_own_workflow
    reason = "" if ok else (f"The token can't manage {slug}: RepoMind only files issues on repositories you "
                            "maintain (push or triage access).")
    return {"ok": ok, "reason": reason, "html_url": repo.get("html_url")}


def decode_meta(body: str):
    m = _META.search(body or "")
    if not m:
        return None
    try:
        return json.loads(base64.b64decode(m.group(1)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def existing(client: Client, slug: str) -> list:
    """RepoMind-labelled issues (open and closed) carrying a fingerprint."""
    out, page = [], 1
    while len(out) < MAX_EXISTING:
        items = client.request("GET", f"/repos/{slug}/issues",
                               params={"labels": LABEL, "state": "all", "per_page": 100, "page": page})
        if not items:
            break
        for issue in items:
            if "pull_request" in issue:
                continue
            meta = decode_meta(issue.get("body"))
            if meta and meta.get("fp"):
                out.append({"number": issue["number"], "state": issue["state"], "title": issue["title"],
                            "url": issue["html_url"], "meta": meta})
        if len(items) < 100:
            break
        page += 1
    return out


# ------------------------------------------------------------------ plan

def plan(findings: list, existing_issues: list, still_present=None, min_severity: str = None,
         max_issues: int = None, selected=None) -> dict:
    """What a run would do, without doing it.

    findings: review findings, best first. selected: optional fingerprints
    to limit creation to (the one-click raise). still_present(meta) ->
    True / False / None (unknown) decides whether an open issue whose
    finding is absent from this review is verifiably resolved.

    Returns {"items": [{fingerprint, action, reason, issue}], "resolve":
    [{number, url, title, reason}], "creates": n}. action is "create" or
    "skip"."""
    threshold = SEVERITY_ORDER.get((min_severity or MIN_SEVERITY), 2)
    cap = MAX_ISSUES if max_issues is None else max_issues
    by_fp = {}
    for issue in existing_issues:
        by_fp.setdefault(issue["meta"]["fp"], issue)
    items, creates = [], 0
    for f in findings:
        fp = f["fingerprint"]
        issue = by_fp.get(fp)
        if issue and issue["state"] == "open":
            items.append({"fingerprint": fp, "action": "skip", "reason": f"already open as #{issue['number']}",
                          "issue": issue})
        elif issue:
            items.append({"fingerprint": fp, "action": "skip", "reason": f"closed as #{issue['number']}; not re-raised",
                          "issue": issue})
        elif SEVERITY_ORDER[f["severity"]] < threshold:
            items.append({"fingerprint": fp, "action": "skip", "reason": f"below the {min_severity or MIN_SEVERITY} threshold",
                          "issue": None})
        elif selected is not None and fp not in selected:
            items.append({"fingerprint": fp, "action": "skip", "reason": "not selected", "issue": None})
        elif creates >= cap:
            items.append({"fingerprint": fp, "action": "skip", "reason": f"over the {cap}-issue limit for one run",
                          "issue": None})
        else:
            creates += 1
            items.append({"fingerprint": fp, "action": "create", "reason": "", "issue": None})

    current = {f["fingerprint"] for f in findings}
    resolve = []
    if still_present is not None and close_resolved_enabled():
        for issue in existing_issues:
            if issue["state"] != "open" or issue["meta"]["fp"] in current:
                continue
            present = still_present(issue["meta"])
            if present is False:
                what = ("the rule violation no longer exists" if issue["meta"].get("kind") == "architecture"
                        else "the flagged code is no longer in the file")
                resolve.append({"number": issue["number"], "url": issue["url"], "title": issue["title"],
                                "reason": what})
    return {"items": items, "resolve": resolve, "creates": creates}


# ------------------------------------------------------------------ rendering

def mask_secrets(text: str) -> str:
    """Masks credential-like values: well-known key prefixes anywhere, and
    string literals of 16+ characters mixing letters and digits. The same
    function runs over file text when checking whether a finding is still
    present, so masked quotes keep matching."""
    text = _KNOWN_KEY.sub(lambda m: m.group(1) + "****", text or "")

    def literal(m):
        value = m.group(2)
        if re.search(r"[A-Za-z]", value) and re.search(r"\d", value) and "/" not in value and "." not in value:
            return f"{m.group(1)}{value[:4]}****{m.group(1)}"
        return m.group(0)
    return _STRING_LITERAL.sub(literal, text)


def _safe(text: str, limit: int = 1500) -> str:
    """AI or repository text going into an issue: no @mentions, no comment
    terminators, bounded length."""
    text = mask_secrets(text).replace("@", "@​").replace("-->", "-- >")
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _fence(code: str) -> str:
    return "```\n" + code.replace("```", "`​``") + "\n```"


def render_issue(finding: dict, slug: str, rng: dict) -> tuple:
    sev = finding["severity"].capitalize()
    title = f"[RepoMind] {sev} · {finding['category']}: {_safe(finding['title'], 90)}"[:120]
    head = rng["head"]
    location = finding["file"] + (f":{finding['line']}" if finding.get("line") else "")
    link = f"https://github.com/{slug}/blob/{head}/{finding['file']}" + (f"#L{finding['line']}" if finding.get("line") else "")
    lines = [f"**{sev} {finding['category']} finding** in [`{location}`]({link})", ""]
    if finding.get("quote"):
        lines += [_fence(_safe(finding["quote"], 400)), ""]
    lines += [_safe(finding.get("explanation", "")), ""]
    if finding.get("suggestion"):
        lines += ["**Suggested fix:** " + _safe(finding["suggestion"]), ""]
    if finding.get("edges"):
        lines += ["**Dependencies that break the rule:**", ""]
        lines += [f"- `{e['caller']}` → `{e['callee']}`" for e in finding["edges"][:15]]
        if len(finding["edges"]) > 15:
            lines.append(f"- … and {len(finding['edges']) - 15} more")
        lines.append("")
    if finding.get("commits"):
        lines += ["**Changed in:** " + ", ".join(f"[{c}](https://github.com/{slug}/commit/{c})"
                                                 for c in finding["commits"][-5:]), ""]
    origin = ("Detected deterministically by the architecture rule engine (confidence 1.0)."
              if finding["kind"] == "architecture"
              else f"Found by the AI code review and checked against the changed lines (confidence {finding['confidence']}).")
    base = rng.get("base_short") or rng["base"][:7]
    meta = dict(finding.get("meta") or {}, fp=finding["fingerprint"])
    if meta.get("quote"):
        meta["quote"] = mask_secrets(meta["quote"])
    encoded = base64.b64encode(json.dumps(meta, sort_keys=True).encode("utf-8")).decode("ascii")
    lines += ["---", f"_{origin} Raised automatically by the RepoMind review of `{base}..{head[:7]}`. "
              "If this isn't a problem, close the issue — it won't be raised again._",
              f"<!-- repomind:meta={encoded} -->"]
    return title, "\n".join(lines)


# ------------------------------------------------------------------ apply

def apply(client: Client, slug: str, findings: list, run_plan: dict, rng: dict) -> dict:
    """Creates the planned issues and closes the resolved ones. Returns
    {"created": [{fingerprint, number, url}], "closed": [...], "errors": [...]}."""
    by_fp = {f["fingerprint"]: f for f in findings}
    created, closed, errors = [], [], []
    to_create = [i for i in run_plan["items"] if i["action"] == "create"]
    if to_create:
        try:
            client.request("POST", f"/repos/{slug}/labels", json={
                "name": LABEL, "color": LABEL_COLOR, "description": "Raised by the RepoMind code review"})
        except GitHubError as exc:
            if "422" not in str(exc):  # 422 = the label already exists
                errors.append(str(exc))
    for item in to_create:
        title, body = render_issue(by_fp[item["fingerprint"]], slug, rng)
        try:
            issue = client.request("POST", f"/repos/{slug}/issues", json={"title": title, "body": body,
                                                                           "labels": [LABEL]})
            created.append({"fingerprint": item["fingerprint"], "number": issue["number"], "url": issue["html_url"]})
        except GitHubError as exc:
            errors.append(str(exc))
    for r in run_plan.get("resolve", []):
        try:
            client.request("POST", f"/repos/{slug}/issues/{r['number']}/comments", json={
                "body": f"Resolved at {rng['head'][:7]}: {r['reason']}. Closed automatically by the RepoMind review."})
            client.request("PATCH", f"/repos/{slug}/issues/{r['number']}", json={"state": "closed",
                                                                                "state_reason": "completed"})
            closed.append(r)
        except GitHubError as exc:
            errors.append(str(exc))
    return {"created": created, "closed": closed, "errors": errors}


def presence_checker(read_file, head_violation_pairs):
    """still_present() for plan(): architecture findings are present while
    the (rule, module) pair still violates at head; code findings while the
    quoted code is still in the file. read_file(path) -> text or None."""
    pairs = {tuple(p) for p in head_violation_pairs}

    def still_present(meta):
        if meta.get("kind") == "architecture":
            return (meta.get("rule"), meta.get("module")) in pairs
        if meta.get("kind") == "code" and meta.get("file") and meta.get("quote"):
            text = read_file(meta["file"])
            if text is None:
                return False
            return " ".join(mask_secrets(meta["quote"]).split()) in " ".join(mask_secrets(text).split())
        return None
    return still_present


# ------------------------------------------------------------------ one entry point for the app and the CLI

_transport = None  # tests install an httpx.MockTransport here


def sync(review: dict, repo_url: str, read_file, *, apply_changes: bool, selected=None, slug: str = None,
         token: str = None) -> dict:
    """Preview (apply_changes=False) or perform the GitHub side of a review.

    Returns {"available", "slug", "can_raise", "reason", "items", "resolve",
    "creates", "result"}; never raises for GitHub problems — they come back
    as a reason, so the review itself is always shown."""
    slug = slug or repo_slug(repo_url)
    out = {"available": False, "slug": slug, "can_raise": False, "reason": "", "items": [], "resolve": [],
           "creates": 0, "result": None}
    if not slug:
        out["reason"] = "Issues can only be raised for repositories hosted on github.com."
        return out
    token = token or os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        out["reason"] = "Set GITHUB_TOKEN in .env to raise issues (a fine-grained token with Issues read/write)."
        return out
    client = Client(token, transport=_transport)
    try:
        allowed = access(client, slug)
        out["available"] = True
        if not allowed["ok"]:
            out["reason"] = allowed["reason"]
            return out
        out["can_raise"] = True
        try:
            issues = existing(client, slug)
        except GitHubError as exc:
            out["can_raise"], out["reason"] = False, str(exc)
            return out
        checker = presence_checker(read_file, review.get("head_violation_pairs", []))
        run_plan = plan(review["findings"], issues, still_present=checker, selected=selected)
        out.update(items=run_plan["items"], resolve=run_plan["resolve"], creates=run_plan["creates"])
        if apply_changes:
            out["result"] = apply(client, slug, review["findings"], run_plan, review["range"])
        return out
    finally:
        client.close()
