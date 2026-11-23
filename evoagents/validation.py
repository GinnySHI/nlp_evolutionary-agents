"""Non-executing checks for generated text artifacts; never a functional verdict."""
from __future__ import annotations

import ast
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import PurePosixPath
import re


class _HTMLStructure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.starts = Counter()
        self.ends = Counter()
        self.ids = Counter()

    def handle_starttag(self, tag, attrs):
        self.starts[tag] += 1
        for key, value in attrs:
            if key == "id" and value:
                self.ids[value] += 1

    def handle_endtag(self, tag):
        self.ends[tag] += 1


def validate_text(path: str, text: str) -> dict:
    errors, warnings = [], []
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".py":
        try:
            ast.parse(text, filename=path)
        except (SyntaxError, ValueError, RecursionError) as exc:
            errors.append(f"Python syntax error at line {getattr(exc, 'lineno', '?')}: {type(exc).__name__}")
    elif suffix == ".json":
        try:
            json.loads(text, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, RecursionError):
            errors.append("Invalid JSON document.")
    elif suffix in {".html", ".htm"}:
        parser = _HTMLStructure()
        parser.feed(text)
        for tag in ("html", "head", "body"):
            if parser.starts[tag] != 1 or parser.ends[tag] != 1:
                errors.append(f"Expected one complete {tag} element; found {parser.starts[tag]} starts and {parser.ends[tag]} ends.")
        for tag in ("script", "style"):
            if parser.starts[tag] != parser.ends[tag]:
                errors.append(f"Unclosed or duplicate closing {tag} element.")
        duplicates = sorted(key for key, count in parser.ids.items() if count > 1)
        if duplicates:
            errors.append("Duplicate element IDs: " + ", ".join(duplicates[:20]))
        if re.search(r"</html\s*>\s*\S", text, re.I):
            errors.append("Content appears after the document's closing html tag.")
        if "toISOString" in text and re.search(r"T00:00:00(?![Z+])", text):
            warnings.append("Local-midnight Date converted to UTC ISO may shift a calendar date. Verify date-only logic in the intended timezone.")
    else:
        warnings.append("No syntax parser for this file type; only text checks performed.")
    if len(text) > 200 and "\n" not in text and text.count("\\n") >= 5:
        warnings.append("Many literal backslash-n sequences without real newlines; inspect JSON escaping.")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "scope": "Static syntax/structure only. Does not execute code or verify facts, UI, or functionality."}
