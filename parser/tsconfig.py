"""TypeScript/JavaScript path aliases from tsconfig.json / jsconfig.json.

Real TS projects rarely import across folders with long relative paths;
they declare `compilerOptions.paths` (`"@/*": ["src/*"]`) or a `baseUrl`
and write `import { x } from '@/services/user'`. Without reading the
config those imports look like npm packages and every edge through them
is lost.

Only what module resolution needs is read: `baseUrl`, `paths`, and
`extends` chains between files inside the repository. Each config applies
to the files under its own folder; the nearest one wins.
"""
from __future__ import annotations

import json
import os
import posixpath

_SKIP_DIRS = {".git", "venv", ".venv", "env", "__pycache__", "node_modules"}
CONFIG_PREFIXES = ("tsconfig", "jsconfig")
_MAX_EXTENDS = 5


def is_config_file(name: str) -> bool:
    return name.endswith(".json") and name.startswith(CONFIG_PREFIXES)


def strip_jsonc(text: str) -> str:
    """tsconfig is JSON with comments and trailing commas; json.loads wants
    neither. Strings are copied verbatim so `"@/*"` or URLs survive."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
        elif c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "]}":
                i += 1  # trailing comma
            else:
                out.append(c)
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _read_json(abs_path: str):
    try:
        with open(abs_path, encoding="utf-8-sig") as f:
            return json.loads(strip_jsonc(f.read()))
    except (OSError, ValueError):
        return None


def _compiler_options(repo_path: str, rel_path: str, depth: int = 0) -> dict:
    """compilerOptions with `extends` applied, and baseUrl/paths made
    repo-relative (they are relative to the file that declares them)."""
    data = _read_json(os.path.join(repo_path, *rel_path.split("/")))
    if not isinstance(data, dict):
        return {}
    here = posixpath.dirname(rel_path)
    merged = {}
    parents = data.get("extends")
    for parent in ([parents] if isinstance(parents, str) else parents or []):
        if depth >= _MAX_EXTENDS or not isinstance(parent, str) or not parent.startswith("."):
            continue  # package configs (`@tsconfig/node18`) never carry repo paths
        target = posixpath.normpath(posixpath.join(here, parent))
        if not target.endswith(".json"):
            target += ".json"
        if target.startswith(".."):
            continue
        merged.update(_compiler_options(repo_path, target, depth + 1))

    options = data.get("compilerOptions")
    if isinstance(options, dict):
        if isinstance(options.get("baseUrl"), str):
            merged["baseUrl"] = _join(here, options["baseUrl"])
        if isinstance(options.get("paths"), dict):
            merged["paths"] = options["paths"]
            merged["pathsDir"] = here
    return merged


def _join(base: str, rel: str) -> str:
    joined = posixpath.normpath(posixpath.join(base, rel)) if base else posixpath.normpath(rel)
    return "" if joined == "." else joined


def load_path_configs(repo_path: str) -> list:
    """One entry per tsconfig.json/jsconfig.json in the repo that declares
    baseUrl or paths: {"dir", "base_url", "paths": [(pattern, [targets])]},
    with every path repo-relative. Sorted deepest folder first."""
    configs = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name not in ("tsconfig.json", "jsconfig.json"):
                continue
            rel = os.path.relpath(os.path.join(root, name), repo_path).replace(os.sep, "/")
            options = _compiler_options(repo_path, rel)
            # Paths resolve against baseUrl when one is in effect, otherwise
            # against the config that declared them.
            paths_base = options.get("baseUrl", options.get("pathsDir", ""))
            paths = []
            for pattern, targets in (options.get("paths") or {}).items():
                if not isinstance(pattern, str) or not isinstance(targets, list) or pattern.count("*") > 1:
                    continue
                resolved = [_join(paths_base, t) for t in targets if isinstance(t, str) and t.count("*") <= 1]
                if resolved:
                    paths.append((pattern, resolved))
            if paths or options.get("baseUrl") is not None:
                configs.append({"dir": posixpath.dirname(rel), "name": name, "base_url": options.get("baseUrl"), "paths": paths})
    # Deepest folder first; tsconfig.json wins over jsconfig.json in one folder.
    seen, unique = set(), []
    for c in sorted(configs, key=lambda c: (-len(c["dir"]), c["dir"], c["name"] != "tsconfig.json")):
        if c["dir"] not in seen:
            seen.add(c["dir"])
            unique.append(c)
    return unique


def config_for(configs: list, importer: str):
    for c in configs:  # deepest first
        if not c["dir"] or importer == c["dir"] or importer.startswith(c["dir"] + "/"):
            return c
    return None


def alias_candidates(spec: str, config) -> list:
    """Repo-relative paths (without extension probing) a non-relative
    specifier may refer to under `config`, most specific pattern first.
    The caller keeps the first one that is a parsed file, so a bare npm
    package name that merely matches `baseUrl` stays external."""
    if config is None:
        return []
    matches = []
    for pattern, targets in config["paths"]:
        if "*" in pattern:
            prefix, suffix = pattern.split("*")
            if spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
                star = spec[len(prefix):len(spec) - len(suffix)]
                matches.append((len(prefix), [t.replace("*", star) for t in targets]))
        elif spec == pattern:
            matches.append((len(pattern) + 1, targets))
    matches.sort(key=lambda m: -m[0])
    candidates = [t for _, targets in matches for t in targets]
    if config["base_url"] is not None:
        candidates.append(_join(config["base_url"], spec))
    return candidates
