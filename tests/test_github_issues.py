"""Raising review findings as GitHub issues, against an in-memory GitHub."""
import json

import pytest

from fixtures.fake_github import FakeGitHub
from review import github_issues as gh

TOKEN = "ghp_secret_test_token_123"
RANGE = {"base": "a" * 40, "head": "b" * 40, "base_short": "aaaaaaa", "head_short": "bbbbbbb", "empty_base": False}


def _finding(fp, severity="high", kind="code", **kw):
    f = {"fingerprint": fp, "kind": kind, "category": "bug" if kind == "code" else "architecture",
         "severity": severity, "confidence": 0.9 if kind == "code" else 1.0, "file": "app/x.py", "line": 12,
         "quote": "return total - discount", "title": f"Finding {fp}", "explanation": "Ping @alice about it.",
         "suggestion": "Fix it.", "commits": ["bbbbbbb"],
         "meta": {"kind": kind, "file": "app/x.py", "quote": "return total - discount"} if kind == "code"
         else {"kind": "architecture", "rule": "no-controller-to-db", "module": "app/x.py"}}
    f.update(kw)
    return f


def _review(*findings, pairs=()):
    return {"findings": list(findings), "range": RANGE, "head_violation_pairs": list(pairs)}


@pytest.fixture
def fake(monkeypatch):
    server = FakeGitHub("owner/repo")
    monkeypatch.setattr(gh, "_transport", server.transport())
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return server


def _sync(review, apply_changes=True, files=None, **kw):
    files = files if files is not None else {"app/x.py": "def f():\n    return total - discount\n"}
    return gh.sync(review, "https://github.com/owner/repo", files.get, apply_changes=apply_changes, **kw)


def test_repo_slug():
    assert gh.repo_slug("https://github.com/owner/repo") == "owner/repo"
    assert gh.repo_slug("https://github.com/owner/repo.git") == "owner/repo"
    assert gh.repo_slug("git@github.com:owner/my.repo.git") == "owner/my.repo"
    assert gh.repo_slug("https://gitlab.com/owner/repo") is None
    assert gh.repo_slug("C:/code/repo") is None


def test_no_token_or_not_github(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = _sync(_review(_finding("f1")), apply_changes=False)
    assert not out["can_raise"] and "GITHUB_TOKEN" in out["reason"]
    out = gh.sync(_review(_finding("f1")), "https://gitlab.com/o/r", lambda p: None, apply_changes=False)
    assert not out["can_raise"] and "github.com" in out["reason"]


@pytest.mark.parametrize("permissions", [{"admin": False, "maintain": False, "push": False, "triage": False,
                                          "pull": True}, False])
def test_refuses_repos_the_token_does_not_maintain(fake, permissions):
    fake.permissions = permissions
    out = _sync(_review(_finding("f1")))
    assert not out["can_raise"] and "only files issues on repositories you maintain" in out["reason"]
    assert not any(method != "GET" for method, _, _ in fake.requests) and fake.issues == {}


def test_actions_token_is_accepted_for_its_own_repo(fake, monkeypatch):
    fake.permissions = False   # installation tokens don't report user permissions
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    assert _sync(_review(_finding("f1")))["result"]["created"]


def test_creates_labelled_issues_with_marker_and_never_duplicates(fake):
    review = _review(_finding("f1"), _finding("f2", severity="low"))
    out = _sync(review)
    created = out["result"]["created"]
    assert [c["fingerprint"] for c in created] == ["f1"] and "repomind-review" in fake.labels
    issue = fake.issues[created[0]["number"]]
    assert issue["title"].startswith("[RepoMind] High · bug: Finding f1")
    assert "@\u200balice" in issue["body"] and "@alice" not in issue["body"]          # no pings
    assert f"blob/{'b' * 40}/app/x.py#L12" in issue["body"]
    assert gh.decode_meta(issue["body"])["fp"] == "f1"
    low = next(i for i in out["items"] if i["fingerprint"] == "f2")
    assert low["action"] == "skip" and "threshold" in low["reason"]

    again = _sync(review)
    assert again["result"]["created"] == [] and len(fake.issues) == 1
    assert next(i for i in again["items"] if i["fingerprint"] == "f1")["reason"] == "already open as #1"


def test_closed_issues_are_not_reraised(fake):
    title, body = gh.render_issue(_finding("f1"), "owner/repo", RANGE)
    fake.add_issue(title, body, state="closed")
    out = _sync(_review(_finding("f1")))
    assert out["result"]["created"] == [] and "not re-raised" in out["items"][0]["reason"]


def test_cap_and_selection(fake, monkeypatch):
    findings = [_finding(f"f{i}") for i in range(5)]
    out = _sync(_review(*findings), apply_changes=False)
    assert out["creates"] == 5 and fake.issues == {}                 # preview writes nothing
    monkeypatch.setattr(gh, "MAX_ISSUES", 2)
    out = _sync(_review(*findings))
    assert len(out["result"]["created"]) == 2
    assert sum("limit" in i["reason"] for i in out["items"]) == 3
    out = _sync(_review(*findings), selected={"f4"})
    assert [c["fingerprint"] for c in out["result"]["created"]] == ["f4"]


def test_resolved_findings_are_closed_only_when_verifiably_gone(fake):
    for f in (_finding("code-gone"),
              _finding("code-still", meta={"kind": "code", "file": "app/x.py", "quote": "keep_me()"}),
              _finding("arch-gone", kind="architecture"),
              _finding("arch-still", kind="architecture", meta={"kind": "architecture", "rule": "r2",
                                                                "module": "app/y.py"})):
        title, body = gh.render_issue(f, "owner/repo", RANGE)
        fake.add_issue(title, body)
    files = {"app/x.py": "def f():\n    keep_me()\n"}             # the first quote is gone, keep_me() remains
    out = _sync(_review(pairs=[("r2", "app/y.py")]), files=files)
    closed = sorted(c["number"] for c in out["result"]["closed"])
    assert closed == [1, 3]
    assert fake.issues[1]["state"] == "closed" and fake.issues[2]["state"] == "open"
    assert fake.issues[4]["state"] == "open" and len(fake.comments) == 2


def test_token_never_leaks(fake, monkeypatch):
    fake.permissions = False
    out = _sync(_review(_finding("f1")))
    assert TOKEN not in json.dumps(out, default=str)
    assert all(auth == f"Bearer {TOKEN}" for _, _, auth in fake.requests)   # sent only as the auth header
    monkeypatch.setattr(gh, "_transport", FakeGitHub("someone/else").transport())
    out = _sync(_review(_finding("f1")))
    assert TOKEN not in json.dumps(out, default=str) and not out["can_raise"]


def test_secrets_are_masked_in_issues_and_resolution_still_works(fake):
    secret = "sk_" + "live_51H8xQ2eZvKYlo2C9a7RmT3pQ"  # split so secret scanners skip this fake key
    quote = f'STRIPE_API_KEY = "{secret}"'
    finding = _finding("sec", category="security", quote=quote, explanation=f"The key {secret} is committed.",
                       meta={"kind": "code", "file": "app/x.py", "quote": quote})
    out = _sync(_review(finding), files={"app/x.py": quote + "\n"})
    body = fake.issues[out["result"]["created"][0]["number"]]["body"]
    assert secret not in body and "sk_live_****" in body
    assert secret not in json.dumps(gh.decode_meta(body))
    # The masked marker still recognises the code while it's there, and closes the issue once it's gone.
    assert _sync(_review(), files={"app/x.py": quote + "\n"})["result"]["closed"] == []
    closed = _sync(_review(), files={"app/x.py": 'STRIPE_API_KEY = os.environ["STRIPE_API_KEY"]\n'})
    assert [c["number"] for c in closed["result"]["closed"]] == [1]
