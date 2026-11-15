"""spdxify command line."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .fix import Unresolved, plan
from .scan import RULES, SEVERITIES, check
from .verify import verify

MANUAL = {"PL009", "SP001"}
C = {"error": "31", "warn": "33", "info": "36", "ok": "32", "dim": "2", "bold": "1"}


def _color(enabled: bool):
    def c(kind: str, s: str) -> str:
        return f"\033[{C[kind]}m{s}\033[0m" if enabled else s
    return c


def _use_color(args) -> bool:
    if getattr(args, "no_color", False) or os.environ.get("NO_COLOR"):
        return False
    return bool(os.environ.get("FORCE_COLOR")) or sys.stdout.isatty()


def _rel(p: str) -> str:
    try:
        r = os.path.relpath(p)
        return r if not r.startswith("..") else p
    except ValueError:
        return p


def cmd_check(args) -> int:
    projects = check(args.paths)
    c = _color(_use_color(args))
    th = SEVERITIES.index(args.min_severity)
    ignore = set(x.strip() for x in (args.ignore or "").split(",") if x.strip())
    all_f = []
    for pr in projects:
        pr.findings = [f for f in pr.findings if f.rule not in ignore]
        all_f.extend((pr, f) for f in pr.findings)
    shown = [(pr, f) for pr, f in all_f if SEVERITIES.index(f.severity) >= th]
    if args.format == "json":
        out = []
        for pr in projects:
            out.append({"project": pr.name, "root": _rel(str(pr.root)), "backend": pr.backend,
                        "suggested_license": pr.target, "candidates": pr.candidates, "sources": pr.sources,
                        "license_files": pr.license_files, "note": pr.note,
                        "findings": [{"rule": f.rule, "severity": f.severity, "path": _rel(f.path), "line": f.line,
                                      "message": f.message} for f in pr.findings]})
        print(json.dumps(out, indent=2))
    elif args.format == "github":
        lvl = {"error": "error", "warn": "warning", "info": "notice"}
        for pr, f in shown:
            print(f"::{lvl[f.severity]} file={_rel(f.path)},line={f.line},title=spdxify {f.rule}::{f.message}")
    else:
        for pr in projects:
            fs = [f for f in pr.findings if SEVERITIES.index(f.severity) >= th]
            if not fs and not args.verbose:
                continue
            head = f"{pr.name}  {c('dim', _rel(str(pr.root)) + '/')}"
            print(c("bold", head))
            if pr.note:
                print("  " + c("dim", pr.note))
            for f in fs:
                print(f"  {c(f.severity, f.severity.upper().ljust(5))} {f.rule} {c('dim', f'{_rel(f.path)}:{f.line}')}  {f.message}")
            fixable = [f for f in fs if f.rule not in MANUAL | {"PL007", "PL008"}]
            if fixable:
                if pr.target:
                    print(f"  {c('ok', '->')} migrate to SPDX \"{pr.target}\"" +
                          (f", license-files = {json.dumps(pr.license_files)}" if pr.license_files else ""))
                elif pr.candidates:
                    print(f"  {c('warn', '??')} ambiguous: one of {', '.join(pr.candidates)} (fix needs --license)")
            print()
        n = {s: sum(1 for _, f in all_f if f.severity == s) for s in SEVERITIES}
        print(f"{len(projects)} project(s): " + ", ".join(c(s, f"{n[s]} {s}") for s in reversed(SEVERITIES)))
        if any(f.rule not in MANUAL for _, f in shown):
            print(c("dim", "run `spdxify fix` to see the patch, `spdxify fix --write` to apply it"))
    fail_th = SEVERITIES.index(args.fail_on) if args.fail_on != "never" else 99
    return 1 if any(SEVERITIES.index(f.severity) >= fail_th for _, f in all_f) else 0


def cmd_fix(args) -> int:
    projects = check(args.paths)
    c = _color(_use_color(args))
    if args.license and len([p for p in projects if p.findings]) > 1:
        print("--license applies to every project found; pass a single project path", file=sys.stderr)
        return 2
    changed, unresolved = 0, 0
    for pr in projects:
        if not pr.findings and not args.license:
            continue
        try:
            changes = plan(pr, args.license, bump_backend=not args.no_build_system)
        except Unresolved as exc:
            unresolved += 1
            print(c("warn", f"skip {pr.name} ({_rel(str(pr.root))}): {exc}"), file=sys.stderr)
            continue
        for ch in changes:
            changed += 1
            if args.write:
                Path(ch.path).write_text(ch.after, encoding="utf-8")
                print(c("ok", f"fixed {_rel(ch.path)}") + ": " + "; ".join(ch.summary))
            else:
                for line in ch.diff().splitlines():
                    kind = "ok" if line.startswith("+") and not line.startswith("+++") else \
                        "error" if line.startswith("-") and not line.startswith("---") else "dim" if line.startswith("@@") else None
                    print(c(kind, line) if kind else line)
    left = [f for pr in check(args.paths) for f in pr.findings] if args.write else []
    if not args.write and changed:
        print(c("dim", f"\n{changed} file(s) would change. Re-run with --write to apply."))
    if args.write:
        manual = [f for f in left if f.rule in ("SP001", "PL009")]
        if manual:
            print(c("dim", "still to do by hand: " + "; ".join(f"{f.rule} {_rel(f.path)}:{f.line}" for f in manual)))
    if not changed and not unresolved:
        print(c("ok", "nothing to fix"))
    return 1 if unresolved else 0


def cmd_verify(args) -> int:
    projects = [p for p in check(args.paths) if p.pyproject or p.setup_cfg]
    c = _color(_use_color(args))
    bad = 0
    for pr in projects:
        if pr.backend not in ("setuptools", None) and pr.pyproject:
            print(f"{pr.name}: {c('dim', f'backend {pr.backend}: verify only drives setuptools; use python -m build')}")
            continue
        r = verify(pr.root, args.python)
        md = r.metadata
        tag = c("ok", "OK  ") if r.ok else c("error", "FAIL")
        print(f"{tag} {pr.name}  {c('dim', _rel(str(pr.root)))}  setuptools {r.setuptools or '?'}")
        if r.error:
            print(f"     {c('error', r.error)}")
        for w in dict.fromkeys(r.warnings):
            print(f"     {c('warn', w)}")
        if md:
            print(f"     Metadata-Version: {', '.join(md.get('Metadata-Version', ['?']))}  "
                  f"License-Expression: {', '.join(md.get('License-Expression', ['-']))}  "
                  f"License-File: {', '.join(md.get('License-File', ['-']))}")
            if md.get("License"):
                print(f"     {c('dim', 'legacy License: ' + md['License'][0][:60])}")
        bad += 0 if r.ok else 1
    return 1 if bad else 0


def cmd_explain(args) -> int:
    rules = [args.rule.upper()] if args.rule else sorted(RULES)
    for r in rules:
        if r not in RULES:
            print(f"unknown rule {r}", file=sys.stderr)
            return 2
        sev, title, why = RULES[r]
        print(f"{r} [{sev}] {title}")
        if why and args.rule:
            print(f"  {why}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="spdxify", description="Migrate Python packaging license metadata to PEP 639 "
                                "SPDX expressions before setuptools drops the old forms (2027-02-18).")
    p.add_argument("--version", action="version", version=f"spdxify {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="report deprecated / broken license metadata")
    pc.add_argument("paths", nargs="*", default=["."])
    pc.add_argument("--format", choices=["text", "json", "github"], default="text")
    pc.add_argument("--min-severity", choices=SEVERITIES, default="info", help="hide findings below this")
    pc.add_argument("--fail-on", choices=SEVERITIES + ["never"], default="warn", help="exit 1 at/above this (default warn)")
    pc.add_argument("--ignore", help="comma-separated rule ids to ignore")
    pc.add_argument("-v", "--verbose", action="store_true", help="also list clean projects")
    pc.add_argument("--no-color", action="store_true")
    pc.set_defaults(func=cmd_check)

    pf = sub.add_parser("fix", help="show (or --write) the PEP 639 migration patch")
    pf.add_argument("paths", nargs="*", default=["."])
    pf.add_argument("--write", "-w", action="store_true", help="apply the changes")
    pf.add_argument("--license", help="SPDX expression to use when the license is ambiguous")
    pf.add_argument("--no-build-system", action="store_true", help="don't raise the build backend floor")
    pf.add_argument("--no-color", action="store_true")
    pf.set_defaults(func=cmd_fix)

    pv = sub.add_parser("verify", help="build metadata with the installed setuptools and show license warnings/errors")
    pv.add_argument("paths", nargs="*", default=["."])
    pv.add_argument("--python", help="interpreter whose setuptools to use (default: this one)")
    pv.add_argument("--no-color", action="store_true")
    pv.set_defaults(func=cmd_verify)

    pe = sub.add_parser("explain", help="describe the rules")
    pe.add_argument("rule", nargs="?")
    pe.set_defaults(func=cmd_explain)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
