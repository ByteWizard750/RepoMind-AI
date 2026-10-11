"""Tree-sitter based parsing of TypeScript source into the SAME output
shape parser/ast_extractor.py and parser/js_extractor.py produce, so
graph/loader.py needs no changes to accept it.

TypeScript reuses the exact same node types as JavaScript for every
construct this project extracts (function_declaration, arrow_function,
class_declaration, method_definition, import_statement, call_expression —
confirmed empirically, no renaming or wrapping) — typed parameters and
return types just add sibling `type_annotation` children without changing
node types, so raw-text signature capture keeps working unmodified, and
class/method decorators are a plain repeated `decorator` field (unlike
Python's wrapping `decorated_definition`), so no unwrapping is needed.
TS-only constructs (`interface_declaration`, `type_alias_declaration`) are
type-only — deliberately not extracted as Class/Function since they don't
exist at runtime.

All node-level extraction and the import/call resolution are shared with
js_extractor.py; this module only supplies the TS/TSX grammars and file
walk. Normally TS is resolved together with JS (js_extractor.parse_family).
"""
from __future__ import annotations

import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

from parser import js_extractor

TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())

_SKIP_DIRS = js_extractor._SKIP_DIRS
_TS_EXTENSIONS = (".ts",)
_TSX_EXTENSIONS = (".tsx",)


def extract_repo(repo_path: str) -> dict:
    """Per-file extraction results for every .ts/.tsx file (declaration
    files excluded: they describe code, they aren't code)."""
    ts_parser = Parser(TS_LANGUAGE)
    tsx_parser = Parser(TSX_LANGUAGE)
    raw_files = {}
    for rel_path, abs_path in js_extractor.iter_files(repo_path, _TS_EXTENSIONS):
        if not rel_path.endswith(".d.ts"):
            raw_files[rel_path] = js_extractor.extract_source(ts_parser, abs_path)
    for rel_path, abs_path in js_extractor.iter_files(repo_path, _TSX_EXTENSIONS):
        raw_files[rel_path] = js_extractor.extract_source(tsx_parser, abs_path)
    return raw_files


def parse_repo(repo_path: str) -> dict:
    """Parse every .ts/.tsx file under repo_path and resolve CALLS/IMPORTS
    edges among them. Returns the same dict shape as ast_extractor.parse_repo."""
    return js_extractor.build(repo_path, extract_repo(repo_path))
