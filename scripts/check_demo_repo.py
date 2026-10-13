"""Checks a demo repository tells the story RepoMind should find, offline
(no Neo4j, no AI): the history, the health curve over the same evenly spaced
snapshots the app uses, the violations at HEAD, and the detected decision
points.

Usage: python scripts/check_demo_repo.py <repo_path> [--rules rules.yaml] [--snapshots 20] [--all]
  --rules      defaults to the repository's own rules.yaml, else RepoMind's
  --all        evaluate every commit instead of the snapshots (slower, exact)
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from adr.detect import detect_decisions  # noqa: E402
from history import commit_meta, contributors, git, mine_commits  # noqa: E402
from rules.config import RulesError, load_rules_config  # noqa: E402
from snapshots import (_attach_diffs, parse_commit, pick_snapshot_commits, source_change_filter,  # noqa: E402
                       summarize)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo_path")
    ap.add_argument("--rules")
    ap.add_argument("--snapshots", type=int, default=20)
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    repo = os.path.abspath(args.repo_path)

    rules_path = args.rules or (os.path.join(repo, "rules.yaml") if os.path.exists(os.path.join(repo, "rules.yaml"))
                                else None)
    try:
        rules = load_rules_config(open(rules_path, encoding="utf-8").read() if rules_path else None)
    except RulesError as exc:
        print(f"Invalid rules ({rules_path}): {exc}")
        return 2
    print(f"Rules: {rules_path or 'RepoMind default rules.yaml'} "
          f"({len(rules['rules'])} rules, layers: {', '.join(rules.get('layers', {})) or 'parser defaults'})")

    commits = mine_commits(repo)["commits"]
    first_parent = git(repo, "rev-list", "--first-parent", "--count", "HEAD").strip()
    print(f"\nCommits: {len(commits)} (non-merge), {first_parent} on the first-parent line")
    if commits:
        print(f"Dates: {commits[0]['date'][:10]} to {commits[-1]['date'][:10]}")
    print("Authors: " + ", ".join(f"{c['name']} ({c['commits']})" for c in contributors(commits, top=20)))

    t0 = time.time()
    head = parse_commit(repo, "HEAD", rules)
    layered = {}
    for m in head["modules"]:
        layered.setdefault(m.get("layer_type") or "(no layer)", []).append(m["path"])
    print(f"\nHEAD: {len(head['modules'])} modules, {len(head['calls'])} resolved calls, "
          f"{len(head['imports'])} imports (parsed in {time.time() - t0:.1f}s)")
    for layer, paths in sorted(layered.items()):
        print(f"  {layer:<16} {len(paths):>3}  e.g. {', '.join(sorted(paths)[:3])}")

    n = 10_000 if args.all else args.snapshots
    shas = pick_snapshot_commits(repo, n, source_change_filter(commits))
    snaps = []
    for idx, sha in enumerate(shas):
        facts = summarize(head, rules) if idx == len(shas) - 1 else summarize(parse_commit(repo, sha, rules), rules)
        meta = commit_meta(repo, sha)
        snaps.append({"idx": idx, "sha": sha, "short": sha[:7], "date": meta.get("date"),
                      "subject": meta.get("subject", ""), **facts})
    _attach_diffs(snaps)

    print(f"\nHealth curve ({len(snaps)} {'commits' if args.all else 'snapshots, as the app picks them'}):")
    for s in snaps:
        h = "  n/a" if s["health"] is None else f"{s['health']:5.1f}"
        delta = ""
        if s.get("new_violations"):
            delta += f"  +{len(s['new_violations'])} new"
        if s.get("resolved_violations"):
            delta += f"  -{len(s['resolved_violations'])} resolved"
        print(f"  {s['idx']:>3} {s['short']} {str(s['date'])[:10]} health {h}  "
              f"violations {len(s['violations']):>2}{delta}  {s['subject'][:60]}")

    final = snaps[-1]
    print(f"\nViolations at HEAD: {len(final['violations'])}")
    by_rule = {}
    for key in final["violation_keys"]:
        by_rule.setdefault(key[0], set()).add(key[1])
    for rule, modules in sorted(by_rule.items()):
        print(f"  {rule}: {', '.join(sorted(modules))}")
    for line in final["violations"]:
        print(f"    {line}")

    decisions = detect_decisions(repo, commits, snaps, exclude_patterns=("docs/adr/*", "doc/adr/*", "adr/*"))
    print(f"\nDecision points RepoMind would reconstruct as ADRs: {len(decisions)}")
    for d in decisions:
        print(f"  [{d['kind']}] {d['sha'][:7]} {d['subject'][:90]}  (significance {d['significance']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
