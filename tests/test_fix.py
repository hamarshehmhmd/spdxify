try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

import pytest

from spdxify.fix import Unresolved, _bump_requirement, plan
from spdxify.scan import check


def fixed(root, override=None, **kw):
    out = {}
    for p in check([str(root)]):
        for ch in plan(p, override, **kw):
            out[ch.path.split("/")[-2] + "/" + ch.path.split("/")[-1]] = ch
    return out


def test_core_fix_preserves_comments_and_order(mono):
    ch = fixed(mono / "core")["core/pyproject.toml"]
    assert "# license kept as a table since 2021\nlicense = \"MIT\"\nlicense-files = [\"LICENSE\"]\n" in ch.after
    data = tomllib.loads(ch.after)
    assert data["project"]["classifiers"] == ["Programming Language :: Python :: 3", "Operating System :: OS Independent"]
    assert data["build-system"]["requires"] == ["setuptools>=77"]
    assert ch.diff().startswith("--- a/")


def test_cli_fix_drops_empty_classifiers_and_fixes_pin(mono):
    ch = fixed(mono / "cli")["cli/pyproject.toml"]
    d = tomllib.loads(ch.after)
    assert d["project"]["license"] == "BSD-3-Clause"
    assert d["project"]["license-files"] == ["LICENSE"]
    assert "classifiers" not in d["project"]
    assert d["build-system"]["requires"] == ["setuptools>=77", "wheel"]


def test_plugin_fix(mono):
    d = tomllib.loads(fixed(mono / "plugin")["plugin/pyproject.toml"].after)
    assert d["project"]["license"] == "MIT"
    assert d["project"]["license-files"] == ["LICENSE"]
    assert d["build-system"]["requires"] == ["hatchling>=1.27"]


def test_api_keeps_license_adds_files(mono):
    d = tomllib.loads(fixed(mono / "api")["api/pyproject.toml"].after)
    assert d["project"]["license"] == "Apache-2.0"
    assert d["project"]["license-files"] == ["LICENSE.txt"]


def test_ambiguous_needs_license(mono):
    with pytest.raises(Unresolved):
        fixed(mono / "gis")
    d = tomllib.loads(fixed(mono / "gis", "gpl-3.0-or-later")["gis/pyproject.toml"].after)
    assert d["project"]["license"] == "GPL-3.0-or-later"


def test_bad_override(mono):
    with pytest.raises(Unresolved):
        fixed(mono / "core", "MIT License")


def test_setup_cfg_fix(mono):
    after = fixed(mono / "legacy")["legacy/setup.cfg"].after
    assert "license_expression = GPL-3.0-or-later\n" in after
    assert "license_files = COPYING" in after
    assert "License ::" not in after and "Programming Language :: Python :: 3" in after
    assert "\n[options]\npackages = legacy\n" in after


def test_new_license_key_inserted_after_version(proj):
    root = proj({"pyproject.toml": '[project]\nname = "x"\nversion = "1"\ndescription = """multi\nline"""\n\n[tool.x]\na = 1\n',
                 "LICENSE": "Permission is hereby granted, free of charge, The above copyright notice and this permission notice shall be included THE SOFTWARE IS PROVIDED \"AS IS\""})
    ch = fixed(root)["p/pyproject.toml"]
    assert 'version = "1"\nlicense = "MIT"\nlicense-files = ["LICENSE"]\ndescription' in ch.after


def test_no_build_system_flag(mono):
    d = tomllib.loads(fixed(mono / "core", bump_backend=False)["core/pyproject.toml"].after)
    assert d["build-system"]["requires"] == ["setuptools"]


def test_idempotent(mono):
    for name, ch in fixed(mono / "core").items():
        (mono / name).write_text(ch.after)
    assert fixed(mono / "core") == {}


@pytest.mark.parametrize("req,expected", [
    ("setuptools", "setuptools>=77"), ("setuptools>=61", "setuptools>=77"), ("setuptools>=64,<75", "setuptools>=77"),
    ("setuptools>=61,<100", "setuptools>=77,<100"), ("setuptools>=80", None), ("setuptools[core]", "setuptools[core]>=77"),
    ("setuptools==75.8.0", "setuptools>=77"),
])
def test_bump(req, expected):
    assert _bump_requirement(req, "setuptools") == expected
