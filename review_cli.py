"""RepoMind code review from the command line — what the GitHub Action runs.

Reviews a range of commits in a local checkout (no Neo4j, no server),
prints a Markdown report (also to $GITHUB_STEP_SUMMARY inside Actions) and,
with --raise, files GitHub issues for the findings and closes RepoMind
issues whose problem is gone.

Usage:
  python review_cli.py --repo-path . [--base SHA | --commits N]
                       [--repo owner/name] [--rules rules.yaml]
                       [--raise] [--fail-on high]

Inside GitHub Actions --repo defaults to $GITHUB_REPOSITORY and the token
to the workflow's $GITHUB_TOKEN (needs `permissions: issues: write`).
"""
import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from agents.review_graph import SEVERITIES, review_changes  # noqa: E402
from review import github_issues  # noqa: E402
from review.diff import file_at  # noqa: E402
from rules.config import RulesError, load_rules_config  # noqa: E402

_RANK = {s: len(SEVERITIES) - i for i, s in enumerate(SEVERITIES)}


def report(result: dict, gh: dict) -> str:
    rng = result["range"]
    lines = [f"## RepoMind code review — `{rng['base_short']}..{rng['head_short']}`", "",
             f"{len(rng['commits'])} commit(s), {len(result['files_reviewed'])} file(s) reviewed, "
             f"{len(result['findings'])} finding(s)"
             + (f", {result['unverified']} unverified AI finding(s) dropped" if result["unverified"] else "") + ".", ""]
    if result["findings"]:
        lines += ["| # | Severity | Category | Location | Finding |", "|---|---|---|---|---|"]
        for f in result["findings"]:
            where = f["file"] + (f":{f['line']}" if f.get("line") else "")
            lines.append(f"| {f['rank']} | {f['severity']} | {f['category']} | `{where}` | {f['title']} |")
        lines.append("")
    for w in result["warnings"]:
        lines.append(f"- ⚠ {w}")
    if gh:
        if gh.get("result"):
            res = gh["result"]
            lines += ["", f"**Issues:** {len(res['created'])} created, {len(res['closed'])} closed as resolved."]
            lines += [f"- created #{c['number']}: {c['url']}" for c in res["created"]]
            lines += [f"- closed #{c['number']} ({c['reason']})" for c in res["closed"]]
            lines += [f"- error: {e}" for e in res["errors"]]
        elif gh.get("reason"):
            lines += ["", f"**Issues not raised:** {gh['reason']}"]
        skipped = [i for i in gh.get("items", []) if i["action"] == "skip"]
        if skipped:
            lines += ["", f"{len(skipped)} finding(s) not raised: "
                      + "; ".join(sorted({i['reason'] for i in skipped}))]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="RepoMind code review of a commit range")
    ap.add_argument("--repo-path", default=".")
    ap.add_argument("--base", help="review base..HEAD (e.g. the push event's `before` sha)")
    ap.add_argument("--commits", type=int, help="review the last N commits (default REVIEW_DEFAULT_COMMITS=5)")
    ap.add_argument("--repo", help="owner/name on GitHub (default: $GITHUB_REPOSITORY or the origin remote)")
    ap.add_argument("--rules", help="rules YAML file (default: the repository's rules.yaml, else RepoMind's)")
    ap.add_argument("--raise", dest="raise_issues", action="store_true", help="create/close GitHub issues")
    ap.add_argument("--fail-on", choices=SEVERITIES, help="exit 1 if a finding at this severity or above exists")
    args = ap.parse_args(argv)

    repo = os.path.abspath(args.repo_path)
    try:
        rules = load_rules_config(open(args.rules, encoding="utf-8").read() if args.rules else None)
    except (OSError, RulesError) as exc:
        print(f"Invalid rules file {args.rules}: {exc}", file=sys.stderr)
        return 2
    if not args.rules and os.path.exists(os.path.join(repo, "rules.yaml")):
        # The repository's own architecture rules, if that file is RepoMind's format.
        try:
            rules = load_rules_config(open(os.path.join(repo, "rules.yaml"), encoding="utf-8").read())
        except RulesError as exc:
            print(f"rules.yaml in the repository isn't RepoMind's format ({exc}); using the default rules.",
                  file=sys.stderr)

    slug = args.repo or os.environ.get("GITHUB_REPOSITORY")
    if not slug:
        try:
            from history import git
            slug = github_issues.repo_slug(git(repo, "remote", "get-url", "origin").strip())
        except Exception:
            slug = None
    repo_url = f"https://github.com/{slug}" if slug else repo

    result = review_changes(repo, repo_url, rules, base=args.base, commits=args.commits)
    gh = {}
    if args.raise_issues:
        gh = github_issues.sync(result, repo_url, lambda path: file_at(repo, result["range"]["head"], path),
                                apply_changes=True, slug=slug)

    text = report(result, gh)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    if args.fail_on and any(_RANK[f["severity"]] >= _RANK[args.fail_on] for f in result["findings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
