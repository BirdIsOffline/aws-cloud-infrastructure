#!/usr/bin/env python3
"""Install one verified official Terraform release on the Ubuntu CI runner."""

import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = "1.17.2"
ARCHIVE = f"terraform_{VERSION}_linux_amd64.zip"
ARCHIVE_SHA256 = "e6f16b2f0b137ee5729caa8c4e79a3bae4ee261acd198a1fcfa8584a6296605b"
SIGNING_FINGERPRINT = "C874011F0AB405110D02105534365D9472D7468F"
KEY_URL = "https://www.hashicorp.com/.well-known/pgp-key.txt"
RELEASE_URL = f"https://releases.hashicorp.com/terraform/{VERSION}/"
MANIFEST = f"terraform_{VERSION}_SHA256SUMS"
REJECTED_STATUSES = frozenset({
    "BADSIG", "ERRSIG", "NO_PUBKEY", "NODATA", "FAILURE", "EXPSIG",
    "EXPKEYSIG", "REVKEYSIG", "SIGEXPIRED", "KEYREVOKED",
})


def status_names(status):
    """Return known status labels only; never return key IDs, UIDs or raw output."""
    known = REJECTED_STATUSES | {"GOODSIG", "VALIDSIG", "KEYEXPIRED"}
    return sorted({fields[1] for line in status.splitlines()
                   if line.startswith("[GNUPG:] ") and len(fields := line.split()) > 1
                   and fields[1] in known})


class VerificationError(ValueError):
    """An artifact or verification prerequisite did not satisfy the contract."""


def require(condition, message):
    if not condition:
        raise VerificationError(message)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(url, target, limit):
    """Fetch only fixed HTTPS URLs, with bounded reads and no redirect fallback."""
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(url, timeout=30) as response, target.open("xb") as output:
        require(response.status == 200, "Artifact download did not return HTTP 200")
        size = 0
        while block := response.read(65536):
            size += len(block)
            require(size <= limit, "Artifact exceeds its download size limit")
            output.write(block)
        require(size > 0, "Artifact download is empty")


def gpg(home, arguments):
    executable = shutil.which("gpg")
    require(executable is not None, "GPG is required; unverified installation is forbidden")
    result = subprocess.run(
        [executable, "--no-options", "--homedir", str(home), "--batch", "--no-tty",
         "--no-auto-key-retrieve", "--no-auto-key-import", "--no-autostart", *arguments],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    summary = ", ".join(status_names(result.stdout)) or "NO_RECOGNIZED_STATUS"
    require(result.returncode == 0,
            f"GPG verification command failed (exit {result.returncode}; status {summary})")
    return result.stdout


def verify_key_listing(listing):
    primary = []
    pending = False
    for line in listing.splitlines():
        fields = line.split(":")
        require(fields[0] not in {"sec", "ssb"}, "Expected a public release key")
        if fields[0] == "pub":
            require(len(fields) > 1 and fields[1] not in {"r", "e", "d"},
                    "Release key is revoked, expired or disabled")
            require(not pending, "Missing primary key fingerprint")
            pending = True
        elif fields[0] == "fpr" and pending:
            require(len(fields) > 9, "Malformed key fingerprint")
            primary.append(fields[9])
            pending = False
    require(not pending and primary == [SIGNING_FINGERPRINT],
            "Release signing-key fingerprint mismatch")


def verify_signature_status(status):
    records = [line.split()[1:] for line in status.splitlines()
               if line.startswith("[GNUPG:] ")]
    # KEYEXPIRED may describe an unused subkey; EXPKEYSIG identifies an expired signer.
    rejected = sorted(set(status_names(status)) & REJECTED_STATUSES)
    require(not rejected, "Manifest signature rejected: " + ", ".join(rejected))
    signatures = [record for record in records if record and record[0] == "VALIDSIG"]
    require(len(signatures) == 1, "Expected exactly one valid manifest signature")
    signature = signatures[0]
    require(len(signature) in {10, 11}, "Malformed manifest signature status")
    primary = signature[10] if len(signature) == 11 else signature[1]
    require(primary == SIGNING_FINGERPRINT, "Manifest signer fingerprint mismatch")
    require(signature[8] in {"8", "9", "10"}, "Manifest signature requires SHA-256 or stronger")


def verify_signature(directory):
    home = directory / "gnupg"
    home.mkdir(mode=0o700)
    key = directory / "release-key.asc"
    listing = gpg(home, ["--with-colons", "--show-keys", str(key)])
    verify_key_listing(listing)
    gpg(home, ["--import", str(key)])
    status = gpg(home, ["--status-fd", "1", "--verify",
                       str(directory / (MANIFEST + ".sig")), str(directory / MANIFEST)])
    verify_signature_status(status)


def verify_archive(directory):
    entries = []
    for line in (directory / MANIFEST).read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        require(match is not None, "Malformed signed checksum manifest")
        if match[2] == ARCHIVE:
            entries.append(match[1])
    require(entries == [ARCHIVE_SHA256], "Signed archive entry does not match the pinned release")
    with (directory / ARCHIVE).open("rb") as archive:
        actual = hashlib.file_digest(archive, "sha256").hexdigest()
    require(actual == ARCHIVE_SHA256, "Terraform archive SHA-256 mismatch")


def extract_binary(archive, destination):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        require(len(entries) == 2 and {entry.filename for entry in entries} == {"terraform", "LICENSE.txt"},
                "Unexpected Terraform archive entries")
        for entry in entries:
            kind = stat.S_IFMT(entry.external_attr >> 16)
            require(kind in {0, stat.S_IFREG} and 0 < entry.file_size <= 160 * 1024 * 1024,
                    "Unexpected archive file type or size")
        with package.open("terraform") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target)
    destination.chmod(0o755)


def install(runner_temp, github_path):
    with tempfile.TemporaryDirectory(prefix="terraform-verify-", dir=runner_temp) as temporary:
        directory = Path(temporary)
        download(KEY_URL, directory / "release-key.asc", 256 * 1024)
        download(RELEASE_URL + MANIFEST, directory / MANIFEST, 1024 * 1024)
        download(RELEASE_URL + MANIFEST + ".sig", directory / (MANIFEST + ".sig"), 64 * 1024)
        verify_signature(directory)
        download(RELEASE_URL + ARCHIVE, directory / ARCHIVE, 64 * 1024 * 1024)
        verify_archive(directory)
        installed = Path(tempfile.mkdtemp(prefix="terraform-bin-", dir=runner_temp))
        try:
            extract_binary(directory / ARCHIVE, installed / "terraform")
            with github_path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(str(installed) + "\n")
        except BaseException:
            shutil.rmtree(installed)
            raise
    print(f"PASS: Terraform {VERSION} signature and pinned SHA-256 verified; installed linux_amd64.")


def main():
    require(sys.platform == "linux" and platform.machine() == "x86_64",
            "Installer supports only the Linux x86_64 CI runner")
    runner_temp = Path(os.environ["RUNNER_TEMP"])
    github_path = Path(os.environ["GITHUB_PATH"])
    require(runner_temp.is_dir() and github_path.is_file(), "Missing GitHub runner paths")
    install(runner_temp, github_path)


if __name__ == "__main__":
    try:
        main()
    except (VerificationError, OSError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, VerificationError) else type(error).__name__
        print(f"ERROR: Terraform installation stopped: {message}", file=sys.stderr)
        sys.exit(1)
