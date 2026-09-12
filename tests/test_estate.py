from pathlib import Path

from data_estate.generate import Generator, write_estate
from data_estate.validate import check


def test_seeds_validate(tmp_path: Path):
    for seed in (1, 2, 3):
        e = Generator(seed).build(["efos", "kickback", "roundtrip", "duplicate"])
        write_estate(e, tmp_path / f"c{seed}")
        assert check(tmp_path / f"c{seed}") == []


def test_clean_books(tmp_path: Path):
    e = Generator(9).build([])
    write_estate(e, tmp_path / "clean")
    assert check(tmp_path / "clean") == []
    assert e.truth["schemes"] == []


def test_deterministic():
    a = Generator(11).build(["efos"])
    b = Generator(11).build(["efos"])
    assert [i.uuid for i in a.invoices] == [i.uuid for i in b.invoices]
