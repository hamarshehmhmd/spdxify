"""Rewrite pyproject.toml / setup.cfg license metadata to PEP 639 form, preserving formatting."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import tomlkit
from packaging.requirements import Requirement

from . import licenses as L
from . import spdx
from .scan import BACKEND_MIN, Project, _spec_allows_min


@dataclass
class Change:
    path: str
    before: str
    after: str
    summary: list[str]

    def diff(self) -> str:
        return "".join(difflib.unified_diff(self.before.splitlines(True), self.after.splitlines(True),
                                            fromfile=f"a/{self.path}", tofile=f"b/{self.path}"))


class Unresolved(Exception):
    def __init__(self, project: Project, message: str):
        super().__init__(message)
        self.project = project


def _bump_requirement(req_str: str, backend: str) -> str | None:
    try:
        req = Requirement(req_str)
    except Exception:
        return None
    mn = BACKEND_MIN[backend]
    allowed, floor_ok = _spec_allows_min(req.specifier, mn)
    if allowed and floor_ok:
        return None
    short = re.sub(r"(\.0)+$", "", mn)
    if not allowed:
        spec = f">={short}"
    else:
        # keep upper bounds / exclusions, replace too-low floors
        keep = [str(s) for s in req.specifier if s.operator not in (">=", ">", "~=")]
        spec = ",".join([f">={short}"] + keep)
    out = req.name + (f"[{','.join(sorted(req.extras))}]" if req.extras else "") + spec
    if req.marker:
        out += f"; {req.marker}"
    return out


def target_for(pr: Project, override: str | None) -> str:
    if override:
        c = spdx.canonical(override)
        if not c:
            raise Unresolved(pr, f"--license '{override}' is not a valid SPDX expression: {spdx.error(override)}")
        return L.DEPRECATED_IDS.get(c, c)
    if pr.target:
        return pr.target
    if pr.candidates:
        raise Unresolved(pr, "can't tell which license this is; candidates: " + ", ".join(pr.candidates) +
                         ". Re-run with --license EXPR")
    raise Unresolved(pr, "no license could be identified; re-run with --license EXPR")


def fix_pyproject(pr: Project, override: str | None = None, bump_backend: bool = True) -> Change | None:
    path = pr.pyproject
    before = path.read_text(encoding="utf-8")
    doc = tomlkit.parse(before)
    proj = doc.get("project")
    if proj is None:
        return None
    summary: list[str] = []
    pending: list[tuple[str, str]] = []
    rules = {f.rule for f in pr.findings if f.path == str(path)}
    license_rules = {"PL001", "PL002", "PL003", "PL004", "PL005", "PL006", "PL012", "PL013", "PL014"}
    if override is None and "PL013" in rules:
        raise Unresolved(pr, "license sources disagree (" + ", ".join(pr.candidates) + "); re-run with --license EXPR")
    dynamic = [str(x) for x in proj.get("dynamic", [])]
    if rules & license_rules or override:
        target = target_for(pr, override)
        old = proj.get("license")
        if "license" not in dynamic:
            if not (isinstance(old, str) and str(old) == target):
                if old is None:
                    pending.append(("license", f'license = "{target}"'))
                else:
                    proj["license"] = target
                summary.append(f"license = \"{target}\"")
        # classifiers
        cls = proj.get("classifiers")
        if cls is not None:
            keep = [i for i, c in enumerate(cls) if not str(c).startswith("License ::")]
            removed = len(cls) - len(keep)
            if removed:
                for i in reversed(range(len(cls))):
                    if str(cls[i]).startswith("License ::"):
                        del cls[i]
                if len(cls) == 0:
                    del proj["classifiers"]
                summary.append(f"removed {removed} License :: classifier(s)")
        # license-files
        if "license-files" not in proj and pr.license_files and "license" not in dynamic:
            pending.append(("license-files", "license-files = [" + ", ".join(f'"{f}"' for f in pr.license_files) + "]"))
            summary.append("license-files = [" + ", ".join(f'"{f}"' for f in pr.license_files) + "]")
    if "PL010" in rules or "PL011" in rules:
        lf = proj.get("license-files")
        if lf is not None:
            from .scan import _glob, _license_globs_ok
            for i in reversed(range(len(lf))):
                pat = str(lf[i])
                if not _license_globs_ok(pat) or not _glob(pr.root, pat):
                    del lf[i]
                    summary.append(f"dropped license-files pattern '{pat}' (matches nothing / invalid)")
            if len(lf) == 0:
                del proj["license-files"]
    if bump_backend and pr.backend in BACKEND_MIN:
        bs = doc.get("build-system")
        reqs = bs.get("requires") if bs is not None else None
        if reqs is not None:
            for i, r in enumerate(list(reqs)):
                try:
                    name = Requirement(str(r)).name.lower().replace("_", "-")
                except Exception:
                    continue
                if name == pr.backend:
                    new = _bump_requirement(str(r), pr.backend)
                    if new and new != str(r):
                        reqs[i] = new
                        summary.append(f"build-system: '{r}' -> '{new}'")
    after = tomlkit.dumps(doc)
    for key, line in pending:
        anchors = ["license"] if key == "license-files" else ["requires-python", "version", "name"]
        after = _insert_line(after, "project", anchors, line)
    tomlkit.parse(after)  # sanity: still valid TOML
    if after == before:
        return None
    return Change(str(path), before, after, summary)


def _insert_line(text: str, section: str, anchors: list[str], new_line: str) -> str:
    """Insert new_line after the first single-line `anchor = ...` key of [section] (else at section end)."""
    lines = text.splitlines(True)
    start = end = None
    for i, ln in enumerate(lines):
        st = ln.strip()
        if st.startswith("[") and not st.startswith("[["):
            if start is not None and end is None:
                end = i
            if st.strip("[] ") == section and start is None:
                start = i
    if start is None:
        return text
    end = end if end is not None else len(lines)
    for anchor in anchors:
        for i in range(start + 1, end):
            m = re.match(r"^\s*" + re.escape(anchor) + r"\s*=(.*)$", lines[i].rstrip("\n"))
            if m:
                val = m.group(1)
                if ('"""' in val or "'''" in val) or val.count("[") != val.count("]") or val.count("{") != val.count("}"):
                    continue
                indent = re.match(r"^\s*", lines[i]).group(0)
                if not lines[i].endswith("\n"):
                    lines[i] += "\n"
                lines.insert(i + 1, indent + new_line + "\n")
                return "".join(lines)
    j = end
    while j > start + 1 and not lines[j - 1].strip():
        j -= 1
    if j > 0 and not lines[j - 1].endswith("\n"):
        lines[j - 1] += "\n"
    lines.insert(j, new_line + "\n")
    return "".join(lines)


def fix_setup_cfg(pr: Project, override: str | None = None) -> Change | None:
    path = pr.setup_cfg
    before = path.read_text(encoding="utf-8")
    rules = {f.rule for f in pr.findings if f.path == str(path)}
    if not rules & {"SC001", "SC002", "SC003", "SC004"}:
        return None
    lines = before.splitlines(True)
    out: list[str] = []
    summary: list[str] = []
    section = ""
    need_expr = bool(rules & {"SC002", "SC004"}) and not pr.data.get("project")
    target = None
    if need_expr:
        target = target_for(pr, override)
    has_expr = any(re.match(r"^license_expression\s*[=:]", ln) for ln in lines)
    in_cls = False
    wrote_expr = has_expr
    for ln in lines:
        s = ln.strip()
        if s.startswith("[") and s.endswith("]"):
            if section == "metadata" and target and not wrote_expr:
                out.append(f"license_expression = {target}\n")
                wrote_expr = True
                summary.append(f"license_expression = {target}")
            section, in_cls = s[1:-1].strip(), False
            out.append(ln)
            continue
        if section == "metadata":
            if re.match(r"^classifiers\s*[=:]", ln):
                in_cls = True
                out.append(ln)
                continue
            if in_cls and (ln[:1] in (" ", "\t")):
                if s.startswith("License ::"):
                    summary.append(f"removed classifier '{s}'")
                    continue
            elif in_cls and s:
                in_cls = False
            m = re.match(r"^license_file(\s*[=:])(.*)$", ln)
            if m:
                out.append(f"license_files{m.group(1)}{m.group(2)}\n")
                summary.append("license_file -> license_files")
                continue
            m = re.match(r"^license\s*[=:]", ln)
            if m and target:
                out.append(f"license_expression = {target}\n")
                wrote_expr = True
                summary.append(f"license = ... -> license_expression = {target}")
                continue
        out.append(ln)
    if section == "metadata" and target and not wrote_expr:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"license_expression = {target}\n")
        summary.append(f"license_expression = {target}")
    after = "".join(out)
    if after == before:
        return None
    return Change(str(path), before, after, summary)


def plan(pr: Project, override: str | None = None, bump_backend: bool = True) -> list[Change]:
    changes = []
    if pr.pyproject and pr.data.get("project"):
        c = fix_pyproject(pr, override, bump_backend)
        if c:
            changes.append(c)
    if pr.setup_cfg:
        c = fix_setup_cfg(pr, override)
        if c:
            changes.append(c)
    return changes
