#!/usr/bin/python3
"""Command substitutes copied ONLY into the credential-free disposable root."""

import json
import os
from pathlib import Path
import sys
import time

if not Path("/.recovery-fixture.json").is_file() or not Path("/.recovery-runtime.json").is_file():
    raise SystemExit("Fixture command refuses non-isolated execution")
identity = json.loads(Path("/.recovery-runtime.json").read_text())
if identity != {"device": Path("/").stat().st_dev, "inode": Path("/").stat().st_ino}:
    raise SystemExit("Fixture root identity mismatch")
STATE = Path("/fixture/state.json")
state = json.loads(STATE.read_text())
name = Path(sys.argv[0]).name
args = sys.argv[1:]
state.setdefault("commands", []).append([name, *args])
code = 0
output = ""


def flag(key):
    return bool(state.get(key))


def option(key):
    return args[args.index(key) + 1]


if name == "rpm":
    if args[-1] == "amazon-ssm-agent":
        output = "3.3.2746.0"
    elif flag("missing_package") and args[-1] == "nginx":
        code = 1
    if flag("block_bootstrap") and Path("/var/lib/aws-portfolio-deploy/recovery-required").exists():
        Path("/fixture/blocked.json").write_text(json.dumps({"pid": os.getpid(), "group": os.getpgrp()}))
        time.sleep(60)
elif name == "dnf":
    code = 99  # Package installation is never permitted in these fixtures.
elif name == "systemctl":
    verb, service = args[0], args[-1]
    active = state.setdefault("active", {"nginx": True, "amazon-cloudwatch-agent": True})
    if verb == "is-active":
        code = 0 if active[service] else 3
        output = "active" if active[service] else "inactive"
    elif verb == "is-enabled":
        output = "enabled"
    elif verb in {"start", "stop"}:
        active[service] = verb == "start"
    elif verb not in {"reload", "enable"}:
        code = 99
elif name == "nginx":
    if flag("nginx_invalid") or flag("rollback_nginx_failure") and flag("website_failed"):
        code = 1
elif name == "curl":
    state["http_calls"] = state.get("http_calls", 0) + 1
    if flag("website_http_failure") and not flag("website_failed"):
        state["website_failed"] = True
        code = 22
    elif flag("verification_http_failure") and "--write-out" in args and not flag("verification_failure_injected"):
        # Only verify-server requests a status code. Never shift this fault into rollback.
        state["verification_failure_injected"] = True
        state.setdefault("injected_faults", []).append("verification_http")
        code = 22
    else:
        if "--output" in args:
            Path(option("--output")).write_bytes(Path("/usr/share/nginx/html/index.html").read_bytes())
        if "--write-out" in args:
            output = "200"
elif name == "config-translator":
    if flag("translation_failure"):
        code = 1
    else:
        Path(option("--output")).write_bytes(Path(option("--input")).read_bytes())
elif name == "amazon-cloudwatch-agent":
    code = 1 if flag("schema_failure") else 0
elif name == "amazon-cloudwatch-agent-ctl":
    action = option("-a")
    if action == "status":
        running = state.get("active", {}).get("amazon-cloudwatch-agent", True)
        output = json.dumps({"status": "running" if running else "stopped", "configstatus": "configured"})
    elif action == "fetch-config":
        state["activations"] = state.get("activations", 0) + 1
        source = Path(option("-c").removeprefix("file:"))
        cached = Path("/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.d/file_amazon-cloudwatch-agent.json")
        cached.write_bytes(source.read_bytes())
        cached.chmod(0o600)
        code = 1 if state["activations"] <= state.get("activation_failures", 0) else 0
        state.setdefault("active", {})["amazon-cloudwatch-agent"] = code == 0
        if flag("consume_source") and code == 0:
            source.unlink()
    else:
        code = 99
else:
    code = 99
STATE.write_text(json.dumps(state))
if output:
    print(output)
raise SystemExit(code)
