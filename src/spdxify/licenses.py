"""License knowledge: trove classifiers, free-text aliases and license-file fingerprints -> SPDX."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Trove classifier -> SPDX id. None means the classifier is ambiguous on its own.
CLASSIFIERS: dict[str, str | None] = {
    "License :: OSI Approved :: MIT License": "MIT",
    "License :: OSI Approved :: MIT No Attribution License (MIT-0)": "MIT-0",
    "License :: OSI Approved :: Apache Software License": "Apache-2.0",
    "License :: OSI Approved :: BSD License": None,
    "License :: OSI Approved :: ISC License (ISCL)": "ISC",
    "License :: OSI Approved :: Zero-Clause BSD (0BSD)": "0BSD",
    "License :: OSI Approved :: GNU General Public License (GPL)": None,
    "License :: OSI Approved :: GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later",
    "License :: OSI Approved :: GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)": "GPL-3.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v2 (LGPLv2)": "LGPL-2.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "License :: OSI Approved :: GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
    "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)": None,
    "License :: OSI Approved :: GNU Affero General Public License v3": "AGPL-3.0-only",
    "License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)": "AGPL-3.0-or-later",
    "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "License :: OSI Approved :: Mozilla Public License 1.1 (MPL 1.1)": "MPL-1.1",
    "License :: OSI Approved :: Eclipse Public License 2.0 (EPL-2.0)": "EPL-2.0",
    "License :: OSI Approved :: Eclipse Public License 1.0 (EPL-1.0)": "EPL-1.0",
    "License :: OSI Approved :: European Union Public Licence 1.2 (EUPL 1.2)": "EUPL-1.2",
    "License :: OSI Approved :: European Union Public Licence 1.1 (EUPL 1.1)": "EUPL-1.1",
    "License :: OSI Approved :: Boost Software License 1.0 (BSL-1.0)": "BSL-1.0",
    "License :: OSI Approved :: zlib/libpng License": "Zlib",
    "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
    "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    "License :: OSI Approved :: Academic Free License (AFL)": None,
    "License :: OSI Approved :: Artistic License": None,
    "License :: OSI Approved :: Universal Permissive License (UPL)": "UPL-1.0",
    "License :: OSI Approved :: University of Illinois/NCSA Open Source License": "NCSA",
    "License :: OSI Approved :: Common Development and Distribution License 1.0 (CDDL-1.0)": "CDDL-1.0",
    "License :: OSI Approved :: Historical Permission Notice and Disclaimer (HPND)": "HPND",
    "License :: OSI Approved :: Blue Oak Model License (BlueOak-1.0.0)": "BlueOak-1.0.0",
    "License :: OSI Approved :: The Unlicense": "Unlicense",
    "License :: CC0 1.0 Universal (CC0 1.0) Public Domain Dedication": "CC0-1.0",
    "License :: Public Domain": None,
    "License :: Other/Proprietary License": "LicenseRef-Proprietary",
    "License :: OSI Approved": None,
    "License :: Freely Distributable": None,
    "License :: Freeware": None,
}

# SPDX candidates offered when a classifier/text is ambiguous.
AMBIGUOUS_HINTS: dict[str, list[str]] = {
    "bsd": ["BSD-3-Clause", "BSD-2-Clause"],
    "gpl": ["GPL-3.0-or-later", "GPL-3.0-only", "GPL-2.0-or-later", "GPL-2.0-only"],
    "lgpl": ["LGPL-3.0-or-later", "LGPL-2.1-or-later", "LGPL-2.1-only"],
    "public domain": ["Unlicense", "CC0-1.0", "LicenseRef-Public-Domain"],
    "afl": ["AFL-3.0", "AFL-2.1"],
    "artistic": ["Artistic-2.0", "Artistic-1.0-Perl"],
    "other": ["LicenseRef-<name>"],
}

# Deprecated SPDX ids that `packaging` still accepts -> current id.
DEPRECATED_IDS = {
    "GPL-1.0": "GPL-1.0-only", "GPL-1.0+": "GPL-1.0-or-later",
    "GPL-2.0": "GPL-2.0-only", "GPL-2.0+": "GPL-2.0-or-later",
    "GPL-3.0": "GPL-3.0-only", "GPL-3.0+": "GPL-3.0-or-later",
    "LGPL-2.0": "LGPL-2.0-only", "LGPL-2.0+": "LGPL-2.0-or-later",
    "LGPL-2.1": "LGPL-2.1-only", "LGPL-2.1+": "LGPL-2.1-or-later",
    "LGPL-3.0": "LGPL-3.0-only", "LGPL-3.0+": "LGPL-3.0-or-later",
    "AGPL-1.0": "AGPL-1.0-only", "AGPL-3.0": "AGPL-3.0-only",
    "GFDL-1.3": "GFDL-1.3-only", "eCos-2.0": "GPL-2.0-or-later WITH eCos-exception-2.0",
    "wxWindows": "GPL-2.0-or-later WITH WxWindows-exception-3.1", "Nunit": "Zlib-acknowledgement",
    "StandardML-NJ": "SMLNJ", "BSD-2-Clause-FreeBSD": "BSD-2-Clause", "BSD-2-Clause-NetBSD": "BSD-2-Clause",
}

# Free-text license names (as found in license = {text = "..."} or setup.cfg license =) -> SPDX.
_ALIASES = {
    "mit": "MIT", "mit/x11": "MIT", "expat": "MIT", "mit0": "MIT-0", "mit no attribution": "MIT-0",
    "apache": "Apache-2.0", "apache2": "Apache-2.0", "apache 2": "Apache-2.0", "apache 20": "Apache-2.0",
    "apache v2": "Apache-2.0", "apache v20": "Apache-2.0", "apache version 20": "Apache-2.0",
    "apache software": "Apache-2.0", "asl 20": "Apache-2.0", "asl2": "Apache-2.0", "al2": "Apache-2.0",
    "bsd": None, "bsd style": None, "bsd-style": None,
    "bsd3": "BSD-3-Clause", "bsd 3": "BSD-3-Clause", "bsd 3 clause": "BSD-3-Clause", "3 clause bsd": "BSD-3-Clause",
    "new bsd": "BSD-3-Clause", "modified bsd": "BSD-3-Clause", "revised bsd": "BSD-3-Clause",
    "bsd2": "BSD-2-Clause", "bsd 2": "BSD-2-Clause", "bsd 2 clause": "BSD-2-Clause", "2 clause bsd": "BSD-2-Clause",
    "simplified bsd": "BSD-2-Clause", "freebsd": "BSD-2-Clause", "0bsd": "0BSD", "zero clause bsd": "0BSD",
    "isc": "ISC", "iscl": "ISC",
    "gpl": None, "gnu gpl": None, "gnu general public": None,
    "gplv2": "GPL-2.0-only", "gpl v2": "GPL-2.0-only", "gpl2": "GPL-2.0-only", "gnu gpl v2": "GPL-2.0-only",
    "gplv2+": "GPL-2.0-or-later", "gpl v2+": "GPL-2.0-or-later", "gpl2+": "GPL-2.0-or-later",
    "gplv3": "GPL-3.0-only", "gpl v3": "GPL-3.0-only", "gpl3": "GPL-3.0-only", "gnu gpl v3": "GPL-3.0-only",
    "gnu gplv3": "GPL-3.0-only", "gnu general public v3": "GPL-3.0-only", "gnu general public v3 0": "GPL-3.0-only",
    "gplv3+": "GPL-3.0-or-later", "gpl v3+": "GPL-3.0-or-later", "gpl3+": "GPL-3.0-or-later",
    "gnu gpl v3+": "GPL-3.0-or-later", "gnu general public v3+": "GPL-3.0-or-later", "gnu gplv3+": "GPL-3.0-or-later",
    "gnu general public v2": "GPL-2.0-only", "gnu general public v2+": "GPL-2.0-or-later",
    "lgpl": None, "lgplv2": "LGPL-2.0-only", "lgplv21": "LGPL-2.1-only", "lgpl v21": "LGPL-2.1-only",
    "lgplv2+": "LGPL-2.0-or-later", "lgplv21+": "LGPL-2.1-or-later", "lgplv3": "LGPL-3.0-only",
    "lgpl v3": "LGPL-3.0-only", "lgplv3+": "LGPL-3.0-or-later", "lgpl3": "LGPL-3.0-only",
    "agpl": None, "agplv3": "AGPL-3.0-only", "agpl v3": "AGPL-3.0-only", "agpl3": "AGPL-3.0-only",
    "agplv3+": "AGPL-3.0-or-later", "agpl v3+": "AGPL-3.0-or-later", "gnu agplv3": "AGPL-3.0-only",
    "mpl": None, "mpl2": "MPL-2.0", "mpl 2": "MPL-2.0", "mpl 20": "MPL-2.0", "mpl v2": "MPL-2.0",
    "mozilla public 20": "MPL-2.0", "mozilla public v2": "MPL-2.0",
    "unlicense": "Unlicense", "the unlicense": "Unlicense", "public domain": None,
    "cc0": "CC0-1.0", "cc0 10": "CC0-1.0", "cc0 10 universal": "CC0-1.0",
    "psf": "PSF-2.0", "psfl": "PSF-2.0", "python software foundation": "PSF-2.0",
    "zlib": "Zlib", "zlib/libpng": "Zlib", "boost": "BSL-1.0", "bsl 10": "BSL-1.0", "boost software 10": "BSL-1.0",
    "epl 20": "EPL-2.0", "epl2": "EPL-2.0", "eupl 12": "EUPL-1.2", "eupl12": "EUPL-1.2",
    "proprietary": "LicenseRef-Proprietary", "commercial": "LicenseRef-Proprietary",
    "all rights reserved": "LicenseRef-Proprietary", "other/proprietary": "LicenseRef-Proprietary",
}

def _norm(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"\(.*?\)", " ", t)  # drop parentheticals like (MIT)
    t = re.sub(r"\b(the|licen[cs]es?|version|ver)\b", " ", t)
    t = t.replace("-", " ").replace("_", " ").replace(",", " ")
    t = re.sub(r"(\d)\.(\d)", r"\1\2", t)
    t = t.replace(".", " ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s*or (any )?later$", "+", t)
    return t.replace(" +", "+")


@dataclass
class Guess:
    """Result of interpreting one license source."""
    spdx: str | None = None          # a single confident answer
    candidates: list[str] = field(default_factory=list)  # when ambiguous
    source: str = ""                 # human-readable origin

    @property
    def ambiguous(self) -> bool:
        return self.spdx is None and bool(self.candidates)


def _ambig_family(text: str) -> str:
    t = text.lower()
    for fam in ("lgpl", "lesser", "agpl", "affero", "gpl", "general public", "bsd", "public domain", "afl", "academic", "artistic"):
        if fam in t:
            return {"lesser": "lgpl", "affero": "gpl", "agpl": "gpl", "general public": "gpl",
                    "academic": "afl"}.get(fam, fam)
    return "other"


def from_classifier(classifier: str) -> Guess:
    src = f"classifier '{classifier}'"
    if classifier in CLASSIFIERS:
        spdx = CLASSIFIERS[classifier]
        if spdx:
            return Guess(spdx=spdx, source=src)
        return Guess(candidates=AMBIGUOUS_HINTS[_ambig_family(classifier)], source=src)
    return Guess(candidates=AMBIGUOUS_HINTS[_ambig_family(classifier)], source=src)


def from_text(text: str) -> Guess:
    """Interpret a free-text license string (or a pasted full license text)."""
    from . import spdx as _spdx

    src = f"license text '{_short(text)}'"
    if len(text) > 200 or "\n" in text.strip():
        g = from_license_file_text(text)
        g.source = "license text (full license pasted)"
        return g
    valid = _spdx.canonical(text)
    if valid:
        return Guess(spdx=DEPRECATED_IDS.get(valid, valid), source=src)
    key = _norm(text)
    if key in _ALIASES:
        spdx = _ALIASES[key]
        if spdx:
            return Guess(spdx=spdx, source=src)
        return Guess(candidates=AMBIGUOUS_HINTS[_ambig_family(key)], source=src)
    # "MIT License" style or "Apache License, Version 2.0" handled by _norm; try stripping trailing words
    for k in (key.replace(" ", ""), key.split(" or ")[0]):
        if k in _ALIASES and _ALIASES[k]:
            return Guess(spdx=_ALIASES[k], source=src)
    return Guess(candidates=[], source=src)


def _short(s: str, n: int = 40) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


# --- license file fingerprints ---------------------------------------------------------------

def _has(t: str, *needles: str) -> bool:
    return all(n in t for n in needles)


def from_license_file_text(raw: str) -> Guess:
    t = " ".join(raw.lower().split())
    t = t.replace("“", '"').replace("”", '"').replace("’", "'")
    gpl_like = []
    if "gnu affero general public license" in t:
        return Guess(candidates=["AGPL-3.0-or-later", "AGPL-3.0-only"], source="license file (AGPL-3.0 text)")
    if "gnu lesser general public license" in t or "gnu library general public license" in t:
        if "version 3" in t[:400]:
            return Guess(candidates=["LGPL-3.0-or-later", "LGPL-3.0-only"], source="license file (LGPL-3.0 text)")
        if "version 2.1" in t[:400]:
            return Guess(candidates=["LGPL-2.1-or-later", "LGPL-2.1-only"], source="license file (LGPL-2.1 text)")
        return Guess(candidates=AMBIGUOUS_HINTS["lgpl"], source="license file (LGPL text)")
    if "gnu general public license" in t:
        if "version 3" in t[:400]:
            gpl_like = ["GPL-3.0-or-later", "GPL-3.0-only"]
        elif "version 2" in t[:400]:
            gpl_like = ["GPL-2.0-or-later", "GPL-2.0-only"]
        else:
            gpl_like = AMBIGUOUS_HINTS["gpl"]
        return Guess(candidates=gpl_like, source=f"license file ({gpl_like[0][:7]} text)")
    if "apache license" in t and "version 2.0" in t:
        return Guess(spdx="Apache-2.0", source="license file (Apache-2.0 text)")
    if "mozilla public license" in t and ("version 2.0" in t or "v. 2.0" in t):
        return Guess(spdx="MPL-2.0", source="license file (MPL-2.0 text)")
    if "eclipse public license - v 2.0" in t or "eclipse public license v2.0" in t:
        return Guess(spdx="EPL-2.0", source="license file (EPL-2.0 text)")
    if "european union public licence" in t and "v. 1.2" in t:
        return Guess(spdx="EUPL-1.2", source="license file (EUPL-1.2 text)")
    if "boost software license - version 1.0" in t:
        return Guess(spdx="BSL-1.0", source="license file (BSL-1.0 text)")
    if "free and unencumbered software released into the public domain" in t:
        return Guess(spdx="Unlicense", source="license file (Unlicense text)")
    if "cc0 1.0 universal" in t:
        return Guess(spdx="CC0-1.0", source="license file (CC0-1.0 text)")
    if "python software foundation license version 2" in t:
        return Guess(spdx="PSF-2.0", source="license file (PSF-2.0 text)")
    if "permission is hereby granted, free of charge" in t and 'the software is provided "as is"' in t:
        if "the above copyright notice and this permission notice shall be included" in t:
            return Guess(spdx="MIT", source="license file (MIT text)")
        return Guess(spdx="MIT-0", source="license file (MIT-0 text)")
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t or \
            "permission to use, copy, modify, and distribute this software for any purpose" in t:
        if "provided that the above copyright notice and this permission notice appear in all copies" in t:
            return Guess(spdx="ISC", source="license file (ISC text)")
        return Guess(spdx="0BSD", source="license file (0BSD text)")
    if "redistribution and use in source and binary forms" in t:
        if "neither the name" in t or "the names of its contributors may not be used" in t or \
                "name of the copyright holder nor" in t:
            return Guess(spdx="BSD-3-Clause", source="license file (BSD-3-Clause text)")
        if "advertising materials" in t:
            return Guess(spdx="BSD-4-Clause", source="license file (BSD-4-Clause text)")
        return Guess(spdx="BSD-2-Clause", source="license file (BSD-2-Clause text)")
    if _has(t, "this software is provided 'as-is'", "altered source versions must be plainly marked"):
        return Guess(spdx="Zlib", source="license file (Zlib text)")
    if "all rights reserved" in t and len(t) < 600 and "permission" not in t:
        return Guess(spdx="LicenseRef-Proprietary", source="license file (all rights reserved)")
    return Guess(candidates=[], source="license file (unrecognised text)")


def narrow(candidates: list[str], other: Guess | None) -> str | None:
    """Use a second source to pick one of several candidates (e.g. GPL text + 'GPLv3+' classifier)."""
    if not other:
        return None
    if other.spdx and other.spdx in candidates:
        return other.spdx
    if other.candidates:
        common = [c for c in candidates if c in other.candidates]
        if len(common) == 1:
            return common[0]
    return None


def family(spdx: str) -> str:
    """Rough license family, used to decide whether two sources agree."""
    s = spdx.split()[0]
    s = re.sub(r"-(only|or-later)$", "", s).rstrip("+")
    return s
