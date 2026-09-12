"""data_estate/out/company_42 is the frozen demo dataset (AGENTS.md). Any byte change fails this test.

If you believe it must change, open an issue labelled needs-human. Do not update EXPECTED.
"""
import hashlib
from pathlib import Path

FROZEN = Path(__file__).resolve().parents[1] / "data_estate" / "out" / "company_42"
EXPECTED = "c44f08440288f7f39a442911f294d1dd91d31b7fc423057160950c5a8d1818f4"


def digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(p.relative_to(root).as_posix().encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def test_company_42_is_frozen():
    assert FROZEN.is_dir(), "frozen dataset missing"
    assert digest(FROZEN) == EXPECTED, "data_estate/out/company_42 changed. It is frozen; generate elsewhere."
