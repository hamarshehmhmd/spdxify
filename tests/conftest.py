import shutil
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "monorepo"


@pytest.fixture
def mono(tmp_path):
    dst = tmp_path / "mono"
    shutil.copytree(EXAMPLES, dst)
    return dst


@pytest.fixture
def proj(tmp_path):
    """Factory: write a single project from a dict of files."""
    def make(files: dict, name="p"):
        root = tmp_path / name
        for rel, content in files.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(content.encode())
        return root
    return make
