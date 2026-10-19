"""Files made new: never over an existing one, two writers at once taking two names, and a write
that fails part-way leaving nothing behind."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from scry_core import fresh
from scry_core.reply_contract import Invalid


def test_a_file_is_created_once(tmp_path: Path) -> None:
    fresh.create(tmp_path / "a", b"one", "the file")
    assert (tmp_path / "a").read_bytes() == b"one"
    with pytest.raises(Invalid, match="already there") as e:
        fresh.create(tmp_path / "a", b"two", "the file")
    assert e.value.code == "bad_argument" and (tmp_path / "a").read_bytes() == b"one"
    with pytest.raises(Invalid, match="cannot be created") as e:
        fresh.create(tmp_path / "no" / "a", b"x", "the file")
    assert e.value.code == "host_failed"


def test_numbered_files_skip_taken_names_and_never_collide(tmp_path: Path) -> None:
    (tmp_path / "f").mkdir()
    (tmp_path / "f" / "t-1").write_bytes(b"theirs")
    names: list[Path] = []
    lock = threading.Lock()

    def take() -> None:
        path = fresh.numbered(tmp_path / "f", lambda n: f"t-{n}", b"x", "the file")
        with lock:
            names.append(path)
    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(names)) == 8 and tmp_path / "f" / "t-1" not in names
    assert (tmp_path / "f" / "t-1").read_bytes() == b"theirs"
    assert fresh.numbered(tmp_path / "new" / "deep", lambda n: f"t-{n}", b"x",
                          "the file").parent == tmp_path / "new" / "deep"


def test_a_folder_or_a_file_that_cannot_be_made_is_host_failed(tmp_path: Path) -> None:
    (tmp_path / "blocked").write_bytes(b"a file where the folder would go")
    with pytest.raises(Invalid, match="cannot be created") as e:
        fresh.numbered(tmp_path / "blocked", lambda n: f"t-{n}", b"x", "the file")
    assert e.value.code == "host_failed"
    with pytest.raises(Invalid, match="cannot be created"):
        fresh.numbered(tmp_path, lambda n: f"no/t-{n}", b"x", "the file")


class _Full:
    def __init__(self, real: Any) -> None:
        self.real = real

    def __enter__(self) -> _Full:
        return self

    def __exit__(self, *_: object) -> None:
        self.real.close()

    def write(self, _: bytes) -> int:
        raise OSError("no space left on device")


def test_a_write_that_fails_part_way_leaves_nothing(tmp_path: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    real_open: Any = Path.open

    def opened(self: Path, mode: str = "r") -> Any:
        return _Full(real_open(self, mode))
    monkeypatch.setattr(Path, "open", opened)
    with pytest.raises(Invalid, match="could not be written whole") as e:
        fresh.create(tmp_path / "half", b"x", "the file")
    assert e.value.code == "host_failed" and not (tmp_path / "half").exists()
    with pytest.raises(Invalid, match="could not be written whole"):
        fresh.numbered(tmp_path, lambda n: f"t-{n}", b"x", "the file")
    assert list(tmp_path.iterdir()) == []


def test_numbered_directories_skip_taken_names(tmp_path: Path) -> None:
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "series-1").mkdir()
    made = [fresh.numbered_dir(tmp_path / "s", lambda n: f"series-{n}", "the series")
            for _ in range(2)]
    assert [p.name for p in made] == ["series-2", "series-3"] and all(p.is_dir() for p in made)
    (tmp_path / "file").write_bytes(b"x")
    with pytest.raises(Invalid, match="cannot be created") as e:
        fresh.numbered_dir(tmp_path / "file", lambda n: f"s-{n}", "the series")
    assert e.value.code == "host_failed"
    with pytest.raises(Invalid, match="cannot be created"):
        fresh.numbered_dir(tmp_path, lambda n: f"no/s-{n}", "the series")


def _folder(dest: Path | None, scratch: Path) -> tuple[Path, bool]:
    return fresh.directory(dest, scratch / "series", lambda n: f"series-{n}", "the series"), \
        dest is not None


def test_a_series_folder_is_the_callers_dest_or_a_numbered_scratch(tmp_path: Path) -> None:
    dest = tmp_path / "mine"
    assert _folder(dest, tmp_path / "scratch") == (dest, True) and dest.is_dir()
    one, kept = _folder(None, tmp_path / "scratch")
    two, _ = _folder(None, tmp_path / "scratch")
    assert (one.name, two.name, kept) == ("series-1", "series-2", False)


def test_a_dest_already_there_is_refused_and_left_alone(tmp_path: Path) -> None:
    (tmp_path / "there").mkdir()
    (tmp_path / "there" / "keep.png").write_bytes(b"x")
    with pytest.raises(Invalid, match="already there") as e:
        _folder(tmp_path / "there", tmp_path)
    assert e.value.code == "bad_argument" and (tmp_path / "there" / "keep.png").exists()


def test_a_dest_whose_parent_is_missing_is_the_callers(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="cannot be created") as e:
        _folder(tmp_path / "no" / "such", tmp_path)
    assert e.value.code == "bad_argument"


@pytest.mark.parametrize("raised", [Invalid("bad_argument", "x"), KeyboardInterrupt()])
def test_any_exception_inside_a_capture_takes_the_folder_away(tmp_path: Path,
                                                               raised: BaseException) -> None:
    where, _ = _folder(tmp_path / "s", tmp_path)
    with pytest.raises(type(raised)), fresh.taken_back(where):
        (where / "raw-1.png").write_bytes(b"half")
        raise raised
    assert not where.exists()


def test_a_capture_that_ends_well_keeps_its_folder(tmp_path: Path) -> None:
    where, _ = _folder(None, tmp_path)
    with fresh.taken_back(where):
        (where / "f000001.png").write_bytes(b"x")
    assert (where / "f000001.png").exists()
