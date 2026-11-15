import json
import shutil
import subprocess
import sys

import pytest

from spdxify.cli import main
from spdxify.verify import verify


def run(capsys, *argv):
    rc = main(list(argv))
    return rc, capsys.readouterr()


def test_check_text_and_exit(mono, capsys):
    rc, out = run(capsys, "check", str(mono), "--no-color")
    assert rc == 1
    assert "PL003" in out.out and "6 project(s): 2 error" in out.out


def test_check_fail_on_error_only(mono, capsys):
    rc, _ = run(capsys, "check", str(mono / "core"), "--fail-on", "error")
    assert rc == 0
    rc, _ = run(capsys, "check", str(mono / "api"), "--fail-on", "error")
    assert rc == 1


def test_check_ignore(mono, capsys):
    rc, out = run(capsys, "check", str(mono / "api"), "--ignore", "PL003,PL008")
    assert rc == 0


def test_json(mono, capsys):
    rc, out = run(capsys, "check", str(mono), "--format", "json")
    data = {p["project"]: p for p in json.loads(out.out)}
    assert data["acme-core"]["suggested_license"] == "MIT"
    assert data["acme-api"]["findings"][0]["rule"] == "PL003"


def test_github_annotations(mono, capsys):
    rc, out = run(capsys, "check", str(mono / "api"), "--format", "github")
    assert out.out.startswith("::error file=")
    assert "title=spdxify PL003" in out.out


def test_fix_dry_run_then_write(mono, capsys):
    before = (mono / "core" / "pyproject.toml").read_text()
    rc, out = run(capsys, "fix", str(mono / "core"), "--no-color")
    assert rc == 0 and '+license = "MIT"' in out.out
    assert (mono / "core" / "pyproject.toml").read_text() == before
    rc, out = run(capsys, "fix", str(mono / "core"), "--write", "--no-color")
    assert "fixed" in out.out
    rc, out = run(capsys, "check", str(mono / "core"))
    assert rc == 0


def test_fix_unresolved_exit(mono, capsys):
    rc, out = run(capsys, "fix", str(mono / "gis"))
    assert rc == 1 and "--license" in out.err


def test_fix_license_requires_single_project(mono, capsys):
    rc, out = run(capsys, "fix", str(mono), "--license", "MIT")
    assert rc == 2


def test_explain(capsys):
    rc, out = run(capsys, "explain", "PL003")
    assert rc == 0 and "InvalidConfigError" in out.out
    rc, out = run(capsys, "explain")
    assert "SC003" in out.out
    rc, _ = run(capsys, "explain", "XX1")
    assert rc == 2


# ---- real setuptools ------------------------------------------------------------------------

def test_verify_before_and_after_with_real_setuptools(mono):
    r = verify(mono / "api")
    assert r.error and "InvalidConfigError" in r.error
    r = verify(mono / "core")
    assert r.error is None and any("TOML table is deprecated" in w for w in r.warnings)
    assert main(["fix", str(mono / "api"), str(mono / "core"), "--write"]) == 0
    for name in ("api", "core"):
        r = verify(mono / name)
        assert r.ok, r
    assert verify(mono / "core").metadata["License-Expression"] == ["MIT"]
    assert verify(mono / "api").metadata["License-File"] == ["LICENSE.txt"]


def test_verify_cli_whole_monorepo_after_fix(mono, capsys):
    assert main(["fix", str(mono), "--write"]) == 1  # gis is ambiguous
    assert main(["fix", str(mono / "gis"), "--license", "GPL-3.0-only", "--write"]) == 0
    rc, out = run(capsys, "verify", str(mono), "--no-color")
    assert rc == 0, out.out
    assert out.out.count("OK  ") == 5 and "hatchling" in out.out


@pytest.mark.skipif(shutil.which("hatchling") is None and subprocess.run([sys.executable, "-c", "import hatchling"]).returncode != 0,
                    reason="hatchling not installed")
def test_hatchling_build_after_fix(mono, tmp_path):
    root = mono / "plugin"
    def build():
        return subprocess.run([sys.executable, "-c",
                               "import hatchling.build as b, sys; print(b.build_wheel(sys.argv[1]))", str(tmp_path)],
                              cwd=root, capture_output=True, text=True)
    assert build().returncode != 0  # "MIT License" is not SPDX
    assert main(["fix", str(root), "--write"]) == 0
    r = build()
    assert r.returncode == 0, r.stderr


def test_module_entrypoint(mono):
    r = subprocess.run([sys.executable, "-m", "spdxify", "check", str(mono / "core"), "--no-color"], capture_output=True, text=True)
    assert r.returncode == 1 and "PL001" in r.stdout
