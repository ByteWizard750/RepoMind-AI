"""Builds RepoMind's two demo repositories, and drives the live code-review
part of the demo.

  python demo/build_demo_repos.py build [--out DIR]
      Creates DIR/shopwise (Python, FastAPI) and DIR/taskflow (TypeScript,
      Express) from their scripted histories. Default DIR: a `repomind-demos`
      folder next to this repository. Rebuilding replaces only folders this
      script created.

  python demo/build_demo_repos.py ci DIR/shopwise
      Commits RepoMind's GitHub Action (.github/workflows/repomind-review.yml),
      so every later push is reviewed and issues are raised automatically.

  python demo/build_demo_repos.py bad DIR/shopwise
      Commits planted problems (SQL injection, a router reaching the database,
      a swallowed exception, a hard-coded secret, ... ; TaskFlow: a missing
      await, an assignment in a condition, raw SQL from a controller).
  python demo/build_demo_repos.py fix DIR/shopwise
      Commits the fixes, so RepoMind closes the issues it raised.

Nothing is pushed: push yourself (`git push`) after each step you want
GitHub to see. See demo/README.md for the full demo-day script.
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gitstory  # noqa: E402
import shop_story  # noqa: E402
import tasks_story  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(os.path.dirname(ROOT), "repomind-demos")
REPOS = {"shopwise": shop_story, "taskflow": tasks_story}


def _story_for(repo: str):
    if not os.path.exists(os.path.join(repo, gitstory.MARKER)):
        raise SystemExit(f"{repo} isn't a demo repository built by this script.")
    return shop_story if os.path.exists(os.path.join(repo, "requirements.txt")) else tasks_story


def build(out: str) -> None:
    for name, story in REPOS.items():
        path = os.path.join(out, name)
        gitstory.fresh_repo(path)
        commits = gitstory.play(path, story.STORY)
        print(f"{name}: {commits} commits in {path}")


def live_commit(repo: str, which: str) -> None:
    step = getattr(_story_for(repo), "BAD_COMMIT" if which == "bad" else "FIX_COMMIT")
    # Dated now, so it reads as fresh on GitHub and in the review.
    from datetime import datetime, timezone
    when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    sha = gitstory.commit(repo, when, step["author"], step["message"], step["files"])
    print(f"committed {sha}: {step['message']}")


def add_ci(repo: str) -> None:
    _story_for(repo)
    target = os.path.join(repo, ".github", "workflows", "repomind-review.yml")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, "ci", "repomind-review.yml"), target)
    from datetime import datetime, timezone
    when = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    author = _story_for(repo).STORY[0]["author"]
    sha = gitstory.commit(repo, when, author, "Review every push with RepoMind")
    print(f"committed {sha}: added .github/workflows/repomind-review.yml")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=DEFAULT_OUT)
    for name in ("ci", "bad", "fix"):
        sub.add_parser(name).add_argument("repo")
    args = ap.parse_args(argv)
    if args.command == "build":
        build(os.path.abspath(args.out))
    elif args.command == "ci":
        add_ci(os.path.abspath(args.repo))
    else:
        live_commit(os.path.abspath(args.repo), args.command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
