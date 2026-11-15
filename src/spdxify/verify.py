"""Ask the installed setuptools to build the project's metadata and report license warnings/errors."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_PROBE = r'''
import json, sys, tempfile, warnings, io, contextlib, os
res = {"setuptools": None, "warnings": [], "error": None, "metadata": {}}
try:
    import setuptools
    res["setuptools"] = setuptools.__version__
    from setuptools import build_meta
except Exception as e:
    res["error"] = "setuptools not importable: %s" % e
    print(json.dumps(res)); sys.exit(0)
out = tempfile.mkdtemp()
buf = io.StringIO()
with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            d = build_meta.prepare_metadata_for_build_wheel(out)
        meta = open(os.path.join(out, d, "METADATA"), encoding="utf-8").read()
        md = {}
        for line in meta.split("\n\n", 1)[0].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                if k in ("Name", "Version", "License", "License-Expression", "License-File", "Classifier", "Metadata-Version"):
                    md.setdefault(k, []).append(v.strip())
        res["metadata"] = md
    except BaseException as e:
        msg = str(e).strip().splitlines()
        res["error"] = "%s: %s" % (type(e).__name__, " ".join(msg[:3])[:400])
    for x in w:
        m = str(x.message).strip().splitlines()
        title = m[0] if m else ""
        if any(k in str(x.message) for k in ("icense", "classifier")):
            res["warnings"].append("%s: %s" % (x.category.__name__, title[:200]))
print("@@SPDXIFY@@" + json.dumps(res))
'''


@dataclass
class VerifyResult:
    root: str
    setuptools: str | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.warnings


def verify(root: Path, python: str | None = None, timeout: int = 120) -> VerifyResult:
    proc = subprocess.run([python or sys.executable, "-c", _PROBE], cwd=str(root), capture_output=True,
                          text=True, timeout=timeout)
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("@@SPDXIFY@@"):
            payload = json.loads(line[len("@@SPDXIFY@@"):])
    if payload is None:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        return VerifyResult(str(root), error="metadata probe crashed: " + " | ".join(tail))
    return VerifyResult(str(root), payload["setuptools"], payload["warnings"], payload["error"], payload["metadata"])
