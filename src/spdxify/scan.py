"""Find Python projects and check their license metadata against PEP 639 / current build backends."""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import Version

from . import licenses as L
from . import spdx

SEVERITIES = ["info", "warn", "error"]


def _read(path) -> str:
    """Read text keeping the file's own line endings (CRLF stays CRLF on rewrite)."""
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read()


def write_text(path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)

# First release of each build backend that understands PEP 639 `license = "<SPDX>"` + `license-files`.
BACKEND_MIN = {
    "setuptools": "77.0.0",
    "hatchling": "1.27.0",
    "flit-core": "3.12.0",
    "pdm-backend": "2.4.0",
}
BACKEND_MODULES = {
    "setuptools.build_meta": "setuptools", "setuptools.build_meta:__legacy__": "setuptools",
    "hatchling.build": "hatchling", "flit_core.buildapi": "flit-core", "pdm.backend": "pdm-backend",
}
DEFAULT_LICENSE_GLOBS = ["LICEN[CS]E*", "COPYING*", "NOTICE*", "AUTHORS*"]
SKIP_DIRS = {".git", ".hg", ".venv", "venv", "env", "node_modules", ".tox", ".nox", "build", "dist",
             "site-packages", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".eggs"}
DEADLINE = "2027-02-18"

RULES = {
    "PL001": ("warn", "license is a TOML table {text = ...}",
              "setuptools>=77 warns `project.license` as a TOML table is deprecated; support ends " + DEADLINE +
              ". Use a plain SPDX string: license = \"MIT\"."),
    "PL002": ("warn", "license is a TOML table {file = ...}",
              "Deprecated like PL001. Put the SPDX id in `license` and the file in `license-files`."),
    "PL003": ("error", "License :: classifiers next to an SPDX license expression",
              "setuptools>=77 fails the build with InvalidConfigError: License classifiers have been superseded by "
              "license expressions. PEP 639 requires backends to reject this combination."),
    "PL004": ("warn", "License :: classifiers are deprecated",
              "setuptools warns 'License classifiers are deprecated'. Declare an SPDX `license` string and drop them."),
    "PL005": ("error", "license is not a valid SPDX expression",
              "A string `license` is parsed as an SPDX expression; free text like \"MIT License\" fails the build "
              "(configuration error: `project.license` must be valid exactly by one definition)."),
    "PL006": ("info", "license uses a deprecated or non-canonical SPDX id", "e.g. GPL-3.0 -> GPL-3.0-only, mit -> MIT."),
    "PL007": ("error", "build backend pinned to a version without PEP 639 support",
              "The pinned backend can't read license = \"<SPDX>\" / license-files, so the build fails."),
    "PL008": ("warn", "build backend has no lower bound with PEP 639 support",
              "Isolated builds get a new backend, but --no-isolation builds, distro builds and old caches can pick a "
              "backend that rejects the SPDX string. Require e.g. setuptools>=77."),
    "PL009": ("warn", "requires-python allows Python 3.8 but setuptools>=77 needs 3.9+",
              "setuptools 75.3 is the last release for Python 3.8, so building there breaks after migrating "
              "(pypa/setuptools#4903). Drop 3.8 or keep the old form until you do."),
    "PL010": ("warn", "license-files pattern matches no file",
              "setuptools warns 'Pattern ... did not match any files' and will make it an error after " + DEADLINE + "."),
    "PL011": ("error", "license-files pattern is invalid",
              "PEP 639: patterns must be relative, use '/' and must not contain '..'. Backends must reject them."),
    "PL012": ("error", "license file referenced by license = {file = ...} does not exist", ""),
    "PL013": ("warn", "license metadata disagrees with the LICENSE file",
              "Two sources name different licenses. spdxify won't guess; pass --license EXPR to fix."),
    "PL014": ("info", "no license metadata, but a license file exists",
              "Wheels without License-Expression show 'UNKNOWN' on PyPI and in license scanners."),
    "SC001": ("error", "setup.cfg: License :: classifiers next to license_expression", "Same failure as PL003."),
    "SC002": ("warn", "setup.cfg: License :: classifiers are deprecated", "Same as PL004."),
    "SC003": ("warn", "setup.cfg: license_file is deprecated", "Use license_files (plural)."),
    "SC004": ("info", "setup.cfg: free-text license = (legacy License field)",
              "setuptools>=77 reads license_expression = <SPDX> in [metadata]."),
    "SP001": ("info", "setup.py: License :: classifiers / license_file (edit by hand)",
              "spdxify doesn't rewrite setup.py; use license_expression=\"<SPDX>\" and license_files=[...]."),
}


@dataclass
class Finding:
    rule: str
    path: str
    line: int
    message: str
    severity: str = ""

    def __post_init__(self):
        if not self.severity:
            self.severity = RULES[self.rule][0]


@dataclass
class Project:
    root: Path
    pyproject: Path | None = None
    setup_cfg: Path | None = None
    setup_py: Path | None = None
    data: dict = field(default_factory=dict)
    backend: str | None = None
    backend_req: Requirement | None = None
    findings: list[Finding] = field(default_factory=list)
    target: str | None = None          # SPDX expression we'd migrate to
    candidates: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    license_files: list[str] = field(default_factory=list)  # what we'd put in license-files
    note: str = ""

    cfg_name: str | None = None

    @property
    def name(self) -> str:
        return self.data.get("project", {}).get("name") or self.cfg_name or self.root.name


def find_projects(paths: list[str]) -> list[Project]:
    seen: dict[Path, Project] = {}
    for p in paths:
        base = Path(p)
        if base.is_file():  # a single pyproject.toml / setup.cfg: just that project, no recursion
            walk = [(str(base.parent), [], [f for f in os.listdir(base.parent) if (base.parent / f).is_file()])]
        else:
            walk = os.walk(base)
        for dirpath, dirnames, filenames in walk:
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info"))
            names = set(filenames)
            if not names & {"pyproject.toml", "setup.cfg", "setup.py"}:
                continue
            root = Path(dirpath)
            pr = seen.setdefault(root.resolve(), Project(root=root))
            if "pyproject.toml" in names:
                pr.pyproject = root / "pyproject.toml"
            if "setup.cfg" in names:
                pr.setup_cfg = root / "setup.cfg"
            if "setup.py" in names:
                pr.setup_py = root / "setup.py"
    return list(seen.values())


def _line_of(text: str, pattern: str, section: str | None = "project") -> int:
    lines = text.splitlines()
    in_sec = section is None
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("["):
            in_sec = section is None or s.strip("[] ") == section
            continue
        if in_sec and re.search(pattern, ln):
            return i
    return 1


def _license_globs_ok(pattern: str) -> bool:
    return not (pattern.startswith("/") or ".." in pattern.split("/") or "\\" in pattern or re.match(r"^[A-Za-z]:", pattern))


def _glob(root: Path, pattern: str) -> list[str]:
    out = sorted(str(p.relative_to(root)).replace(os.sep, "/") for p in root.glob(pattern) if p.is_file())
    return out


def default_license_files(root: Path) -> list[str]:
    found: list[str] = []
    for g in DEFAULT_LICENSE_GLOBS:
        for f in _glob(root, g):
            if f not in found:
                found.append(f)
    return found


def _file_guess(root: Path, rel: str) -> L.Guess | None:
    p = root / rel
    try:
        return L.from_license_file_text(p.read_text(encoding="utf-8", errors="replace")[:20000])
    except OSError:
        return None


def _primary_license_file(root: Path, files: list[str]) -> str | None:
    for f in files:
        if re.match(r"(?i)^(licen[cs]e|copying)", f.split("/")[-1]):
            return f
    return None


def _backend(data: dict) -> tuple[str | None, Requirement | None]:
    bs = data.get("build-system") or {}
    mod = bs.get("build-backend")
    reqs = []
    for r in bs.get("requires", []) or []:
        try:
            reqs.append(Requirement(r))
        except InvalidRequirement:
            continue
    if mod is None and not bs:
        name = "setuptools"  # PEP 517 fallback
    else:
        name = BACKEND_MODULES.get(mod or "setuptools.build_meta:__legacy__")
    if not name:
        return None, None
    for r in reqs:
        if r.name.lower().replace("_", "-") == name:
            return name, r
    return name, None


def _spec_allows_min(spec: SpecifierSet, minimum: str) -> tuple[bool, bool]:
    """Return (some PEP 639 version allowed, a lower bound >= minimum present)."""
    mn = Version(minimum)
    probes = [mn] + [Version(f"{mn.major + k}.0") for k in range(1, 40)] + [Version(f"{mn.major}.{mn.minor + k}") for k in range(1, 30)]
    for sp in spec:
        try:
            v = Version(sp.version.replace(".*", ""))
        except Exception:
            continue
        if v >= mn:
            probes.append(v)
    allowed = any(spec.contains(v, prereleases=True) for v in probes)
    floor_ok = False
    for s in spec:
        if s.operator in (">=", ">", "~=", "==", "==="):
            try:
                v = Version(s.version.replace(".*", ""))
            except Exception:
                continue
            if v >= mn:
                floor_ok = True
    return allowed, floor_ok


def _choose(sources: list[L.Guess]) -> tuple[str | None, list[str], list[L.Guess]]:
    """Combine guesses from several sources. Returns (target, candidates, conflicting)."""
    confident = [g for g in sources if g.spdx]
    ambiguous = [g for g in sources if g.ambiguous]
    fams = {L.family(g.spdx) for g in confident}
    if len(fams) > 1:
        return None, sorted({g.spdx for g in confident}), confident
    if confident:
        best = confident[0].spdx
        # an "-only"/"-or-later" decision from a classifier beats a bare file guess
        for g in confident:
            if g.spdx.endswith(("-only", "-or-later")):
                best = g.spdx
        return best, [], []
    for i, g in enumerate(ambiguous):
        for other in ambiguous[i + 1:]:
            pick = L.narrow(g.candidates, other)
            if pick:
                return pick, [], []
    if ambiguous:
        cands = ambiguous[0].candidates
        for g in ambiguous[1:]:
            common = [c for c in cands if c in g.candidates]
            cands = common or cands
        return None, cands, []
    return None, [], []


def check_pyproject(pr: Project) -> None:
    path = pr.pyproject
    text = _read(path)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        pr.note = f"invalid TOML: {exc}"
        return
    pr.data = data
    proj = data.get("project")
    if not isinstance(proj, dict):
        if not pr.setup_cfg:
            pr.note = "no [project] table (Poetry 1.x / tool-only pyproject): skipped"
        return
    rel = str(path)
    pr.backend, pr.backend_req = _backend(data)
    dynamic = set(proj.get("dynamic", []) or [])
    lic = proj.get("license")
    lic_files = proj.get("license-files")
    classifiers = [c for c in proj.get("classifiers", []) or [] if isinstance(c, str)]
    lic_cls = [c for c in classifiers if c.startswith("License ::")]
    root = pr.root
    guesses: list[L.Guess] = []
    new_format = False
    table_file: str | None = None
    lic_line = _line_of(text, r"^\s*license\s*=")

    if isinstance(lic, dict):
        if "text" in lic:
            pr.findings.append(Finding("PL001", rel, lic_line, f"license = {{text = \"{L._short(str(lic['text']))}\"}} is deprecated (setuptools support ends {DEADLINE})"))
            guesses.append(L.from_text(str(lic["text"])))
        if "file" in lic:
            table_file = str(lic["file"])
            pr.findings.append(Finding("PL002", rel, lic_line, f"license = {{file = \"{table_file}\"}} is deprecated (setuptools support ends {DEADLINE})"))
            if (root / table_file).is_file():
                g = _file_guess(root, table_file)
                if g:
                    guesses.append(g)
            else:
                pr.findings.append(Finding("PL012", rel, lic_line, f"license file '{table_file}' does not exist"))
    elif isinstance(lic, str):
        new_format = True
        canon = spdx.canonical(lic)
        if canon is None:
            pr.findings.append(Finding("PL005", rel, lic_line, f"license = \"{L._short(lic)}\" is not a valid SPDX expression ({spdx.error(lic)})"))
            guesses.append(L.from_text(lic))
        else:
            fixed = L.DEPRECATED_IDS.get(canon, canon)
            if fixed != lic:
                pr.findings.append(Finding("PL006", rel, lic_line, f"license = \"{lic}\" -> \"{fixed}\""))
            guesses.insert(0, L.Guess(spdx=fixed, source="license string"))
    if lic_files is not None:
        new_format = True
        lf_line = _line_of(text, r"^\s*license-files\s*=")
        pats = lic_files if isinstance(lic_files, list) else []
        for pat in pats:
            if not _license_globs_ok(pat):
                pr.findings.append(Finding("PL011", rel, lf_line, f"license-files pattern '{pat}' must be relative, use '/', no '..'"))
            elif not _glob(root, pat):
                pr.findings.append(Finding("PL010", rel, lf_line, f"license-files pattern '{pat}' matches no file"))
    if lic_cls:
        cl_line = _line_of(text, r"License ::")
        names = ", ".join(c.split(" :: ")[-1] for c in lic_cls)
        if isinstance(lic, str) and spdx.canonical(lic):
            pr.findings.append(Finding("PL003", rel, cl_line, f"{len(lic_cls)} License :: classifier(s) with license = \"{lic}\": build fails ({names})"))
        else:
            pr.findings.append(Finding("PL004", rel, cl_line, f"License :: classifier(s) are deprecated: {names}"))
        cguesses = [L.from_classifier(c) for c in lic_cls]
        if len({g.spdx for g in cguesses if g.spdx}) > 1:
            # several confident classifiers = usually dual licensing; don't guess AND vs OR
            ids = sorted({g.spdx for g in cguesses if g.spdx})
            guesses.append(L.Guess(candidates=[" OR ".join(ids), " AND ".join(ids)], source="several license classifiers"))
        else:
            guesses.extend(cguesses)

    # license files on disk
    on_disk = default_license_files(root)
    if table_file:
        pr.license_files = [table_file] if (root / table_file).is_file() else []
    elif isinstance(lic_files, list):
        pr.license_files = [x for x in lic_files if isinstance(x, str) and _license_globs_ok(x) and _glob(root, x)]
    else:
        pr.license_files = on_disk
    main_file = table_file if table_file and (root / table_file).is_file() else _primary_license_file(root, on_disk)
    if main_file and not table_file:
        g = _file_guess(root, main_file)
        if g and (g.spdx or g.candidates):
            guesses.append(g)

    if lic is None and "license" not in dynamic and not lic_cls:
        if main_file:
            g = _file_guess(root, main_file)
            hint = f" ({g.spdx or ' / '.join(g.candidates[:2])})" if g and (g.spdx or g.candidates) else ""
            pr.findings.append(Finding("PL014", rel, _line_of(text, r"^\s*name\s*="), f"no license in [project] but {main_file} exists{hint}"))
        else:
            return
    if "license" in dynamic:
        pr.note = "license is dynamic: only classifiers checked"

    target, cands, conflict = _choose(guesses)
    pr.sources = [g.source + (f" -> {g.spdx}" if g.spdx else (f" -> one of {', '.join(g.candidates)}" if g.candidates else " -> ?")) for g in guesses]
    if conflict:
        pr.findings.append(Finding("PL013", rel, lic_line, "sources disagree: " + "; ".join(f"{g.source} says {g.spdx}" for g in conflict)))
    pr.target, pr.candidates = target, cands

    will_be_new = new_format or bool(pr.findings)
    if pr.backend in BACKEND_MIN and will_be_new:
        mn = BACKEND_MIN[pr.backend]
        bs_line = _line_of(text, r"requires\s*=", section="build-system")
        if pr.backend_req is not None:
            allowed, floor_ok = _spec_allows_min(pr.backend_req.specifier, mn)
            if not allowed:
                pr.findings.append(Finding("PL007", rel, bs_line, f"build-system requires '{pr.backend_req}' but PEP 639 needs {pr.backend}>={mn}", severity="error" if new_format else "warn"))
            elif not floor_ok:
                pr.findings.append(Finding("PL008", rel, bs_line, f"'{pr.backend_req}' has no {pr.backend}>={mn} floor"))
        rp = proj.get("requires-python")
        if pr.backend == "setuptools" and rp:
            try:
                if SpecifierSet(rp).contains("3.8"):
                    pr.findings.append(Finding("PL009", rel, _line_of(text, r"^\s*requires-python"), f"requires-python = \"{rp}\" includes 3.8; setuptools>=77 needs Python>=3.9"))
            except InvalidSpecifier:
                pass


_CFG_KEY = re.compile(r"^(\s*)(license_files?|license_expression|license)\s*[=:]\s*(.*)$")


def check_setup_cfg(pr: Project) -> None:
    path = pr.setup_cfg
    lines = _read(path).splitlines()
    rel = str(path)
    section = ""
    keys: dict[str, tuple[int, str]] = {}
    cls_lines: list[tuple[int, str]] = []
    in_classifiers = False
    for i, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            section, in_classifiers = s[1:-1].strip(), False
            continue
        if section != "metadata":
            continue
        nm = re.match(r"^name\s*[=:]\s*(\S+)", ln)
        if nm:
            pr.cfg_name = nm.group(1)
        m = _CFG_KEY.match(ln)
        if m and not ln.startswith((" ", "\t")):
            keys[m.group(2)] = (i, m.group(3).strip())
            in_classifiers = False
            continue
        if re.match(r"^classifiers\s*[=:]", ln):
            in_classifiers = True
            rest = ln.split("=", 1)[-1].strip() if "=" in ln else ""
            if rest.startswith("License ::"):
                cls_lines.append((i, rest))
            continue
        if in_classifiers:
            if ln[:1] in (" ", "\t") or not s:
                if s.startswith("License ::"):
                    cls_lines.append((i, s))
            else:
                in_classifiers = False
    if not keys and not cls_lines:
        return
    if cls_lines:
        if "license_expression" in keys:
            pr.findings.append(Finding("SC001", rel, cls_lines[0][0], f"{len(cls_lines)} License :: classifier(s) with license_expression: build fails"))
        else:
            pr.findings.append(Finding("SC002", rel, cls_lines[0][0], "License :: classifier(s) are deprecated: " + ", ".join(c.split(" :: ")[-1] for _, c in cls_lines)))
    if "license_file" in keys:
        pr.findings.append(Finding("SC003", rel, keys["license_file"][0], "license_file is deprecated, use license_files"))
    if "license" in keys and "license_expression" not in keys:
        pr.findings.append(Finding("SC004", rel, keys["license"][0], f"license = {L._short(keys['license'][1])} (use license_expression)"))
    if not pr.data.get("project"):
        guesses = []
        if "license_expression" in keys:
            c = spdx.canonical(keys["license_expression"][1])
            if c:
                guesses.append(L.Guess(spdx=L.DEPRECATED_IDS.get(c, c), source="license_expression"))
        if "license" in keys:
            guesses.append(L.from_text(keys["license"][1]))
        guesses.extend(L.from_classifier(c) for _, c in cls_lines)
        main = _primary_license_file(pr.root, default_license_files(pr.root))
        if main:
            g = _file_guess(pr.root, main)
            if g and (g.spdx or g.candidates):
                guesses.append(g)
        target, cands, conflict = _choose(guesses)
        if conflict:
            pr.findings.append(Finding("PL013", rel, 1, "sources disagree: " + "; ".join(f"{g.source} says {g.spdx}" for g in conflict)))
        pr.target, pr.candidates = target, cands
        pr.sources = [g.source + (f" -> {g.spdx}" if g.spdx else "") for g in guesses]


def check_setup_py(pr: Project) -> None:
    text = _read(pr.setup_py)
    hits = []
    for i, ln in enumerate(text.splitlines(), 1):
        if "License ::" in ln or re.search(r"\blicense_file\s*=", ln) or re.search(r"\blicense\s*=\s*['\"]", ln):
            hits.append(i)
    if hits:
        pr.findings.append(Finding("SP001", str(pr.setup_py), hits[0], f"{len(hits)} legacy license line(s) in setup.py: edit by hand"))


def check(paths: list[str]) -> list[Project]:
    projects = find_projects(paths)
    for pr in projects:
        if pr.pyproject:
            check_pyproject(pr)
        if pr.setup_cfg:
            check_setup_cfg(pr)
        if pr.setup_py:
            check_setup_py(pr)
    return projects
