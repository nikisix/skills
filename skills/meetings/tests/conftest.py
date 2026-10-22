import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def org_dir(tmp_path, monkeypatch):
    """A throwaway org tree shaped like ~/org/ringmaster."""
    root = tmp_path / "ringmaster"
    meetings = root / "meetings"
    for sub in ("inbox", "digests", "archive", "logs"):
        (meetings / sub).mkdir(parents=True)
    (root / "2026").mkdir()
    shutil.copy(FIXTURES / "people.yaml", meetings / "people.yaml")
    monkeypatch.setenv("MEETINGS_ORG_DIR", str(root))
    return root
