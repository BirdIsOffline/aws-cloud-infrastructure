"""Run unchanged production code only inside a disposable, offline Linux root."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / ".local/tests"
INPUTS = (
    "scripts/bootstrap.sh", "scripts/deploy-website.sh", "scripts/configure-monitoring.sh",
    "scripts/verify-server.sh", "scripts/ssm/executor.py", "config/ssm/approved-release.json",
    "config/nginx/security.conf", "config/cloudwatch/amazon-cloudwatch-agent.json", "website/index.html",
)
MARKER = ".recovery-fixture.json"


def clean_environment():
    # Never inherit credentials, runner tokens, proxy settings, or Python/shell hooks.
    return {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": "/nonexistent", "LANG": "C", "LC_ALL": "C"}


def checked_root(root, nonce):
    root = Path(root)
    if not re.fullmatch(r"[0-9a-f]{32}", nonce):
        raise ValueError("Invalid fixture nonce")
    if root.parent != PARENT or not root.name.startswith("recovery-") or root.resolve() != root:
        raise ValueError("Fixture outside the intended private test directory")
    for path in (root, *root.parents):
        if path.is_symlink():
            raise ValueError("Symlink in fixture hierarchy")
    marker = root / MARKER
    value = marker.lstat()
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError("Unsafe fixture identity marker")
    if json.loads(marker.read_text()) != {"nonce": nonce, "format": 1}:
        raise ValueError("Fixture identity does not match")
    return root


def namespace_guard(previous, current):
    if set(previous) != {"net", "pid", "mnt"} or any(previous[k] == current[k] for k in previous):
        raise RuntimeError("Separate network, PID and mount namespaces are mandatory")


def namespaces():
    return {name: os.readlink("/proc/self/ns/" + name) for name in ("net", "pid", "mnt")}


def copy_file(root, source, destination, mode=0o644):
    target = root / destination.lstrip("/")
    if target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise ValueError("Unsafe fixture destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(mode)
    return target


def binary(root, source, destination=None):
    source = Path(source)
    copy_file(root, source, destination or str(source), 0o755)
    result = subprocess.run(["/usr/bin/ldd", str(source)], env=clean_environment(), capture_output=True, text=True, check=False)
    if result.returncode and "not a dynamic executable" not in result.stderr + result.stdout:
        raise RuntimeError("Cannot resolve a trusted system binary's dependencies")
    if "not found" in result.stdout:
        raise RuntimeError("Missing runtime library")
    for name in set(re.findall(r"(/[^\s()]+)", result.stdout)):
        copy_file(root, name, name, 0o755)


def build(root):
    os.chown(root, 0, 0)
    for relative in INPUTS:
        source = ROOT / relative
        if source.resolve() != source or not source.is_file() or source.stat().st_nlink != 1:
            raise RuntimeError("Non-regular fixture source or symlink parent")
    contract = json.loads((ROOT / "config/ssm/approved-release.json").read_text())
    for relative, spec in contract["files"].items():
        if relative not in INPUTS:
            raise RuntimeError("Unexpected release source")
        source = ROOT / relative
        if source.is_symlink() or source.stat().st_nlink != 1 or hashlib.sha256(source.read_bytes()).hexdigest() != spec["sha256"]:
            raise RuntimeError("Release source differs from approved bytes")
    for name in ("bash", "env", "install", "mktemp", "cmp", "realpath", "stat", "cp", "mv", "chmod", "chown", "rm", "rmdir", "date", "mkdir", "dirname"):
        source = shutil.which(name, path=clean_environment()["PATH"])
        if not source:
            raise RuntimeError("Missing system runtime prerequisite: " + name)
        binary(root, source, "/usr/bin/" + name)
    python = "/usr/bin/python3"
    binary(root, python, python)
    metadata = json.loads(subprocess.check_output([python, "-I", "-c", "import json,sysconfig;print(json.dumps({'stdlib':sysconfig.get_path('stdlib'),'extensions':sysconfig.get_config_var('DESTSHARED')}))"], env=clean_environment()))
    stdlib = Path(metadata["stdlib"])
    shutil.copytree(stdlib, root / str(stdlib).lstrip("/"), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages", "dist-packages", "test", "tests", "idlelib", "tkinter", "sitecustomize.py", "usercustomize.py"))
    for extension in Path(metadata["extensions"]).glob("*.so"):
        binary(root, extension)
    for relative in INPUTS:
        source = ROOT / relative
        target = copy_file(root, source, "/project/" + relative, 0o700 if relative.endswith(".sh") else 0o600)
        if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(target.read_bytes()).digest():
            raise RuntimeError("Fixture source integrity mismatch")
    for name in ("recovery_suite.py", "recovery_stub.py"):
        copy_file(root, ROOT / "tests" / name, "/suite/" + name)
    for directory in ("etc", "dev", "var/tmp", "var/lib", "var/backups", "fixture", "opt", "usr/sbin", "bin", "sbin"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "var/tmp").chmod(0o1777)
    (root / "dev/null").touch(mode=0o666)
    (root / "etc/passwd").write_text("root:x:0:0:fixture:/root:/usr/bin/bash\n")
    (root / "etc/group").write_text("root:x:0:\n")
    (root / "etc/nsswitch.conf").write_text("passwd: files\ngroup: files\nhosts: files\n")
    value = root.stat()
    (root / ".recovery-runtime.json").write_text(json.dumps({"device": value.st_dev, "inode": value.st_ino}))
    # No bind mounts, host /etc, home, /proc, devices, sockets, or credentials.


def drop_capabilities(last_capability):
    if not 5 <= last_capability < 64:
        raise RuntimeError("Unsupported kernel capability range")
    libc = ctypes.CDLL(None, use_errno=True)
    keep = (1 << 0) | (1 << 1) | (1 << 3) | (1 << 5)  # chown, DAC, owner, kill only
    for capability in range(last_capability + 1):
        if not keep & (1 << capability) and libc.prctl(24, capability, 0, 0, 0) != 0:
            if ctypes.get_errno() != 22:
                raise OSError("Cannot drop capability bounding set")
    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32), ("inheritable", ctypes.c_uint32)]
    data = (Data * 2)()
    data[0].effective = data[0].permitted = keep
    if libc.capset(ctypes.byref(Header(0x20080522, 0)), ctypes.byref(data)) != 0 or libc.prctl(38, 1, 0, 0, 0) != 0:
        raise OSError("Cannot constrain fixture privileges")


def child(root, nonce, previous):
    checked_root(root, nonce)
    namespace_guard(json.loads(previous), namespaces())
    if os.getpid() != 1 or os.geteuid() != 0:
        raise RuntimeError("Isolated PID namespace root required")
    last_capability = int(Path("/proc/sys/kernel/cap_last_cap").read_text())
    os.chroot(root)
    os.chdir("/")
    drop_capabilities(last_capability)
    env = clean_environment()
    env["RECOVERY_ISOLATED"] = nonce
    os.execve("/usr/bin/python3", ["python3", "-I", "-B", "/suite/recovery_suite.py"], env)


def supervise(root, nonce):
    root = checked_root(root, nonce)
    if os.geteuid() != 0:
        raise RuntimeError("Passwordless isolated runner privileges unavailable")
    try:
        build(root)
        cmd = ["/usr/bin/unshare", "--mount", "--net", "--pid", "--fork", "--propagation", "private",
               "/usr/bin/python3", "-I", "-B", str(Path(__file__).resolve()), "--child", str(root), nonce, json.dumps(namespaces())]
        process = subprocess.Popen(cmd, env=clean_environment(), start_new_session=True)
        try:
            return process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
            raise RuntimeError("Recovery suite exceeded its bounded runtime; no retry") from None
    finally:
        # Resolve and validate the exact workspace fixture again before deletion.
        checked_root(root, nonce)
        shutil.rmtree(root)


def main():
    if len(sys.argv) > 1:
        if len(sys.argv) == 4 and sys.argv[1] == "--supervise":
            return supervise(Path(sys.argv[2]), sys.argv[3])
        if len(sys.argv) == 5 and sys.argv[1] == "--child":
            child(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
            return 1
        raise ValueError("Unexpected runner arguments")
    if sys.platform != "linux":
        print("NOT EXECUTED: isolated recovery suite requires Linux namespaces and chroot; hosted Ubuntu CI is mandatory.")
        return 0
    for tool in ("/usr/bin/python3", "/usr/bin/unshare", "/usr/bin/ldd"):
        if not Path(tool).is_file():
            raise RuntimeError("Missing Linux isolation prerequisite")
    for path in (ROOT / ".local", PARENT):
        if path.is_symlink():
            raise ValueError("Unsafe private test parent")
        path.mkdir(mode=0o700, exist_ok=True)
    nonce = uuid.uuid4().hex
    root = Path(tempfile.mkdtemp(prefix="recovery-", dir=PARENT))
    marker = root / MARKER
    marker.write_text(json.dumps({"nonce": nonce, "format": 1}))
    marker.chmod(0o600)
    prefix = [] if os.geteuid() == 0 else ["sudo", "-n", "--"]
    result = subprocess.run(prefix + ["/usr/bin/python3", "-I", "-B", str(Path(__file__).resolve()), "--supervise", str(root), nonce], env=clean_environment(), check=False)
    if root.exists():
        # Failed privilege setup can leave an empty, user-owned fixture only.
        checked_root(root, nonce)
        if list(root.iterdir()) == [marker] and root.stat().st_uid == os.getuid():
            marker.unlink()
            root.rmdir()
    return result.returncode


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("FAIL: isolated recovery runner: " + str(exc), file=sys.stderr)
        sys.exit(1)
