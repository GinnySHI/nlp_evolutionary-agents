"""Reproduce software-2 checks in a fresh copy using the project sandbox."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New output directory; must not exist")
    parser.add_argument("--sandbox", choices=("auto", "macos", "docker"), default="auto")
    args = parser.parse_args()
    evidence = Path(__file__).resolve().parent
    repo = evidence.parents[2]
    artifacts = repo / "deliverables/course-deepseek-20261123/software-2"
    sys.path.insert(0, str(repo))
    from evoagents.sandbox import Sandbox

    manifest = json.loads((evidence / "artifact-manifest.json").read_text())
    for name, expected in manifest["files"].items():
        actual = hashlib.sha256((artifacts / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Delivered file does not match recorded evidence: {name}")

    if args.output:
        workspace = args.output.resolve()
        workspace.mkdir(parents=True, exist_ok=False)
    else:
        scratch = repo / "reports/private"
        scratch.mkdir(parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix="software-2-review-", dir=scratch))
    for name in manifest["files"]:
        shutil.copyfile(artifacts / name, workspace / name)
    shutil.copyfile(evidence / "checkpoint-120/review_software2.py", workspace / "review_software2.py")
    result = Sandbox(workspace, backend=args.sandbox).run_python("review_software2.py", timeout=60)
    (workspace / "sandbox-result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["stdout"], end="")
    if result["stderr"]:
        print(result["stderr"], file=sys.stderr, end="")
    print(f"Fresh evidence: {workspace}")
    if not result["ok"]:
        return 1
    assessment = json.loads((workspace / "software-2-result.json").read_text())
    # Date interaction and chart appearance await the separate browser check.
    return 1 if any(item["status"] == "fail" for item in assessment["criteria"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
