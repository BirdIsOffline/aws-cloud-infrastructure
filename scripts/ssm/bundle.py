#!/usr/bin/env python3
"""Create/check a pinned local bundle. No AWS, GitHub, or deployment operations."""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import runpy
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def create(root=ROOT):
    contract = json.loads((root / "config/ssm/approved-release.json").read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    entries = []
    for relative, spec in sorted(contract["files"].items()):
        path = root / relative
        if path.is_symlink() or not path.is_file() or any(parent.is_symlink() for parent in path.parents):
            raise ValueError("Non-regular bundle source")
        if path.stat().st_nlink != 1:
            raise ValueError("Hard-linked bundle source")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != spec["sha256"]:
            raise ValueError("Source differs from approved release; executor revision review required")
        if data != subprocess.check_output(["git", "show", commit + ":" + relative], cwd=root):
            raise ValueError("Bundle source differs from the immutable commit")
        entries.append({"path": relative, "type": "file", "mode": spec["mode"], "sha256": spec["sha256"], "content": data.decode("utf-8")})
    envelope = json.dumps({"commit": commit, "files": entries}, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.b64encode(gzip.compress(envelope, mtime=0)).decode()
    namespace = runpy.run_path(str(root / "scripts/ssm/executor.py"))
    namespace["decode_bundle"](encoded, contract)
    return encoded, contract


def document(root=ROOT):
    template = (root / "config/ssm/deploy-server.json").read_text()
    contract = json.dumps(json.loads((root / "config/ssm/approved-release.json").read_text()), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return template.replace("__EXECUTOR_BASE64__", base64.b64encode((root / "scripts/ssm/executor.py").read_bytes()).decode()).replace("__CONTRACT_BASE64__", base64.b64encode(contract.encode()).decode())


def document_name(rendered, contract):
    prefix = contract["document_name_prefix"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,63}", prefix) or prefix.lower().startswith(("aws", "amazon", "amzn")):
        raise ValueError("Invalid or AWS-reserved custom document prefix")
    return prefix + "-" + hashlib.sha256(rendered.encode()).hexdigest()


def check(root=ROOT):
    encoded, contract = create(root)
    rendered = document(root)
    document_name(rendered, contract)
    parsed = json.loads(rendered)
    if parsed["schemaVersion"] != "2.2" or any(parameter["interpolationType"] != "ENV_VAR" for parameter in parsed["parameters"].values()):
        raise ValueError("SSM interpolation/schema contract")
    # Budget source + maximum parameter data + serialization overhead conservatively.
    total = len(rendered.encode()) + contract["limits"]["encoded_bytes"] + 1024
    if total >= 60 * 1024:
        raise ValueError("Executor and maximum bundle exceed conservative SSM document budget")
    if "{{" in parsed["mainSteps"][0]["inputs"]["runCommand"][0]:
        raise ValueError("Unsafe command parameter interpolation")
    return {"files": len(contract["files"]), "encoded_bundle_bytes": len(encoded), "document_bytes": len(rendered.encode()), "maximum_combined_budget_bytes": total, "execution_timeout_seconds": 900}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Explicit local JSON parameter output; keep under ignored .local storage")
    args = parser.parse_args()
    summary = check()
    if args.output:
        if not args.output.resolve().is_relative_to(ROOT / ".local"):
            raise ValueError("Bundle parameter output must remain under ignored .local storage")
        encoded, _ = create()
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"Bundle": [encoded]}, stream)
            stream.write("\n")
    print(json.dumps(summary))
