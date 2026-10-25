"""The AVI main header: the frames it declares and their size.

The fixture is a finished 12-frame capture whose `00dc` tag appears 26 times (the index names every
frame again), so `avih` is the one trustworthy count.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from scry_core import avi
from scry_core.reply_contract import Invalid

ZMBV_12 = Path(__file__).parent / "fixtures" / "avi" / "dosbox-x-zmbv-12.avi"


def test_a_finished_capture_declares_its_own_frames_and_size() -> None:
    data = ZMBV_12.read_bytes()
    assert data.count(b"00dc") == 26, "the fixture still shows the doubled tag count"
    assert avi.header(ZMBV_12) == avi.Header(frames=12, width=720, height=400)


def test_a_file_with_no_main_header_answers_none(tmp_path: Path) -> None:
    unfinished = tmp_path / "running.avi"
    unfinished.write_bytes(bytes(2048) + b"00dc" * 3)
    assert avi.header(unfinished) is None
    assert avi.header(tmp_path / "absent.avi") is None


def test_a_header_past_the_first_kilobytes_is_not_looked_for(tmp_path: Path) -> None:
    far = tmp_path / "far.avi"
    data = ZMBV_12.read_bytes()
    at = data.find(b"avih")
    far.write_bytes(data[:at] + bytes(avi.WITHIN) + data[at:])
    assert avi.header(far) is None


def test_a_header_cut_short_answers_none(tmp_path: Path) -> None:
    data = ZMBV_12.read_bytes()
    short = tmp_path / "short.avi"
    short.write_bytes(data[:data.find(b"avih") + 20])
    assert avi.header(short) is None


def test_size_refuses_naming_the_argument_when_there_is_no_header(tmp_path: Path) -> None:
    bad = tmp_path / "x.avi"
    bad.write_bytes(b"RIFF" + bytes(100))
    with pytest.raises(Invalid, match=r"source: .*x\.avi has no AVI main header") as e:
        avi.size("source", bad)
    assert e.value.code == "bad_argument"


def test_size_refuses_a_header_that_declares_no_frame_size(tmp_path: Path) -> None:
    data = bytearray(ZMBV_12.read_bytes())
    at = data.find(b"avih") + 8
    struct.pack_into("<II", data, at + avi.WIDTH_DWORD * 4, 0, 400)
    zero = tmp_path / "zero.avi"
    zero.write_bytes(bytes(data))
    with pytest.raises(Invalid, match=r"declares a 0x400 frame") as e:
        avi.size("source", zero)
    assert e.value.code == "bad_argument"


def test_size_answers_width_and_height() -> None:
    assert avi.size("source", ZMBV_12) == (720, 400)


#: A capture cut while recording: header says 0 frames, no index yet.
RUNNING = Path(__file__).parent / "fixtures" / "avi" / "dosbox-x-zmbv-running.avi"


def test_a_capture_being_written_declares_zero_and_has_no_index() -> None:
    data = RUNNING.read_bytes()
    assert avi.parse(data) == avi.Header(frames=0, width=640, height=480)
    assert b"idx1" not in data


def test_the_frames_of_a_finished_capture_are_its_headers_and_of_a_running_one_its_chunks() -> None:
    assert avi.count(ZMBV_12.read_bytes()) == 12
    assert avi.count(RUNNING.read_bytes()) == 9
    assert avi.count(b"not a video") == 0
    assert avi.finished(ZMBV_12.read_bytes()) and not avi.finished(RUNNING.read_bytes())


def test_size_says_when_a_file_cannot_be_read(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match=r"source: .*absent\.avi cannot be read") as e:
        avi.size("source", tmp_path / "absent.avi")
    assert e.value.code == "bad_argument"
