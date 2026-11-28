"""Offline artifact rejection tests; real GPG checks run on hosted Linux."""

import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("terraform_installer", ROOT / "scripts/ci/install_terraform.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
FIXTURE = ROOT / "tests/fixtures/terraform-release.json"


def key_listing(fingerprint=installer.SIGNING_FINGERPRINT, validity="-"):
    return f"pub:{validity}:4096:1:release-key:::::::\nfpr:::::::::{fingerprint}:\n"


def signature_status(fingerprint=installer.SIGNING_FINGERPRINT):
    return f"[GNUPG:] VALIDSIG {fingerprint} 2026-11-01 1793491200 0 4 0 1 8 00 {fingerprint}\n"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".local/tests"
        parent.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="terraform-verifier-", dir=parent)
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def archive(self, entries=None):
        path = self.directory / installer.ARCHIVE
        with zipfile.ZipFile(path, "w") as package:
            for name, content, mode in entries or [
                ("terraform", b"synthetic executable, never run", stat.S_IFREG | 0o755),
                ("LICENSE.txt", b"synthetic license", stat.S_IFREG | 0o644),
            ]:
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = mode << 16
                package.writestr(entry, content)
        return path

    def manifest(self, digest=None, extra=""):
        data = f"{digest or installer.ARCHIVE_SHA256}  {installer.ARCHIVE}\n" + extra
        (self.directory / installer.MANIFEST).write_text(data, encoding="ascii")

    def test_expected_primary_key_and_authorized_subkey_are_accepted(self):
        installer.verify_key_listing(key_listing() + "sub:::::::::::\nfpr:::::::::" + "A" * 40 + ":\n")
        status = signature_status().replace("VALIDSIG " + installer.SIGNING_FINGERPRINT, "VALIDSIG " + "A" * 40)
        installer.verify_signature_status(status)

    def test_wrong_extra_missing_and_unusable_primary_keys_are_rejected(self):
        listings = ["", key_listing("A" * 40), key_listing() * 2,
                    "pub:-:4096:1:release-key:::::::\n", key_listing(validity="e"),
                    key_listing(validity="r"), key_listing(validity="d"), "sec:::::::::::\n"]
        for listing in listings:
            with self.subTest(listing=listing), self.assertRaises(installer.VerificationError):
                installer.verify_key_listing(listing)

    def test_missing_duplicate_wrong_and_weak_signatures_are_rejected(self):
        statuses = ["[GNUPG:] GOODSIG key release\n", signature_status() * 2,
                    signature_status("A" * 40), signature_status().replace(" 1 8 00 ", " 1 2 00 "),
                    "[GNUPG:] VALIDSIG incomplete\n"]
        for status in statuses:
            with self.subTest(status=status), self.assertRaises(installer.VerificationError):
                installer.verify_signature_status(status)

    def test_signature_failure_expiration_and_revocation_fail_closed(self):
        for failure in ["BADSIG", "ERRSIG", "NO_PUBKEY", "NODATA", "FAILURE", "EXPSIG",
                        "EXPKEYSIG", "REVKEYSIG", "SIGEXPIRED", "KEYREVOKED"]:
            with self.subTest(failure=failure), self.assertRaises(installer.VerificationError):
                installer.verify_signature_status(signature_status() + "[GNUPG:] " + failure + " key\n")

    def test_unused_expired_subkeys_allow_only_an_otherwise_valid_signature(self):
        for expiry in ("[GNUPG:] KEYEXPIRED 1640995200\n",
                       "[GNUPG:] KEYEXPIRED 20220101T000000\n"):
            with self.subTest(expiry=expiry):
                installer.verify_signature_status(expiry + signature_status() + expiry)
                with self.assertRaises(installer.VerificationError):
                    installer.verify_signature_status(expiry)
                with self.assertRaises(installer.VerificationError):
                    installer.verify_signature_status(expiry + signature_status("A" * 40))
                with self.assertRaises(installer.VerificationError):
                    installer.verify_signature_status(expiry + signature_status().replace(" 1 8 00 ", " 1 2 00 "))

    def test_actual_signer_and_signature_failures_override_unused_subkey_expiry(self):
        for code in ("EXPKEYSIG", "REVKEYSIG", "KEYREVOKED", "EXPSIG", "SIGEXPIRED", "BADSIG"):
            status = "[GNUPG:] KEYEXPIRED 1640995200\n" + signature_status() + f"[GNUPG:] {code} unneeded-detail\n"
            with self.subTest(code=code), self.assertRaisesRegex(installer.VerificationError, f"^Manifest signature rejected: {code}$"):
                installer.verify_signature_status(status)

    def test_rejection_diagnostics_contain_only_known_status_labels(self):
        raw = "unneeded-raw-output"
        status = f"[GNUPG:] BADSIG {raw}\n[GNUPG:] UNKNOWN_{raw} hidden\n[GNUPG:] REVKEYSIG {raw}\n"
        with self.assertRaises(installer.VerificationError) as failure:
            installer.verify_signature_status(signature_status() + status)
        self.assertEqual(str(failure.exception), "Manifest signature rejected: BADSIG, REVKEYSIG")
        with mock.patch.object(installer.shutil, "which", return_value="synthetic-gpg"), \
                mock.patch.object(installer.subprocess, "run", return_value=mock.Mock(returncode=2, stdout=status, stderr=raw)):
            with self.assertRaises(installer.VerificationError) as command_failure:
                installer.gpg(self.directory, [])
        self.assertEqual(str(command_failure.exception), "GPG verification command failed (exit 2; status BADSIG, REVKEYSIG)")
        self.assertNotIn(raw, str(command_failure.exception))

    def test_gpg_failure_missing_tool_and_timeout_do_not_fall_back(self):
        with mock.patch.object(installer.shutil, "which", return_value=None), self.assertRaises(installer.VerificationError):
            installer.gpg(self.directory, [])
        with mock.patch.object(installer.shutil, "which", return_value="synthetic-gpg"):
            with mock.patch.object(installer.subprocess, "run", return_value=mock.Mock(returncode=2, stdout="")), self.assertRaises(installer.VerificationError):
                installer.gpg(self.directory, [])
            with mock.patch.object(installer.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic-gpg", 30)), self.assertRaises(subprocess.TimeoutExpired):
                installer.gpg(self.directory, [])

    def test_signed_manifest_must_have_one_exact_pinned_archive_entry(self):
        cases = ["", "A" * 64 + "  " + installer.ARCHIVE + "\n",
                 "0" * 64 + "  " + installer.ARCHIVE + "\n",
                 installer.ARCHIVE_SHA256 + "  other.zip\n",
                 (installer.ARCHIVE_SHA256 + "  " + installer.ARCHIVE + "\n") * 2,
                 installer.ARCHIVE_SHA256 + "  path/" + installer.ARCHIVE + "\n"]
        for content in cases:
            (self.directory / installer.MANIFEST).write_text(content, encoding="ascii")
            with self.subTest(content=content), self.assertRaises(installer.VerificationError):
                installer.verify_archive(self.directory)

    def test_tampered_and_truncated_archive_hashes_are_rejected(self):
        self.manifest()
        for content in [b"", b"truncated archive", b"tampered archive"]:
            (self.directory / installer.ARCHIVE).write_bytes(content)
            with self.subTest(content=content), self.assertRaises(installer.VerificationError):
                installer.verify_archive(self.directory)

    def test_valid_fixture_hash_and_safe_extraction(self):
        archive = self.archive()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.manifest(digest)
        with mock.patch.object(installer, "ARCHIVE_SHA256", digest):
            installer.verify_archive(self.directory)
        destination = self.directory / "installed-terraform"
        installer.extract_binary(archive, destination)
        self.assertEqual(destination.read_bytes(), b"synthetic executable, never run")

    def test_unexpected_traversal_duplicate_symlink_and_oversized_entries_are_rejected(self):
        regular = stat.S_IFREG | 0o644
        cases = [[("../terraform", b"bad", regular), ("LICENSE.txt", b"test", regular)],
                 [("terraform", b"one", regular), ("terraform", b"two", regular)],
                 [("terraform", b"destination", stat.S_IFLNK | 0o777), ("LICENSE.txt", b"test", regular)],
                 [("terraform", b"", regular), ("LICENSE.txt", b"test", regular)],
                 [("terraform", b"test", regular), ("LICENSE.txt", b"test", regular), ("extra", b"bad", regular)]]
        for entries in cases:
            destination = self.directory / "must-not-exist"
            if len({entry[0] for entry in entries}) != len(entries):
                with self.assertWarnsRegex(UserWarning, "Duplicate name"):
                    archive = self.archive(entries)
            else:
                archive = self.archive(entries)
            with self.subTest(entries=entries), self.assertRaises(installer.VerificationError):
                installer.extract_binary(archive, destination)
            self.assertFalse(destination.exists())
        archive = self.archive()
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
        entries[0].file_size = 160 * 1024 * 1024 + 1
        with mock.patch.object(installer.zipfile, "ZipFile") as factory:
            factory.return_value.__enter__.return_value.infolist.return_value = entries
            with self.assertRaises(installer.VerificationError):
                installer.extract_binary(archive, self.directory / "must-not-exist")

    def test_verification_failure_never_extracts_or_exports_a_path(self):
        for failure in ("signature", "hash"):
            github_path = self.directory / (failure + "-path")
            github_path.write_bytes(b"")
            with mock.patch.object(installer, "download"), \
                    mock.patch.object(installer, "verify_signature", side_effect=installer.VerificationError("bad signature") if failure == "signature" else None) as signature, \
                    mock.patch.object(installer, "verify_archive", side_effect=installer.VerificationError("bad hash") if failure == "hash" else None) as archive, \
                    mock.patch.object(installer, "extract_binary") as extract:
                with self.assertRaises(installer.VerificationError):
                    installer.install(self.directory, github_path)
                signature.assert_called_once()
                self.assertEqual(archive.call_count, int(failure == "hash"))
                extract.assert_not_called()
            self.assertEqual(github_path.read_bytes(), b"")
            self.assertEqual(list(self.directory.glob("terraform-bin-*")), [])

    def test_successful_install_verifies_before_extraction_and_path_export(self):
        events = []
        github_path = self.directory / "github-path"
        github_path.write_bytes(b"")
        def extracted(archive, destination):
            self.assertEqual(events, ["signature", "hash"])
            self.assertEqual(github_path.read_bytes(), b"")
            destination.write_bytes(b"synthetic, never execute")
            events.append("extract")
        with mock.patch.object(installer, "download") as download, \
                mock.patch.object(installer, "verify_signature", side_effect=lambda _: events.append("signature")), \
                mock.patch.object(installer, "verify_archive", side_effect=lambda _: events.append("hash")), \
                mock.patch.object(installer, "extract_binary", side_effect=extracted), \
                mock.patch.object(installer.sys, "stdout", io.StringIO()):
            installer.install(self.directory, github_path)
        self.assertEqual(events, ["signature", "hash", "extract"])
        self.assertEqual(download.call_count, 4)
        self.assertEqual([call.args[0] for call in download.call_args_list], [
            installer.KEY_URL, installer.RELEASE_URL + installer.MANIFEST,
            installer.RELEASE_URL + installer.MANIFEST + ".sig", installer.RELEASE_URL + installer.ARCHIVE])
        self.assertTrue((Path(github_path.read_text().strip()) / "terraform").is_file())

    def test_failed_extraction_removes_partial_install_and_exports_nothing(self):
        github_path = self.directory / "github-path"
        github_path.write_bytes(b"")
        with mock.patch.object(installer, "download"), mock.patch.object(installer, "verify_signature"), \
                mock.patch.object(installer, "verify_archive"), \
                mock.patch.object(installer, "extract_binary", side_effect=zipfile.BadZipFile("synthetic")):
            with self.assertRaises(zipfile.BadZipFile):
                installer.install(self.directory, github_path)
        self.assertEqual(github_path.read_bytes(), b"")
        self.assertEqual(list(self.directory.glob("terraform-bin-*")), [])

    def test_empty_oversized_and_non_200_downloads_fail(self):
        for content, status, limit in [(b"", 200, 5), (b"123456", 200, 5), (b"test", 204, 5)]:
            target = self.directory / "download"
            target.unlink(missing_ok=True)
            response = io.BytesIO(content)
            response.status = status
            with mock.patch.object(installer.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = response
                with self.subTest(status=status, size=len(content)), self.assertRaises(installer.VerificationError):
                    installer.download("https://example.invalid/fixture", target, limit)

    def test_download_redirects_are_not_followed(self):
        self.assertIsNone(installer.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.invalid/"))

    def test_wrong_platform_and_missing_ci_paths_fail_before_download(self):
        with mock.patch.object(installer, "install") as install:
            with mock.patch.object(installer.sys, "platform", "win32"), self.assertRaises(installer.VerificationError):
                installer.main()
            with mock.patch.object(installer.sys, "platform", "linux"), mock.patch.object(installer.platform, "machine", return_value="aarch64"), self.assertRaises(installer.VerificationError):
                installer.main()
            with mock.patch.object(installer.sys, "platform", "linux"), mock.patch.object(installer.platform, "machine", return_value="x86_64"), mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(KeyError):
                installer.main()
            install.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "Real GPG release-signature verification requires Linux")
    def test_real_gpg_accepts_official_signature_and_rejects_tampering(self):
        self.assertIsNotNone(shutil.which("gpg"), "Linux CI must provide GPG; no bypass is allowed")
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        data = {}
        for name, entry in fixture["files"].items():
            data[name] = base64.b64decode(entry["base64"], validate=True)
            self.assertEqual(hashlib.sha256(data[name]).hexdigest(), entry["sha256"])
        for case in ("valid", "manifest-tamper", "signature-tamper"):
            directory = self.directory / case
            directory.mkdir(mode=0o700)
            (directory / "release-key.asc").write_bytes(data["key"])
            (directory / installer.MANIFEST).write_bytes(data["manifest"] + (b"tampered\n" if case == "manifest-tamper" else b""))
            signature = data["signature"]
            if case == "signature-tamper":
                signature = signature[:-1] + bytes([signature[-1] ^ 1])
            (directory / (installer.MANIFEST + ".sig")).write_bytes(signature)
            with self.subTest(case=case):
                if case == "valid":
                    installer.verify_signature(directory)
                    self.assertEqual(stat.S_IMODE((directory / "gnupg").stat().st_mode), 0o700)
                    # Negative fixture only: move verification past the pinned key's 2030 expiry.
                    expired = subprocess.run(
                        [shutil.which("gpg"), "--no-options", "--homedir", str(directory / "gnupg"),
                         "--batch", "--no-tty", "--no-auto-key-retrieve", "--no-auto-key-import",
                         "--no-autostart", "--faked-system-time", "20310101T000000", "--status-fd", "1",
                         "--verify", str(directory / (installer.MANIFEST + ".sig")), str(directory / installer.MANIFEST)],
                        capture_output=True, text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertIn("EXPKEYSIG", installer.status_names(expired.stdout))
                    with self.assertRaisesRegex(installer.VerificationError, "EXPKEYSIG"):
                        installer.verify_signature_status(expired.stdout)
                else:
                    with self.assertRaises(installer.VerificationError):
                        installer.verify_signature(directory)


if __name__ == "__main__":
    unittest.main()
