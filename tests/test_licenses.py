import pytest

from spdxify import licenses as L


@pytest.mark.parametrize("text,expected", [
    ("MIT", "MIT"), ("MIT License", "MIT"), ("mit", "MIT"), ("The MIT License (MIT)", "MIT"),
    ("Apache 2.0", "Apache-2.0"), ("Apache License, Version 2.0", "Apache-2.0"), ("Apache-2.0", "Apache-2.0"),
    ("Apache Software License", "Apache-2.0"), ("BSD 3-Clause", "BSD-3-Clause"), ("New BSD License", "BSD-3-Clause"),
    ("Simplified BSD", "BSD-2-Clause"), ("GPLv3", "GPL-3.0-only"), ("GPLv3+", "GPL-3.0-or-later"),
    ("GPL v3 or later", "GPL-3.0-or-later"), ("GPL-3.0", "GPL-3.0-only"), ("LGPLv3+", "LGPL-3.0-or-later"),
    ("MPL 2.0", "MPL-2.0"), ("Mozilla Public License 2.0", "MPL-2.0"), ("ISC", "ISC"), ("Unlicense", "Unlicense"),
    ("Proprietary", "LicenseRef-Proprietary"), ("PSF", "PSF-2.0"), ("Apache-2.0 OR MIT", "Apache-2.0 OR MIT"),
])
def test_from_text(text, expected):
    assert L.from_text(text).spdx == expected


@pytest.mark.parametrize("text", ["BSD", "GPL", "BSD-style", "Public Domain", "LGPL"])
def test_from_text_ambiguous(text):
    g = L.from_text(text)
    assert g.spdx is None and g.candidates


def test_unknown_text_has_no_answer():
    g = L.from_text("Some Custom Thing 7")
    assert g.spdx is None and not g.candidates


@pytest.mark.parametrize("cls,expected", [
    ("License :: OSI Approved :: MIT License", "MIT"),
    ("License :: OSI Approved :: Apache Software License", "Apache-2.0"),
    ("License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)", "GPL-3.0-or-later"),
    ("License :: OSI Approved :: GNU General Public License v2 (GPLv2)", "GPL-2.0-only"),
    ("License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)", "MPL-2.0"),
    ("License :: Other/Proprietary License", "LicenseRef-Proprietary"),
])
def test_from_classifier(cls, expected):
    assert L.from_classifier(cls).spdx == expected


def test_bsd_classifier_is_ambiguous():
    g = L.from_classifier("License :: OSI Approved :: BSD License")
    assert g.ambiguous and "BSD-3-Clause" in g.candidates


def test_all_mapped_classifiers_are_valid_spdx():
    from spdxify.spdx import canonical
    for c, s in L.CLASSIFIERS.items():
        if s:
            assert canonical(s) == s, c


def test_all_aliases_are_valid_spdx():
    from spdxify.spdx import canonical
    for k, s in L._ALIASES.items():
        if s:
            assert canonical(s) == s, k
    for k, s in L.DEPRECATED_IDS.items():
        assert canonical(s), k


MIT_TEXT = """Permission is hereby granted, free of charge, to any person obtaining a copy
of this software ... The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY"""
BSD2 = "Redistribution and use in source and binary forms, with or without modification, are permitted ..."
BSD3 = BSD2 + " 3. Neither the name of the copyright holder nor the names of its contributors may be used"
ISC = ("Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is "
       "hereby granted, provided that the above copyright notice and this permission notice appear in all copies.")


@pytest.mark.parametrize("text,expected", [
    (MIT_TEXT, "MIT"), (MIT_TEXT.replace("The above copyright notice and this permission notice shall be included", "x"), "MIT-0"),
    (BSD2, "BSD-2-Clause"), (BSD3, "BSD-3-Clause"), (ISC, "ISC"),
    (ISC.split(", provided")[0], "0BSD"),
    ("                                 Apache License\n   Version 2.0, January 2004", "Apache-2.0"),
    ("Mozilla Public License Version 2.0\n==================================", "MPL-2.0"),
    ("This is free and unencumbered software released into the public domain.", "Unlicense"),
    ("Boost Software License - Version 1.0 - August 17th, 2003", "BSL-1.0"),
])
def test_file_fingerprints(text, expected):
    assert L.from_license_file_text(text).spdx == expected


def test_gpl_file_is_ambiguous_only_vs_later():
    g = L.from_license_file_text("GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007")
    assert g.spdx is None and g.candidates == ["GPL-3.0-or-later", "GPL-3.0-only"]
    g = L.from_license_file_text("GNU AFFERO GENERAL PUBLIC LICENSE Version 3")
    assert "AGPL-3.0-or-later" in g.candidates
    g = L.from_license_file_text("GNU LESSER GENERAL PUBLIC LICENSE Version 2.1, February 1999")
    assert g.candidates[0] == "LGPL-2.1-or-later"


def test_narrow():
    assert L.narrow(["GPL-3.0-or-later", "GPL-3.0-only"], L.Guess(spdx="GPL-3.0-only")) == "GPL-3.0-only"
    assert L.narrow(["BSD-3-Clause", "BSD-2-Clause"], L.Guess(spdx="MIT")) is None
    assert L.narrow(["a"], None) is None


def test_full_text_pasted_into_table():
    g = L.from_text(MIT_TEXT + "\n" * 3 + "x" * 50)
    assert g.spdx == "MIT"
