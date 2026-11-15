from spdxify.scan import check


def rules(projects, name=None):
    out = {}
    for p in projects:
        out[p.name] = sorted({f.rule for f in p.findings})
    return out[name] if name else out


def test_monorepo_findings(mono):
    r = rules(check([str(mono)]))
    assert r["acme-core"] == ["PL001", "PL004", "PL008"]
    assert r["acme-api"] == ["PL003", "PL008"]
    assert r["acme-cli"] == ["PL002", "PL004", "PL007", "PL009"]
    assert r["acme-plugin"] == ["PL005", "PL008", "PL010"]
    assert r["acme-legacy"] == ["SC002", "SC003", "SC004"]
    assert r["acme-gis"] == ["PL004", "PL008"]


def test_targets(mono):
    t = {p.name: (p.target, p.candidates) for p in check([str(mono)])}
    assert t["acme-core"][0] == "MIT"
    assert t["acme-api"][0] == "Apache-2.0"
    assert t["acme-cli"][0] == "BSD-3-Clause"  # BSD classifier narrowed by the LICENSE text
    assert t["acme-legacy"][0] == "GPL-3.0-or-later"
    assert t["acme-gis"][0] is None and "GPL-3.0-only" in t["acme-gis"][1]


def test_clean_project_has_no_findings(proj):
    root = proj({"pyproject.toml": '[build-system]\nrequires=["setuptools>=77"]\nbuild-backend="setuptools.build_meta"\n'
                 '[project]\nname="x"\nversion="1"\nlicense="MIT"\nlicense-files=["LICENSE"]\n', "LICENSE": "MIT"})
    assert rules(check([str(root)]), "x") == []


def test_severity_pl007_error_when_already_new_format(proj):
    root = proj({"pyproject.toml": '[build-system]\nrequires=["setuptools==75.8.0"]\nbuild-backend="setuptools.build_meta"\n'
                 '[project]\nname="x"\nversion="1"\nlicense="MIT"\n'})
    f = [f for f in check([str(root)])[0].findings if f.rule == "PL007"][0]
    assert f.severity == "error"


def test_deprecated_spdx_id(proj):
    root = proj({"pyproject.toml": '[build-system]\nrequires=["setuptools>=77"]\nbuild-backend="setuptools.build_meta"\n'
                 '[project]\nname="x"\nversion="1"\nlicense="GPL-3.0+"\n'})
    p = check([str(root)])[0]
    assert [f.rule for f in p.findings] == ["PL006"]
    assert p.target == "GPL-3.0-or-later"


def test_conflicting_sources(proj):
    bsd = "Redistribution and use in source and binary forms ... Neither the name of"
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nlicense={text="MIT"}\n', "LICENSE": bsd})
    p = check([str(root)])[0]
    assert "PL013" in [f.rule for f in p.findings]
    assert p.target is None


def test_invalid_license_files_patterns(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nlicense="MIT"\nlicense-files=["../LICENSE","/abs"]\n'})
    assert [f.rule for f in check([str(root)])[0].findings].count("PL011") == 2


def test_missing_table_file(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nlicense={file="LICENSE.md"}\n'})
    assert "PL012" in [f.rule for f in check([str(root)])[0].findings]


def test_no_license_but_file(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\n', "LICENSE": "Apache License\nVersion 2.0"})
    p = check([str(root)])[0]
    assert [f.rule for f in p.findings] == ["PL014"]
    assert p.target == "Apache-2.0"


def test_dual_classifiers_are_not_guessed(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nclassifiers=["License :: OSI Approved :: MIT License",'
                 '"License :: OSI Approved :: Apache Software License"]\n'})
    p = check([str(root)])[0]
    assert p.target is None
    assert "Apache-2.0 OR MIT" in p.candidates


def test_skips_venvs_and_poetry1(proj):
    root = proj({"pyproject.toml": '[tool.poetry]\nname="x"\nlicense="MIT"\n',
                 ".venv/lib/pkg/pyproject.toml": '[project]\nname="bad"\nlicense={text="MIT"}\n',
                 "node_modules/a/setup.py": "classifiers=['License :: x']"})
    ps = check([str(root)])
    assert len(ps) == 1 and ps[0].findings == [] and "Poetry" in ps[0].note


def test_setup_cfg_classifier_with_expression(proj):
    root = proj({"setup.cfg": "[metadata]\nname = y\nlicense_expression = MIT\nclassifiers =\n    License :: OSI Approved :: MIT License\n"})
    assert rules(check([str(root)]), "y") == ["SC001"]


def test_setup_py_reported(proj):
    root = proj({"setup.py": "setup(name='z', license='MIT', classifiers=['License :: OSI Approved :: MIT License'])\n"})
    assert [f.rule for f in check([str(root)])[0].findings] == ["SP001"]


def test_requires_python_39_is_fine(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nrequires-python=">=3.9"\nlicense={text="MIT"}\n'})
    assert "PL009" not in [f.rule for f in check([str(root)])[0].findings]


def test_pep517_default_backend_is_setuptools(proj):
    root = proj({"pyproject.toml": '[project]\nname="x"\nversion="1"\nlicense={text="MIT"}\n'})
    assert check([str(root)])[0].backend == "setuptools"


def test_exact_pin_above_minimum_is_fine(proj):
    # regression: lru-dict pins setuptools==80.9.0 and is already migrated
    root = proj({"pyproject.toml": '[build-system]\nrequires=["setuptools==80.9.0"]\nbuild-backend="setuptools.build_meta"\n'
                 '[project]\nname="x"\nversion="1"\nlicense="MIT"\n'})
    assert check([str(root)])[0].findings == []


def test_file_argument_does_not_recurse(mono):
    ps = check([str(mono / "core" / "pyproject.toml")])
    assert [p.name for p in ps] == ["acme-core"]
