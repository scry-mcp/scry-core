"""`scry_core.window_capture`: the BMP it reads back, the difference of two captures measured from
the box of what changed, a window found by its owner's pid, and every way the host can refuse a
capture said as `Blocked`, never raised as something else."""

from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

import pytest

from scry_core import focus_watch as fw
from scry_core import window_capture as wc

Pixel = tuple[int, int, int]


def _bmp(path: Path, rows: list[list[Pixel]], bpp: int = 24, top_down: bool = False) -> Path:
    """A BMP of `rows` (top row first), as `sips` writes one."""
    width, height = len(rows[0]), len(rows)
    step = bpp // 8
    stride = (width * step + 3) & ~3
    body = b""
    for row in (rows if top_down else rows[::-1]):
        line = b"".join(bytes((b, g, r)) + (b"\xff" if step == 4 else b"") for r, g, b in row)
        body += line + b"\0" * (stride - len(line))
    header = struct.pack("<2sIHHI", b"BM", 54 + len(body), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, bpp, 0,
                       len(body), 0, 0, 0, 0)
    path.write_bytes(header + info + body)
    return path


@pytest.mark.parametrize(("bpp", "top_down"), [(24, False), (32, False), (32, True)])
def test_a_bmp_comes_back_top_row_first_in_rgb(tmp_path: Path, bpp: int, top_down: bool) -> None:
    rows = [[(1, 2, 3), (4, 5, 6), (7, 8, 9)], [(10, 11, 12), (13, 14, 15), (16, 17, 18)]]
    image = wc.read_bmp(_bmp(tmp_path / "a.bmp", rows, bpp, top_down))
    assert (image.width, image.height) == (3, 2)
    assert [image.pixels(y) for y in range(image.height)] == rows


FIXTURES = Path(__file__).parent / "fixtures" / "window_capture"
#: What both fixtures hold: `sips` converted the same 3x2 picture, once with an alpha channel.
KNOWN = [[(255, 0, 0), (0, 255, 0), (0, 0, 255)], [(255, 140, 0), (10, 20, 30), (255, 255, 255)]]


@pytest.mark.parametrize("name", ["sips-rgb24.bmp", "sips-rgba32.bmp"])
def test_what_sips_writes_reads_back_as_the_picture_it_was(name: str) -> None:
    image = wc.read_bmp(FIXTURES / name)
    assert [image.pixels(y) for y in range(image.height)] == KNOWN


def test_bitfields_in_another_order_is_refused_rather_than_read_swapped(tmp_path: Path) -> None:
    data = bytearray((FIXTURES / "sips-rgba32.bmp").read_bytes())
    struct.pack_into("<III", data, 54, 0xFF, 0xFF00, 0xFF0000)
    (tmp_path / "rgb.bmp").write_bytes(bytes(data))
    with pytest.raises(ValueError, match="compression 3"):
        wc.read_bmp(tmp_path / "rgb.bmp")


def test_a_bmp_shorter_than_its_rows_is_refused(tmp_path: Path) -> None:
    (tmp_path / "cut.bmp").write_bytes((FIXTURES / "sips-rgb24.bmp").read_bytes()[:-4])
    with pytest.raises(ValueError, match="shorter"):
        wc.read_bmp(tmp_path / "cut.bmp")


def test_what_is_not_a_bmp_this_reads_is_refused(tmp_path: Path) -> None:
    (tmp_path / "x.bmp").write_bytes(b"PNG nope" + bytes(60))
    with pytest.raises(ValueError, match="not a BMP"):
        wc.read_bmp(tmp_path / "x.bmp")
    eight = bytearray(_bmp(tmp_path / "y.bmp", [[(0, 0, 0)]]).read_bytes())
    eight[28:30] = struct.pack("<H", 8)
    (tmp_path / "y.bmp").write_bytes(bytes(eight))
    with pytest.raises(ValueError, match="8-bit"):
        wc.read_bmp(tmp_path / "y.bmp")


def _image(width: int, height: int, paint: dict[tuple[int, int], Pixel] | None = None
           ) -> wc.Image:
    paint = paint or {}
    return wc.Image.of([[paint.get((x, y), (0, 0, 0)) for x in range(width)]
                        for y in range(height)])


def test_a_frame_on_the_inner_edges_is_shallow_and_spans_the_content() -> None:
    w, h = 40, 30
    # rows 0-4 are a title bar nothing draws on; the content's outermost ring turns orange
    ring = {(x, y): (200, 100, 0) for x in range(w) for y in range(5, h)
            if x in (0, w - 1) or y in (5, h - 1)}
    d = wc.difference(_image(w, h), _image(w, h, ring))
    assert d.changed == len(ring) and d.box == (0, 5, w - 1, h - 1)
    assert d.span == (1.0, 25 / 30) and d.deepest == 0.0
    assert min(d.sides) > 0 and sum(d.sides) == d.changed
    assert d.delta == (200.0, 100.0, 0.0)


def test_a_change_on_two_sides_only_leaves_the_other_two_empty() -> None:
    w, h = 20, 20
    l_shape = {(x, y): (9, 9, 9) for x in range(w) for y in range(h) if x == 0 or y == 0}
    l_shape[(w - 1, h - 1)] = (9, 9, 9)          # one far corner, so the box is the whole image
    d = wc.difference(_image(w, h), _image(w, h, l_shape))
    # only the corners tie onto the far sides: a frame drawn on two sides is not one on four
    assert d.sides[0] > 0 and d.sides[2] > 0 and d.sides[1] + d.sides[3] <= 2


def test_a_change_in_the_middle_is_deep() -> None:
    corners = {(0, 0): (9, 9, 9), (19, 19): (9, 9, 9), (10, 10): (9, 9, 9)}
    d = wc.difference(_image(20, 20), _image(20, 20, corners))
    assert d.deepest == pytest.approx(9 / 19)


def test_identical_captures_differ_nowhere_and_sizes_must_match() -> None:
    assert wc.difference(_image(3, 3), _image(3, 3)).changed == 0
    with pytest.raises(ValueError, match="differ in size"):
        wc.difference(_image(3, 3), _image(4, 3))


def test_the_window_of_a_pid_is_its_largest_ordinary_one(monkeypatch: pytest.MonkeyPatch) -> None:
    listed = [
        {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 0, "kCGWindowNumber": 1,
         "kCGWindowBounds": {"Width": 10, "Height": 10}},
        {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 0, "kCGWindowNumber": 2,
         "kCGWindowBounds": {"Width": 300, "Height": 200}},
        {"kCGWindowOwnerPID": 7, "kCGWindowLayer": 25, "kCGWindowNumber": 3,
         "kCGWindowBounds": {"Width": 900, "Height": 900}},
        {"kCGWindowOwnerPID": 8, "kCGWindowLayer": 0, "kCGWindowNumber": 4,
         "kCGWindowBounds": {"Width": 900, "Height": 900}},
    ]
    monkeypatch.setattr(fw, "windows", lambda: listed)
    assert wc.window_of(7) == 2 and wc.window_of(9) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="the window server is macOS's")
def test_the_window_server_lists_windows() -> None:
    assert isinstance(fw.windows(), list)


def test_off_macos_a_capture_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(wc.Blocked, match="macOS only"):
        wc.capture(1, tmp_path / "w.png")


def _darwin(monkeypatch: pytest.MonkeyPatch, window: int | None) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(wc, "window_of", lambda pid: window)


def test_a_pid_with_no_window_is_blocked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _darwin(monkeypatch, None)
    with pytest.raises(wc.Blocked, match="owns no window"):
        wc.capture(1, tmp_path / "w.png")


def test_a_refused_capture_or_conversion_is_blocked_and_a_good_one_read(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _darwin(monkeypatch, 42)
    calls: list[list[str]] = []

    def refuse(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 1, "", "could not create image")
    monkeypatch.setattr(subprocess, "run", refuse)
    with pytest.raises(wc.Blocked, match="Screen Recording"):
        wc.capture(1, tmp_path / "w.png")
    assert calls[0][:5] == ["screencapture", "-x", "-o", "-l", "42"]

    def capture_only(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"png")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 13, "", "sips broke")
    monkeypatch.setattr(subprocess, "run", capture_only)
    with pytest.raises(wc.Blocked, match="sips could not convert"):
        wc.capture(1, tmp_path / "w2.png")

    def both(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"png")
        else:
            _bmp(Path(argv[-1]), [[(5, 6, 7)]])
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", both)
    with pytest.raises(wc.Blocked, match="one colour"):
        wc.capture(1, tmp_path / "w3.png")

    def real(argv: list[str], **_k: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == "screencapture":
            Path(argv[-1]).write_bytes(b"png")
        else:
            Path(argv[-1]).write_bytes((FIXTURES / "sips-rgb24.bmp").read_bytes())
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", real)
    got = wc.capture(1, tmp_path / "w4.png")
    assert [got.pixels(y) for y in range(got.height)] == KNOWN


@pytest.mark.parametrize("raised", [subprocess.TimeoutExpired("screencapture", 15),
                                    FileNotFoundError("screencapture")])
def test_a_host_tool_that_hangs_or_is_missing_is_blocked(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raised: BaseException) -> None:
    _darwin(monkeypatch, 42)

    def fail(*_a: object, **_k: object) -> None:
        raise raised
    monkeypatch.setattr(subprocess, "run", fail)
    with pytest.raises(wc.Blocked, match="could not be captured"):
        wc.capture(1, tmp_path / "w.png")


def test_the_edge_verdict_takes_a_frame_and_refuses_a_box_in_the_middle() -> None:
    w, h = 100, 80
    edge = max(1, round(w * 0.025))
    ring = {(x, y): (255, 140, 0) for x in range(w) for y in range(h)
            if min(x, y, w - 1 - x, h - 1 - y) < edge}
    drawn, said = wc.edge_verdict(wc.difference(_image(w, h), _image(w, h, ring)))
    assert drawn, said
    blob = {(x, y): (255, 140, 0) for x in range(40, 60) for y in range(30, 50)}
    drawn, said = wc.edge_verdict(wc.difference(_image(w, h), _image(w, h, blob)))
    assert not drawn and "pixels changed" in said
