#!/usr/bin/env python3
"""Offline project checks; use the deployment scripts' existing input contracts."""

import ast
import ipaddress
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[2]
SERVER_SCRIPTS = (
    "bootstrap.sh", "deploy-website.sh", "configure-monitoring.sh", "verify-server.sh"
)
TEXT_SUFFIXES = {".sh", ".py", ".md", ".tf", ".hcl", ".json", ".yml", ".yaml", ".html", ".css"}
FORBIDDEN_NAMES = {"credentials", "terraform.rc", ".terraformrc", "crash.log", "plan.out", "tfplan", "agents.md", "skill.md"}
FORBIDDEN_PARTS = {".aws", ".terraform", ".codex", ".agents", ".local", ".ci-tools", ".vscode", ".idea", ".pytest_cache", "__pycache__", "backup", "backups", "inventory", "artifacts", "tmp", "temp", ".tmp"}
PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "credential assignment": re.compile(
        r"(?i)\b(?:aws_secret_access_key|aws_session_token|aws_access_key_id|password|api_key)"
        r"[\s\"']*[:=]\s*[\"']?[A-Za-z0-9/+_=.-]{16,}"
    ),
    "AWS resource identifier": re.compile(r"\b(?:i|ami|vol|snap|vpc|subnet|sg|eni|rtb|rtbassoc|igw|sgr|eipalloc|eipassoc|nat|vpce|acl|tgw|dhcp)-[0-9a-f]{8,}\b"),
    "account identifier": re.compile(r"\b[0-9]{12}\b"),
    "email address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "personal Windows path": re.compile(r"(?i)\b[A-Z]:[\\/]|/[cC]/[Uu]sers/"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def repository_files():
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, check=True, stdout=subprocess.PIPE,
    )
    return sorted(set(result.stdout.decode("utf-8").strip("\0").split("\0")) - {""})


def source_hygiene():
    files = repository_files()
    require(files, "No repository source files found")
    for relative in files:
        path = PurePosixPath(relative)
        name = path.name.lower()
        forbidden = (
            bool({part.lower() for part in path.parts} & FORBIDDEN_PARTS)
            or name in FORBIDDEN_NAMES
            or name.startswith(".env")
            or ".tfstate" in name
            or name.endswith((".tfvars", ".tfvars.json", ".tfplan", ".plan", ".pem", ".key", ".p12", ".pfx", ".bak", ".backup", ".orig", ".log", ".zip", ".tar", ".tar.gz", "~"))
            or ".tfplan." in name
            or ".backup." in name or ".bak." in name
            or name.startswith("crash.") and name.endswith(".log")
            or name in {"override.tf", "override.tf.json"}
            or name.endswith(("_override.tf", "_override.tf.json"))
        )
        require(not forbidden, f"Forbidden credential/state/backup/local configuration path: {relative}")
        disk_path = ROOT / relative
        require(not disk_path.is_symlink() and disk_path.is_file(), f"Non-regular source: {relative}")
        require(not any(parent.is_symlink() for parent in disk_path.parents if parent != ROOT.parent), f"Symlink parent: {relative}")
        data = disk_path.read_bytes()
        # Scan all publishable files, including unfamiliar extensions, for secrets.
        text = data.decode("utf-8")
        require(not text.startswith("\ufeff"), f"UTF-8 BOM: {relative}")
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                raise ValueError(f"Possible {label}: {relative}:{line}; matched value withheld")
        for match in re.finditer(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", text):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            require(not address.is_global, f"Possible public IPv4 address: {relative}; value withheld")
        if path.suffix in TEXT_SUFFIXES or name in {".gitignore", ".gitattributes"}:
            if path.suffix in {".sh", ".py", ".yml", ".yaml", ".json", ".html", ".css"}:
                require(b"\r" not in data, f"Non-LF line ending: {relative}")
            require(not data or data.endswith(b"\n"), f"Missing final newline: {relative}")
            require(all(line == line.rstrip() for line in text.splitlines()), f"Trailing whitespace: {relative}")
            require(not re.search(r"^(?:<{7}|={7}|>{7})(?: |$)", text, re.M), f"Merge marker: {relative}")
        if path.suffix == ".py":
            ast.parse(text, filename=relative)
        if path.suffix == ".json":
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                require(not set(parsed) & {"Reservations", "Vpcs", "Subnets", "AccessKeyId", "SecretAccessKey", "SessionToken"}, f"Raw AWS inventory/credentials JSON: {relative}")
    require("terraform/.terraform.lock.hcl" in files, "Provider dependency lock file is missing or ignored")
    for script in SERVER_SCRIPTS:
        require(f"scripts/{script}" in files, f"Required server script missing: {script}")
    print(f"PASS: Source hygiene and LF checks ({len(files)} publishable files; ignored local files excluded).")


def script_contract(script, arguments):
    """Reuse the single existing Python input-validator heredoc, without Bash execution."""
    path = ROOT / "scripts" / script
    lines = path.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("if ! python3 - ") and "<<'PY'" in line]
    require(len(starts) == 1, f"Review input-validator extraction after changing {script}")
    start = starts[0] + 1
    end = lines.index("PY", start)
    code = "\n".join(lines[start:end])
    compiled = compile(code, str(path), "exec")
    previous = sys.argv
    try:
        sys.argv = [str(path)] + arguments
        exec(compiled, {"__name__": "__main__"})
    finally:
        sys.argv = previous


class PortfolioHTML(HTMLParser):
    """Strict explicit tag nesting and document checks for this static homepage."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    TAGS = VOID | {"html", "head", "body", "title", "style", "main", "div", "h1", "h2", "h3", "h4", "h5", "h6", "p", "section", "footer", "header", "nav", "a", "span", "strong", "em", "ul", "ol", "li", "pre", "code", "article", "aside", "figure", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.counts = {}
        self.doctype = 0

    def handle_decl(self, declaration):
        require(declaration.lower() == "doctype html" and not self.stack, "Unexpected HTML declaration")
        self.doctype += 1

    def handle_starttag(self, tag, attrs):
        require(tag in self.TAGS, f"Unsupported HTML tag (review validator when extending the page): {tag}")
        require(len(dict(attrs)) == len(attrs), f"Duplicate HTML attributes: {tag}")
        self.counts[tag] = self.counts.get(tag, 0) + 1
        if tag == "html":
            require(not self.stack and dict(attrs).get("lang"), "HTML root needs lang")
        elif tag in {"head", "body"}:
            require(self.stack == ["html"], f"Incorrect HTML parent: {tag}")
        else:
            require(self.stack, f"HTML tag outside document: {tag}")
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        require(tag in self.VOID, f"Non-void HTML tag is self-closing: {tag}")
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        require(self.stack and self.stack[-1] == tag, f"Mismatched HTML closing tag: {tag}")
        self.stack.pop()

    def handle_data(self, data):
        require(self.stack or not data.strip(), "Text outside HTML root")

    def validate(self):
        require(not self.stack and self.doctype == 1, "Unclosed tags or missing/duplicate HTML doctype")
        for tag in ("html", "head", "body", "title", "main", "h1"):
            require(self.counts.get(tag) == 1, f"Expected exactly one HTML {tag}")


def main():
    source_hygiene()
    # Absolute inputs make this reusable from any local working directory.
    homepage = str(ROOT / "website/index.html")
    script_contract("deploy-website.sh", [homepage, str(ROOT / "config/nginx/security.conf"), "deploy"])
    script_contract("configure-monitoring.sh", [str(ROOT / "config/cloudwatch/amazon-cloudwatch-agent.json")])
    script_contract("verify-server.sh", [homepage])
    parser = PortfolioHTML()
    parser.feed(Path(homepage).read_text(encoding="utf-8"))
    parser.close()
    parser.validate()
    print("PASS: Existing monitoring/website/security contracts and explicit HTML structure.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, AssertionError, KeyError, OSError, SyntaxError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
