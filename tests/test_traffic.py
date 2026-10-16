"""The traffic instrument, held on known answers: a reply and a tool list counted by hand, real
transcript lines of both servers counted by another program, the review selection on a table
chosen to sit at its edges, and a run that examined nothing, which is INVALID."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scry_core import traffic
from scry_core.probe import EXIT_INVALID, Invalid

FIXTURES = Path(__file__).parent / "fixtures"
FROZEN_SERVERS = FIXTURES / "probe" / "servers.py"
REAL = FIXTURES / "traffic"

#: Per-tool sums of `JSON.stringify(reply).length`, taken by node over each fixture file: the
#: client's unit counted by a program other than the one under test.
REAL_TOTALS: dict[str, dict[str, int]] = {
    "dosbox-x": {"status": 131, "read_memory": 1252, "machine_map": 12499,
                 "breakpoint_clear": 530},
    "mame": {"status": 188, "read_memory": 286, "machine_map": 9074, "close": 4053},
}
BIG = {"status": "ok", "pad": "x" * traffic.REVIEW_MAX_UNITS}
SMALL = {"status": "ok"}


def _line(tool: str, reply: Any, **rest: Any) -> str:
    return json.dumps({"tool": tool, "args": {}, "reply": reply, **rest}, ensure_ascii=False)


def _transcript(tmp_path: Path, *lines: str, name: str = "t.jsonl") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _servers(tmp_path: Path) -> Path:
    """The frozen servers under a `ROOT` of the test's own, so a table lands in `tmp_path`."""
    servers = tmp_path / "servers.py"
    servers.write_text(
        "import importlib.util\nfrom pathlib import Path\nROOT = Path(__file__).parent\n"
        f"_s = importlib.util.spec_from_file_location('frozen', {str(FROZEN_SERVERS)!r})\n"
        "_m = importlib.util.module_from_spec(_s)\n_s.loader.exec_module(_m)\nload = _m.load\n")
    return servers


def _run(tmp_path: Path, capsys: pytest.CaptureFixture[str], server: str,
         *extra: str) -> tuple[int, list[str]]:
    rc = traffic.main([server, "--servers", str(_servers(tmp_path)), *extra])
    return rc, capsys.readouterr().out.splitlines()


def _table(printed: list[str]) -> dict[str, Any]:
    assert printed[-1].startswith(traffic.LINE_TABLE), printed
    return dict(json.loads(Path(printed[-1].removeprefix(traffic.LINE_TABLE)).read_text()))


def test_a_reply_counted_by_hand() -> None:
    """`{"status":"ok","s":"é😀"}`: 22 characters of ASCII around `é` (1 unit) and an emoji
    outside the BMP (2 units), so 25, where a UTF-8 byte count would say 28 and `len` 24."""
    assert traffic.json_units({"status": "ok", "s": "é\U0001f600"}) == 25


def test_a_tool_list_counted_by_hand() -> None:
    """One tool `ab` whose description is an emoji (2 units, where `len` says 1): its definition
    `{"name":"ab","description":"😀","inputSchema":{}}` is 49 units."""
    async def list_tools() -> list[Any]:
        return [SimpleNamespace(name="ab", description="\U0001f600", input_schema=None)]
    listed = traffic.tool_list(SimpleNamespace(mcp=SimpleNamespace(instructions="ins",
                                                                   list_tools=list_tools)))
    assert listed == {"instructions": 3, "names": 2, "descriptions": 2, "definitions": 49,
                      "tools": {"ab": {"description": 2, "definition": 49}}}


def test_attached_pictures_counted_by_hand(tmp_path: Path) -> None:
    """Three `image` blocks, counted by hand in tiles of 28 px: a 960x720 picture attached at
    the top (35 x 26 = 910), a 256x64 one in a `perform` step's reply (10 x 3 = 30), and a
    3000x3000 one written and NOT attached (`inline: false`), which costs nothing."""
    shown = {"status": "ok", "image": {"inline": True, "width": 960, "height": 720}}
    stepped = {"status": "ok", "ran": [{"op": "palette", "reply": {
        "status": "ok", "image": {"inline": True, "width": 256, "height": 64}}}]}
    unshown = {"status": "ok", "image": {"inline": False, "width": 3000, "height": 3000}}
    assert traffic.image_tokens(shown) == 910
    assert traffic.image_tokens(stepped) == 30
    assert traffic.image_tokens(unshown) == 0
    calls = traffic.read_transcripts([_transcript(
        tmp_path, _line("screen_view", shown), _line("perform", stepped),
        _line("screen_view", unshown))])
    assert calls.image_tokens == {"screen_view": [910, 0], "perform": [30]}
    # The edge of one tile: 28 pixels is one, 29 is two.
    assert traffic.image_tokens({"image": {"inline": True, "width": 28, "height": 29}}) == 2


def test_a_picture_block_with_no_size_is_invalid(tmp_path: Path) -> None:
    """An attached picture whose size the reply does not state cannot be counted, and a zero
    in its place would read as a picture that cost nothing."""
    block = {"status": "ok", "image": {"inline": True, "height": 8}}
    with pytest.raises(Invalid, match="width"):
        traffic.image_tokens(block)
    # A JSON `true` is a Python int, and a picture has at least one pixel a side: neither is a
    # size, and counting either would read as a picture that cost one tile, or nothing.
    for w, h in ((True, True), (0, 28), (28, -56), (-56, -56), (28, 2.0)):
        with pytest.raises(Invalid, match="cannot be counted"):
            traffic.image_tokens({"image": {"inline": True, "width": w, "height": h}})
    # Integer tiles: a size past a float's range is still counted, exactly.
    assert traffic.image_tokens({"image": {"inline": True, "width": 28 * 10**400 + 1,
                                           "height": 28}}) == 10**400 + 1
    path = _transcript(tmp_path, _line("status", SMALL), _line("screen_view", block))
    with pytest.raises(Invalid, match=r"t\.jsonl:2: an attached picture states width=None"):
        traffic.read_transcripts([path])


def test_real_lines_of_both_servers_match_the_clients_count() -> None:
    for server, totals in REAL_TOTALS.items():
        calls = traffic.read_transcripts([REAL / f"{server}.jsonl"])
        assert {t: sum(u) for t, u in calls.units.items()} == totals, server


def test_a_line_separator_inside_a_string_does_not_cut_the_record(tmp_path: Path) -> None:
    reply = {"status": "ok", "text": "a b\u0085c"}
    calls = traffic.read_transcripts([_transcript(tmp_path, _line("status", reply))])
    assert calls.units == {"status": [traffic.json_units(reply)]}


def test_what_is_not_a_reply_is_skipped_and_counted(tmp_path: Path) -> None:
    path = _transcript(
        tmp_path,
        _line("status", SMALL),
        _line("(matrix)", {"exception": "boom", "status": "x"}),
        _line("read_memory", {"exception": "ValueError: x", "traceback": "..."}),
        _line("start", {"hung": True}),
        _line("start", ["status"]),
        json.dumps({"tool": 3, "reply": SMALL}),
        json.dumps(["not", "a", "record"]),
        "",
    )
    calls = traffic.read_transcripts([path])
    assert calls.units == {"status": [traffic.json_units(SMALL)]}
    assert calls.skipped == 6


@pytest.mark.parametrize("lines, said", [
    ((), "hold no reply"),
    ((_line("(board)", {"exception": "no boot"}),), r"1 line\(s\) skipped"),
    (("{not json",), "is not JSON"),
])
def test_a_transcript_with_no_reply_is_invalid(tmp_path: Path, lines: tuple[str, ...],
                                                said: str) -> None:
    with pytest.raises(Invalid, match=said):
        traffic.read_transcripts([_transcript(tmp_path, *lines)])


def test_a_transcript_that_is_not_utf8_is_invalid(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    path.write_bytes(b"\xff\n")
    with pytest.raises(Invalid, match="--transcript"):
        traffic.read_transcripts([path])


def test_the_review_takes_the_pareto_set_and_every_reply_over_the_ceiling() -> None:
    """a+b make 80 of 100 units exactly, so c is outside the set; d is outside it too but one of
    its replies is one unit over the ceiling, and e sits AT the ceiling, which is not over it."""
    totals = {"a": 50, "b": 30, "c": 10, "d": 6, "e": 4}
    maxima = {"a": 10, "b": 10, "c": 10, "d": traffic.REVIEW_MAX_UNITS + 1,
              "e": traffic.REVIEW_MAX_UNITS}
    assert traffic.for_review(totals, maxima) == {"a": ["share"], "b": ["share"], "d": ["max"]}
    # One unit short of the share with a and b leaves c in the set too.
    assert set(traffic.for_review({**totals, "b": 29, "c": 11}, maxima)) == {"a", "b", "c", "d"}
    # A tie at the cut goes to the name that sorts first.
    assert traffic.for_review({"y": 40, "x": 40, "z": 20}, {}) == {"x": ["share"], "y": ["share"]}
    assert traffic.for_review({"y": 79, "x": 11, "w": 11}, {}) == {"y": ["share"], "w": ["share"]}


def test_the_command_writes_the_table_and_prints_one_line_per_flagged_tool(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _transcript(tmp_path, _line("read_memory", BIG), _line("watch_add", SMALL),
                       _line("watch_add", {"status": "ok", "n": 1}), _line("watch_add", SMALL))
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript", str(path))
    assert rc == traffic.EXIT_TABLE, printed
    doc = _table(printed)
    assert Path(printed[-1].removeprefix(traffic.LINE_TABLE)).parent == (
        tmp_path / traffic.TABLES_UNDER_ROOT)
    assert doc["format"] == traffic.TABLE_FORMAT and doc["server"] == "mame"
    small = traffic.json_units(SMALL)
    assert doc["per_tool"]["watch_add"] == {
        "calls": 3, "max": small + 6, "p50": small, "total": 3 * small + 6,
        "share": round((3 * small + 6) / doc["replies"]["units"], 4), "review": [],
        "image_tokens": 0}
    assert doc["per_tool"]["read_memory"]["review"] == ["max", "share"]
    assert doc["replies"] == {"calls": 4, "units": traffic.json_units(BIG) + 3 * small + 6,
                              "image_tokens": 0, "skipped": 0, "foreign": {},
                              "unmeasured": ["memdump", "status"]}
    reviews = [p for p in printed if p.startswith(traffic.LINE_REVIEW)]
    assert len(reviews) == 1, printed
    assert reviews[0].startswith("REVIEW mame read_memory [max,share] calls=1 ")
    assert printed[-2].startswith("TOTAL mame replies calls=4 ")


def test_image_tokens_are_summed_per_tool_and_leave_foreign_calls_out(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two attached pictures under one tool sum (1 + 4 tiles), a second tool adds its own (2),
    and a picture under a name the server does not list counts nowhere."""
    def shown(w: int, h: int) -> dict[str, Any]:
        return {"status": "ok", "image": {"inline": True, "width": w, "height": h}}
    path = _transcript(tmp_path, _line("status", shown(28, 28)), _line("status", shown(56, 56)),
                       _line("read_memory", shown(28, 56)), _line("helper", shown(280, 280)))
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript", str(path))
    assert rc == traffic.EXIT_TABLE, printed
    doc = _table(printed)
    assert doc["per_tool"]["status"]["image_tokens"] == 5
    assert doc["per_tool"]["read_memory"]["image_tokens"] == 2
    assert doc["replies"]["image_tokens"] == 7
    assert " image_tokens=7 " in printed[-2], printed


def test_two_transcripts_are_one_measurement(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    one = _transcript(tmp_path, _line("status", SMALL), name="1.jsonl")
    two = _transcript(tmp_path, _line("status", SMALL), name="2.jsonl")
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript", str(one), "--transcript",
                       str(two))
    assert rc == traffic.EXIT_TABLE and _table(printed)["per_tool"]["status"]["calls"] == 2


def test_a_transcript_of_another_server_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, printed = _run(tmp_path, capsys, "dosbox-x", "--transcript", str(REAL / "mame.jsonl"))
    assert rc == EXIT_INVALID and "none of which dosbox-x lists" in printed[0], printed


def test_a_name_the_server_does_not_list_is_set_apart_not_measured(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A live harness records its own helpers by name beside the tools (a start sent through
    the schema, say): those are counted under `foreign`, outside every figure."""
    path = _transcript(tmp_path, _line("status", SMALL), _line("start_through_the_schema", BIG),
                       _line("start_through_the_schema", BIG))
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript", str(path))
    assert rc == traffic.EXIT_TABLE, printed
    doc = _table(printed)
    assert doc["replies"]["foreign"] == {"start_through_the_schema": 2}
    assert doc["replies"]["calls"] == 1 and set(doc["per_tool"]) == {"status"}
    small = traffic.json_units(SMALL)
    assert doc["replies"]["units"] == small
    assert doc["per_tool"]["status"] == {"calls": 1, "max": small, "p50": small, "total": small,
                                         "share": 1.0, "review": ["share"], "image_tokens": 0}
    reviews = [p for p in printed if p.startswith(traffic.LINE_REVIEW)]
    assert len(reviews) == 1 and reviews[0].startswith("REVIEW mame status [share] "), printed
    assert " foreign=2 (start_through_the_schema) " in printed[-2], printed


def test_before_puts_the_earlier_figures_beside_each_line(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript",
                       str(_transcript(tmp_path, _line("read_memory", BIG))))
    assert rc == traffic.EXIT_TABLE
    first = Path(printed[-1].removeprefix(traffic.LINE_TABLE))
    earlier = json.loads(first.read_text())
    earlier["list"].update(instructions=1, names=2, descriptions=3, definitions=4)
    # A table written before `foreign` existed is still a valid one to compare against.
    del earlier["replies"]["foreign"]
    # ... and so is one written before `image_tokens`.
    del earlier["replies"]["image_tokens"]
    del earlier["per_tool"]["read_memory"]["image_tokens"]
    first.write_text(json.dumps(earlier))
    # A 28x29 picture is 1 x 2 tiles; the earlier table predates `image_tokens` (was -).
    pictured = {**BIG, "image": {"inline": True, "width": 28, "height": 29}}
    later = _transcript(tmp_path, _line("read_memory", pictured), _line("watch_add", SMALL),
                        name="s.jsonl")
    rc, printed = _run(tmp_path, capsys, "mame", "--transcript", str(later), "--before",
                       str(first))
    was = traffic.json_units(BIG)
    now = traffic.json_units(pictured)
    assert rc == traffic.EXIT_TABLE and f"max={now} (was {was})" in printed[0], printed
    assert " image_tokens=2 (was -) " in printed[0], printed
    total = printed[-2]
    assert f"units={now + traffic.json_units(SMALL)} (was {was})" in total, total
    assert " image_tokens=2 (was -) " in total, total
    for k, n in (("instructions", 1), ("names", 2), ("descriptions", 3), ("definitions", 4)):
        assert f"(was {n})" in total.split(f" {k}=")[1], (k, total)
    # A tool the earlier table never saw says so rather than inventing a figure.
    assert traffic._was(earlier, "per_tool", "watch_add", "max") == " (was -)"


@pytest.mark.parametrize("extra, said", [
    (["--transcript", "absent.jsonl"], "--transcript absent.jsonl"),
    (["--before", "absent.json"], "--before absent.json"),
])
def test_a_missing_input_is_invalid(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                    extra: list[str], said: str) -> None:
    rc, printed = _run(tmp_path, capsys, "mame", *extra)
    assert rc == EXIT_INVALID and printed[0].startswith("INVALID ") and said in printed[0]


@pytest.mark.parametrize("doc, said", [
    ("{half", "--before"),
    ({"format": "x"}, "is not a scry-traffic/1 table"),
    ({"format": traffic.TABLE_FORMAT, "server": "dosbox-x"}, "measured 'dosbox-x', not 'mame'"),
    ({"format": traffic.TABLE_FORMAT, "server": "mame", "replies": {"calls": 1},
      "per_tool": {}, "list": {"instructions": 1}},
     "lacks replies.units, replies.skipped, replies.unmeasured, list.names"),
    ({"format": traffic.TABLE_FORMAT, "server": "mame", "replies": None,
      "list": {"instructions": 1, "names": 1, "descriptions": 1, "definitions": 1,
               "tools": {}}}, "lacks per_tool"),
])
def test_a_before_of_another_shape_or_server_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], doc: dict[str, Any] | str,
        said: str) -> None:
    other = tmp_path / "other.json"
    other.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    rc, printed = _run(tmp_path, capsys, "mame", "--before", str(other))
    assert rc == EXIT_INVALID and said in printed[0], printed


def test_a_list_only_table_is_a_valid_before(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, printed = _run(tmp_path, capsys, "dosbox-x")
    assert rc == traffic.EXIT_TABLE and printed[0].startswith("TOTAL dosbox-x list tools=1 ")
    assert _table(printed)["replies"] is None
    rc, again = _run(tmp_path, capsys, "dosbox-x", "--before",
                     printed[-1].removeprefix(traffic.LINE_TABLE))
    assert rc == traffic.EXIT_TABLE and "(was " in again[0], again


def test_an_unknown_server_is_a_usage_error(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as e:
        traffic.main(["nope", "--servers", str(_servers(tmp_path))])
    assert e.value.code == 2 and "invalid choice: 'nope'" in capsys.readouterr().err


def test_a_server_with_no_tools_and_a_table_that_cannot_be_written_are_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    empty = tmp_path / "servers.py"
    empty.write_text(
        "from pathlib import Path\nfrom types import SimpleNamespace\nROOT = Path('.')\n"
        "async def _none():\n    return []\n"
        "def load():\n    return {'s': SimpleNamespace(mcp=SimpleNamespace("
        "instructions='i', list_tools=_none))}\n")
    assert traffic.main(["s", "--servers", str(empty)]) == EXIT_INVALID
    assert "lists no tools" in capsys.readouterr().out
    blocked = tmp_path / "ro"
    blocked.mkdir()
    (blocked / "tmp").write_text("a file where the tables' directory would go")
    with pytest.raises(Invalid, match="could not be written"):
        traffic.write_table({}, blocked, "mame")


def test_an_exception_nobody_expected_is_invalid_not_a_traceback_exit(
        tmp_path: Path, capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: Any) -> Any:
        raise RuntimeError("boom")
    for name in ("tool_list", "report"):
        with monkeypatch.context() as m:
            m.setattr(traffic, name, boom)
            rc, printed = _run(tmp_path, capsys, "mame")
        assert rc == EXIT_INVALID and "boom" in printed[-1], (name, printed)
