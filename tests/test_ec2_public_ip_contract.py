"""Guard the one approved lifecycle exception; Terraform validates HCL semantics."""

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r'\s+|\#[^\n]*|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[\w-]+|.', re.S)


def tokens(source):
    return [value for value in TOKEN.findall(source)
            if not value.isspace() and not value.startswith(("#", "//", "/*"))]


def body(values, prefix):
    starts = [i for i in range(len(values) - len(prefix))
              if values[i:i + len(prefix)] == prefix and values[i + len(prefix)] == "{"]
    if len(starts) != 1:
        raise ValueError("Expected one matching configuration block")
    start = starts[0] + len(prefix) + 1
    depth = 1
    for end in range(start, len(values)):
        depth += (values[end] == "{") - (values[end] == "}")
        if depth == 0:
            return values[start:end]
    raise ValueError("Unclosed configuration block")


def attribute(values, name):
    depth = 0
    found = []
    for i, value in enumerate(values):
        if depth == 0 and value == name and values[i + 1:i + 2] == ["="]:
            start = i + 2
            if values[start] == "[":
                end = values.index("]", start)
                found.append(values[start:end + 1])
            else:
                found.append(values[start:start + 1])
        depth += (value == "{") - (value == "}")
    if len(found) != 1:
        raise ValueError("Expected one literal attribute")
    return found[0]


def validate_contract(source):
    resource = body(tokens(source), ["resource", '"aws_instance"', '"web"'])
    lifecycle = body(resource, ["lifecycle"])
    if attribute(resource, "associate_public_ip_address") != ["true"]:
        raise ValueError("Public IPv4 launch intent must remain true")
    if attribute(lifecycle, "prevent_destroy") != ["true"]:
        raise ValueError("Destruction protection must remain enabled")
    if attribute(lifecycle, "ignore_changes") != ["[", "associate_public_ip_address", "]"]:
        raise ValueError("Only the public-IP observation may be ignored")


FIXTURE = '''resource "aws_instance" "web" {
  associate_public_ip_address = true
  lifecycle {
    prevent_destroy = true
    ignore_changes = [associate_public_ip_address]
  }
}
'''


class PublicIPv4Contract(unittest.TestCase):
    def test_current_instance_contract(self):
        validate_contract((ROOT / "terraform/compute.tf").read_text(encoding="utf-8"))

    def test_no_other_lifecycle_exceptions(self):
        count = sum(tokens(path.read_text(encoding="utf-8")).count("ignore_changes")
                    for path in (ROOT / "terraform").glob("*.tf"))
        self.assertEqual(count, 1, "Unrelated drift must not be ignored")

    def test_rejects_ignore_all(self):
        with self.assertRaises(ValueError):
            validate_contract(FIXTURE.replace("[associate_public_ip_address]", "all"))

    def test_rejects_extra_ignored_setting(self):
        with self.assertRaises(ValueError):
            validate_contract(FIXTURE.replace("[associate_public_ip_address]",
                                              "[associate_public_ip_address, metadata_options]"))

    def test_rejects_removed_or_disabled_guard(self):
        for replacement in ("", "prevent_destroy = false"):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                validate_contract(FIXTURE.replace("prevent_destroy = true", replacement))

    def test_rejects_disabled_launch_assignment(self):
        with self.assertRaises(ValueError):
            validate_contract(FIXTURE.replace("associate_public_ip_address = true",
                                              "associate_public_ip_address = false"))

    def test_accepts_comments_and_reordered_multiline_list(self):
        source = FIXTURE.replace("prevent_destroy = true\n    ignore_changes = [associate_public_ip_address]",
                                 "ignore_changes = [\n # Approved attribute only\n associate_public_ip_address\n]\n"
                                 "// Keep the guard\n prevent_destroy = true")
        validate_contract(source)


if __name__ == "__main__":
    unittest.main()
