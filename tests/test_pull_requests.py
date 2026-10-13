"""Pull request and issue text for ADR evidence: finding the numbers behind
commits (messages, merge commits) and fetching their text from GitHub."""
import json
import os
import subprocess

import httpx
import pytest

import cache
from adr import pull_requests
from adr.pull_requests import PullRequestSource, clean_body, message_refs
from history import mine_commits

DAY = 86_400
T0 = 1_700_000_000


def _git(repo, *args, when=T0):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Ada", "GIT_AUTHOR_EMAIL": "ada@example.com",
           "GIT_COMMITTER_NAME": "Ada", "GIT_COMMITTER_EMAIL": "ada@example.com",
           "GIT_AUTHOR_DATE": f"@{when} +0000", "GIT_COMMITTER_DATE": f"@{when} +0000"}
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


@pytest.fixture
def merged_repo(tmp_path):
    return make_merged_repo(str(tmp_path / "repo"))


def make_merged_repo(repo):
    """main: initial; a feature branch with two commits merged as pull request #7; a squash commit "(#9)"."""
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    open(os.path.join(repo, "app.py"), "w").write("x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "Initial")
    _git(repo, "checkout", "-q", "-b", "feature")
    for i, name in enumerate(("cache.py", "settings.py"), 1):
        open(os.path.join(repo, name), "w").write(f"y = {i}\n")
        _git(repo, "add", "-A", when=T0 + i * DAY)
        _git(repo, "commit", "-q", "-m", f"wip {i}", when=T0 + i * DAY)
    _git(repo, "checkout", "-q", "main", when=T0 + 3 * DAY)
    _git(repo, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #7 from ada/feature",
         when=T0 + 3 * DAY)
    open(os.path.join(repo, "app.py"), "w").write("x = 2\n")
    _git(repo, "add", "-A", when=T0 + 4 * DAY)
    _git(repo, "commit", "-q", "-m", "Switch to pydantic settings (#9)", when=T0 + 4 * DAY)
    return repo


def _github(responses: dict, calls: list):
    def handler(request):
        calls.append((request.url.path, request.headers.get("authorization")))
        number = int(request.url.path.rsplit("/", 1)[1])
        status, body, headers = responses.get(number, (404, {"message": "Not Found"}, {}))
        return httpx.Response(status, json=body, headers=headers)
    return httpx.MockTransport(handler)


PR7 = {"title": "Cache settings in Redis", "body": "<!-- template -->We switch to Redis because the file cache "
       "doesn't scale.\n\n\n![shot](x.png)", "html_url": "https://github.com/o/r/pull/7", "state": "closed",
       "pull_request": {"merged_at": "2023-11-17T00:00:00Z"}}
ISSUE9 = {"title": "Settings are scattered", "body": "Config lives in three places.", "html_url":
          "https://github.com/o/r/issues/9", "state": "closed"}


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(pull_requests, "ENABLED", True)


def test_message_refs_and_body_cleaning():
    assert message_refs({"subject": "Use BaseSettings (#219)", "body": ""}) == [219]
    assert message_refs({"subject": "Fix login", "body": "Fixes #12 and #13. See #12, #14, #15"}) == [12, 13, 14]
    assert message_refs({"subject": "Colour #fff and a&#38;b and path/#3", "body": ""}) == []
    assert clean_body(PR7["body"]) == "We switch to Redis because the file cache doesn't scale."
    assert len(clean_body("x" * 5000)) == pull_requests.BODY_CHARS + 1


def test_commits_are_linked_through_merges_and_messages(merged_repo):
    commits = mine_commits(merged_repo)["commits"]              # merge commits are left out
    by_subject = {c["subject"]: c for c in commits}
    calls = []
    source = PullRequestSource("https://github.com/o/r", merged_repo, token="tok",
                               transport=_github({7: (200, PR7, {}), 9: (200, ISSUE9, {})}, calls))
    links, complete = source.attach(commits)
    assert complete
    assert [r["number"] for r in links[by_subject["wip 1"]["hash"]]] == [7]          # via the merge commit
    assert [r["number"] for r in links[by_subject["wip 2"]["hash"]]] == [7]
    assert links[by_subject["Switch to pydantic settings (#9)"]["hash"]][0]["kind"] == "issue"
    assert by_subject["Initial"]["hash"] not in links
    pr = links[by_subject["wip 1"]["hash"]][0]
    assert pr["kind"] == "pull request" and pr["merged"] and "doesn't scale" in pr["body"] and "<!--" not in pr["body"]
    assert sorted(p for p, _ in calls) == ["/repos/o/r/issues/7", "/repos/o/r/issues/9"]   # each fetched once
    assert all(auth == "Bearer tok" for _, auth in calls)

    again = PullRequestSource("https://github.com/o/r", merged_repo, token="", transport=_github({}, calls))
    links2, _ = again.attach(commits)                            # from the disk cache: no new requests
    assert len(calls) == 2 and links2.keys() == links.keys() and again.status()["from_cache"] == 2


def test_rate_limits_caps_and_missing_numbers(merged_repo):
    commits = mine_commits(merged_repo)["commits"]
    limited = PullRequestSource("https://github.com/o/r", merged_repo, token="", transport=_github(
        {7: (403, {"message": "API rate limit exceeded"}, {"x-ratelimit-remaining": "0"})}, []))
    links, complete = limited.attach(commits)
    assert links == {} and not complete and limited.status()["stopped"] == "rate limit"

    missing = PullRequestSource("https://github.com/o/r", merged_repo, token="t", transport=_github({}, []))
    links, complete = missing.attach(commits)
    assert links == {} and complete                              # numbers that don't exist aren't "incomplete"

    cache_dir = cache.CACHE_DIR
    cache.CACHE_DIR = cache_dir + "-2"                            # forget the cached "doesn't exist" answers
    try:
        capped = PullRequestSource("https://github.com/o/r", merged_repo, token="t", max_fetch=1,
                                   transport=_github({7: (200, PR7, {}), 9: (200, ISSUE9, {})}, []))
        links, complete = capped.attach(commits)
        assert not complete and capped.status()["skipped"] >= 1
    finally:
        cache.CACHE_DIR = cache_dir


def test_text_mentioning_an_excluded_path_is_withheld(merged_repo):
    leaky = {**PR7, "body": "Implements docs/adr/0003-use-redis.md"}
    source = PullRequestSource("https://github.com/o/r", merged_repo, token="t", exclude_paths=["docs/adr/*"],
                               transport=_github({7: (200, leaky, {}), 9: (200, ISSUE9, {})}, []))
    links, complete = source.attach(mine_commits(merged_repo)["commits"])
    assert complete and all(r["number"] != 7 for rs in links.values() for r in rs)
    assert source.status()["withheld"] == 1


def test_no_lookup_outside_github(merged_repo):
    source = PullRequestSource("local:somewhere", merged_repo, transport=_github({}, []))
    assert not source.available
    assert source.attach(mine_commits(merged_repo)["commits"]) == ({}, True)
    assert source.status()["source"] is None and source.status()["complete"]
