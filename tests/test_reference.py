"""`scry_core.reference`: a server's reference generated from its registry, held to it by `drift`,
and its examples picked from a live run's transcript."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from mcp.server.mcpserver import MCPServer
from pydantic import Field

from scry_core import demo, reference, reply_schema, roster
from scry_core.demo import Normaliser
from scry_core.reference import begin_marker, end_marker
from scry_core.strict_arguments import registered, strict_arguments
from scry_core.verdict import Invalid

EXAMPLES = reference.EXAMPLES_PATH


class FixtureEnvelope(reply_schema.ReplyEnvelope, total=False):
    last_stop: dict[str, Any]


class PeekReply(FixtureEnvelope, total=False):
    value: int
    bytes_read: list[int]
    kind: Literal["byte", "word"]


class PokeReply(FixtureEnvelope, total=False):
    written: bool | dict[str, Any]


def _server() -> MCPServer:
    server = MCPServer("fixture")

    @server.tool(title="Peek at memory")
    def peek(addr: str, length: int = 1, mode: Literal["byte", "word"] = "byte") -> dict[str, Any]:
        """Read `length` bytes at `addr`, a <ref> as typed, `x<y` kept in a code span.

        Reply: `value`, `bytes_read`, `kind`."""
        return {"status": "ok"}

    @server.tool()
    def poke(addr: str, value: int) -> dict[str, Any]:
        """Write `value` at `addr`. Reply: `written`."""
        return {"status": "ok"}

    strict_arguments(server)
    return server


def _registry(root: Path, families: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Read", ("peek",)), ("Write memory", ("poke",)))) -> reference.Registry:
    return reference.Registry(server=_server(), models={"peek": PeekReply, "poke": PokeReply},
                              roster=roster.Roster(families=families, answering=()),
                              envelope=FixtureEnvelope, root=root)


def _one_page(root: Path) -> reference.Registry:
    return _registry(root, (("Read", ("peek", "poke")),))


def _examples(root: Path, tools: tuple[str, ...] = ("peek", "poke"),
              call: dict[str, Any] | None = None) -> None:
    path = root / EXAMPLES
    path.parent.mkdir(parents=True, exist_ok=True)
    calls = {"peek": {"addr": "0x10"}, "poke": {"addr": "0x10", "value": 1}}
    path.write_text(json.dumps({t: {"from": "[A] fixture: a cell",
                                    "call": call or calls.get(t, {"addr": "0x10"}),
                                    "reply": {"status": "ok"}} for t in tools}),
                    encoding="utf-8")


def _written(reg: reference.Registry) -> reference.Registry:
    _examples(reg.root)
    reference.write(reg)
    return reg


def _read(tmp_path: Path, page: str = "read") -> str:
    return (tmp_path / f"docs/reference/{page}.md").read_text(encoding="utf-8")


def _block(text: str, name: str) -> str:
    return text[text.index(begin_marker(name)):text.index(end_marker(name))
                + len(end_marker(name))]


# ======================================================================== the blocks


def test_a_tool_block_names_every_argument_its_type_its_default_and_whether_it_is_required(
        tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    text = _read(tmp_path)
    assert "## `peek`" in text and "*Peek at memory*" in text, text
    assert 'peek(addr, length=1, mode="byte")' in text, text
    assert "| `addr` | string | required |" in text, text
    assert "| `length` | integer | `1` |" in text, text
    assert '| `mode` | one of `"byte"`, `"word"` | `"byte"` |' in text, text
    assert reference.drift(reg) == []


def test_the_reply_fields_are_the_model_s_own_beyond_the_server_s_envelope(
        tmp_path: Path) -> None:
    _written(_registry(tmp_path))
    text = _read(tmp_path)
    assert "| `value` | integer |" in text and "| `bytes_read` | array of integer |" in text, text
    assert '| `kind` | one of `"byte"`, `"word"` |' in text, text
    assert "`last_stop`" not in text.split("## `peek`")[1], "the envelope is REFERENCE.md's"
    assert "| `written` | boolean or object |" in _read(tmp_path, "write-memory")


def test_the_index_and_the_envelope_go_to_reference_md_in_the_roster_s_order(
        tmp_path: Path) -> None:
    _written(_registry(tmp_path))
    text = (tmp_path / "REFERENCE.md").read_text(encoding="utf-8")
    read, write = text.index("[Read](docs/reference/read.md)"), text.index(
        "[Write memory](docs/reference/write-memory.md)")
    assert read < write and "[`peek`](docs/reference/read.md#peek)" in text, text
    assert "| `status` |" in text and "| `last_stop` | object |" in text, text


def test_a_description_s_bare_angle_bracket_is_text_and_its_paragraphs_stay_flush(
        tmp_path: Path) -> None:
    _written(_registry(tmp_path))
    text = _block(_read(tmp_path), "peek")
    assert "a &lt;ref> as typed, `x<y` kept in a code span" in text, text
    assert "\nReply: `value`" in text, "the SDK dedents; an indented one would be a code block"


def test_an_argument_s_bounds_its_alternatives_its_items_and_a_constant_are_named() -> None:
    server = MCPServer("bounds")

    @server.tool()
    def take(count: Annotated[int, Field(ge=1, le=128)] = 1,
             seconds: Annotated[float, Field(gt=0)] = 1.0,
             names: list[str] | None = None,
             tag: Annotated[str, Field(pattern=r"^[a-z]+$")] = "a",
             unit: Literal["s"] = "s") -> dict[str, Any]:
        """Take. Reply: `written`."""
        return {"status": "ok"}

    @server.tool()
    def tick() -> dict[str, Any]:
        """Tick, taking nothing and adding nothing to the envelope."""
        return {"status": "ok"}

    strict_arguments(server)
    tools = {t.name: t for t in registered(server)}
    block = reference.tool_block(tools["take"], PokeReply, FixtureEnvelope, None)
    assert "| `count` | integer (>= 1, <= 128) | `1` |" in block, block
    assert "| `seconds` | number (> 0) | `1.0` |" in block, block
    assert "| `names` | array of string or null | `null` |" in block, block
    assert "| `tag` | string (matching `^[a-z]+$`) | `\"a\"` |" in block, block
    assert '| `unit` | `"s"` | `"s"` |' in block, block
    assert "No example yet" in block, block
    bare = reference.tool_block(tools["tick"], FixtureEnvelope, FixtureEnvelope, None)
    assert "Takes no argument." in bare and "the envelope's fields only" in bare, bare


def test_the_example_is_the_transcript_s_call_and_reply_with_its_source(tmp_path: Path) -> None:
    _written(_registry(tmp_path))
    text = _read(tmp_path)
    assert "Example, from a live run:" in text, text
    assert '"addr": "0x10"' in text and '"status": "ok"' in text, text


# ===================================================================== the comparison


def test_one_parameter_line_edited_by_hand_is_drift_naming_the_tool_and_its_file(
        tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    page.write_text(page.read_text(encoding="utf-8").replace(
        "| `length` | integer | `1` |", "| `length` | integer | `2` |"), encoding="utf-8")
    found = reference.drift(reg)
    assert len(found) == 1 and found[0].startswith("`peek` in docs/reference/read.md: line "), found


def test_a_missing_page_a_missing_block_a_stray_one_and_a_stray_file_are_each_drift(
        tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    read = tmp_path / "docs/reference/read.md"
    poke = begin_marker("poke") + "\nold\n" + end_marker("poke")
    read.write_text(read.read_text(encoding="utf-8") + "\n" + poke + "\n", encoding="utf-8")
    (tmp_path / "docs/reference/write-memory.md").write_text("# The Write memory tools\n",
                                                             encoding="utf-8")
    (tmp_path / "docs/reference/gone.md").write_text("# Gone\n", encoding="utf-8")
    ref = tmp_path / "REFERENCE.md"
    ref.write_text(ref.read_text(encoding="utf-8") + "\n" + begin_marker("x") + "\n"
                   + end_marker("x") + "\n", encoding="utf-8")
    found = reference.drift(reg)
    assert "docs/reference/read.md: `poke` is no tool of the Read family" in found, found
    assert "docs/reference/write-memory.md: no block for `poke`" in found, found
    assert "docs/reference/gone.md: names no family" in found, found
    assert "REFERENCE.md: `x` is no block of it" in found, found
    reference.write(reg)
    assert reference.drift(reg) == ["docs/reference/gone.md: names no family"]
    (tmp_path / "docs/reference/write-memory.md").unlink()
    assert "docs/reference/write-memory.md: missing, and it holds poke" in reference.drift(reg)


def test_a_block_out_of_the_roster_s_order_is_drift(tmp_path: Path) -> None:
    reg = _written(_one_page(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    text = page.read_text(encoding="utf-8")
    peek = _block(text, "peek")
    page.write_text(text.replace(peek, "") + "\n" + peek + "\n", encoding="utf-8")
    assert reference.drift(reg) == [
        "docs/reference/read.md: blocks out of the roster's order: poke, peek"]


def test_an_end_marker_with_no_begin_is_drift_naming_it(tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    page.write_text(page.read_text(encoding="utf-8") + "\n" + end_marker("peek") + "\n",
                    encoding="utf-8")
    assert reference.drift(reg) == [
        "docs/reference/read.md: an end marker for `peek` closes no open block"]


@pytest.mark.parametrize("broken", [begin_marker("peek") + "\n",
                                    begin_marker("a") + "\n" + begin_marker("b") + "\n"])
def test_a_begin_marker_never_closed_is_drift_and_a_rewrite_writes_nothing(
        tmp_path: Path, broken: str) -> None:
    reg = _written(_registry(tmp_path))
    ref = tmp_path / "REFERENCE.md"
    ref.write_text("# Reference\n", encoding="utf-8")
    page = tmp_path / "docs/reference/read.md"
    page.write_text(page.read_text(encoding="utf-8") + broken, encoding="utf-8")
    assert any(f.startswith("docs/reference/read.md: `") for f in reference.drift(reg))
    with pytest.raises(Invalid, match="docs/reference/read.md"):
        reference.write(reg)
    assert ref.read_text(encoding="utf-8") == "# Reference\n", "a page was written before it"


def test_a_tool_with_no_example_an_example_of_no_tool_and_a_stale_call_are_drift(
        tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    _examples(tmp_path, ("peek", "gone"), {"addr": "0x10", "width": 4})
    found = reference.drift(reg)
    assert f"`poke` has no example in {EXAMPLES}" in found, found
    assert f"{EXAMPLES}: `gone` is no tool" in found, found
    assert any(f.startswith(f"{EXAMPLES}: `peek`'s example call is one the tool refuses (width")
               for f in found), found


def test_a_registry_with_no_tool_compares_nothing_and_is_invalid(tmp_path: Path) -> None:
    empty = reference.Registry(server=MCPServer("e"), models={}, envelope=FixtureEnvelope,
                               roster=roster.Roster(families=(), answering=()), root=tmp_path)
    with pytest.raises(Invalid, match="no tool"):
        reference.drift(empty)


@pytest.mark.parametrize(("families", "named"), [
    ((("Read", ("peek", "gone")), ("Write memory", ("poke",))), "not registered: gone"),
    ((("Read", ("peek",)),), "in no family: poke"),
    ((("Read", ("peek",)), ("read", ("poke",))), "two families share a page"),
])
def test_a_roster_that_is_not_the_registry_is_invalid(
        tmp_path: Path, families: tuple[tuple[str, tuple[str, ...]], ...], named: str) -> None:
    with pytest.raises(Invalid, match=named):
        reference.drift(_registry(tmp_path, families))


def test_a_tool_with_no_reply_model_is_invalid(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg = reference.Registry(server=reg.server, models={"peek": PeekReply}, roster=reg.roster,
                             envelope=reg.envelope, root=tmp_path)
    with pytest.raises(Invalid, match="no reply model: \\['poke'\\]"):
        reference.drift(reg)


# ======================================================================== the rewrite


def test_the_hand_prose_between_blocks_and_the_page_s_head_survive_a_rewrite(
        tmp_path: Path) -> None:
    reg = _written(_one_page(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    text = page.read_text(encoding="utf-8")
    text = text.replace("# The Read tools\n", "# The Read tools\n\nWhat the family does.\n", 1)
    text = text.replace(begin_marker("poke"), "Why peek.\n\n" + begin_marker("poke"))
    page.write_text(text.replace("integer", "int") + "\nWhy poke.\n", encoding="utf-8")
    assert reference.write(reg) == ["docs/reference/read.md"]
    final = page.read_text(encoding="utf-8")
    assert reference.drift(reg) == [] and reference.write(reg) == []
    assert final.index("What the family does.") < final.index(begin_marker("peek")) \
        < final.index("Why peek.") < final.index(begin_marker("poke")) < final.index("Why poke.")


def test_a_rewrite_puts_blocks_back_in_the_roster_s_order_with_their_prose(
        tmp_path: Path) -> None:
    reg = _written(_one_page(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    text = page.read_text(encoding="utf-8")
    peek, poke = _block(text, "peek"), _block(text, "poke")
    page.write_text(f"# The Read tools\n\n{poke}\n\nWhy poke.\n\n{peek}\n\nWhy peek.\n",
                    encoding="utf-8")
    assert reference.drift(reg), "the setup must be out of order"
    reference.write(reg)
    final = page.read_text(encoding="utf-8")
    assert reference.drift(reg) == [], final
    assert final.index(begin_marker("peek")) < final.index("Why peek.") \
        < final.index(begin_marker("poke")) < final.index("Why poke."), final


def test_a_rewrite_places_a_missing_block_at_its_roster_place(tmp_path: Path) -> None:
    reg = _written(_one_page(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    text = page.read_text(encoding="utf-8")
    page.write_text(text.replace(_block(text, "peek"), "") + "\nTrailing why.\n",
                    encoding="utf-8")
    reference.write(reg)
    final = page.read_text(encoding="utf-8")
    assert reference.drift(reg) == []
    assert final.index(begin_marker("peek")) < final.index(begin_marker("poke")), final


def test_a_stray_block_goes_and_its_prose_joins_the_block_before_it(tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    stray = begin_marker("gone") + "\nold\n" + end_marker("gone")
    page.write_text(page.read_text(encoding="utf-8").replace(
        "# The Read tools\n", f"# The Read tools\n\n{stray}\n\nWhy gone, first.\n", 1)
        + f"\n{stray}\n\nWhy gone.\n", encoding="utf-8")
    reference.write(reg)
    final = page.read_text(encoding="utf-8")
    assert "gone -->" not in final and reference.drift(reg) == [], final
    assert final.index("Why gone, first.") < final.index(begin_marker("peek")) \
        < final.index("Why gone."), final


# ======================================================================== the examples


def _record(tool: str, verdict: str, reply: dict[str, Any], label: str = "c") -> dict[str, Any]:
    return {"section": "[A] fixture", "label": label, "verdict": verdict, "tool": tool,
            "args": {"addr": "0x10"}, "reply": reply}


def test_the_example_picked_is_the_first_ok_reply_of_an_ok_cell_else_the_first_refusal(
        tmp_path: Path) -> None:
    norm = Normaliser(tmp_path, Path.home(), {})
    records = [
        _record("peek", "FAIL", {"status": "ok", "value": 1}),
        _record("peek", "OK", {"status": "INVALID", "code": "bad_argument"}, "refused"),
        _record("peek", "OK", {"status": "ok", "value": 2}, "read"),
        _record("poke", "OK", {"exception": "boom"}, "raised"),
        _record("poke", "OK", {"status": "INVALID", "code": "not_stopped"}, "running"),
        _record("gone", "OK", {"status": "ok"}),
        {"tool": "poke", "verdict": "OK", "label": "late", "reply": {"status": "INVALID"}},
    ]
    picked = reference.examples_from(records, {"peek", "poke"}, norm)
    assert picked["peek"] == {"from": "[A] fixture: read", "call": {"addr": "0x10"},
                              "reply": {"status": "ok", "value": 2}}
    assert picked["poke"]["from"] == "[A] fixture: running" and "gone" not in picked
    alone = reference.examples_from(records[-1:], {"poke"}, norm)["poke"]
    assert alone["from"] == ": late" and alone["call"] == {}, alone
    old = {"tool": "poke", "verdict": "OK", "cell": "late", "reply": {"status": "INVALID"}}
    assert reference.examples_from([old], {"poke"}, norm)["poke"]["from"] == ": "


def test_an_example_keeps_the_shape_of_a_long_reply_and_spells_the_host_s_paths(
        tmp_path: Path) -> None:
    norm = Normaliser(tmp_path, Path.home(), {})
    reply = {"status": "ok", "rows": list(range(20)), "text": "x" * 1000,
             "path": str(tmp_path / "out.png"), "pid": 4242}
    shown = reference.examples_from([_record("peek", "OK", reply)], {"peek"}, norm)["peek"]
    rows = shown["reply"]["rows"]
    assert rows[:demo.ABRIDGED_ITEMS] == list(range(demo.ABRIDGED_ITEMS))
    assert rows[-1] == f"... {20 - demo.ABRIDGED_ITEMS} more", rows
    assert shown["reply"]["text"] == "x" * demo.ABRIDGED_CHARS + " ... (1000 characters)"
    assert shown["reply"]["path"] == f".{os.sep}out.png"
    assert shown["reply"]["pid"] == 4242, "only a demo hides by key; an example shows the run"


# ======================================================================== the command


def _main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setitem(sys.modules, "fixture_registry",
                        types.SimpleNamespace(REGISTRY=_registry(tmp_path), Path=Path))
    return reference.main(["fixture_registry:REGISTRY", *argv])


def test_the_command_writes_then_finds_no_drift_then_names_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _examples(tmp_path)
    assert _main(tmp_path, monkeypatch, "--write") == 0
    assert _main(tmp_path, monkeypatch) == 0
    page = tmp_path / "docs/reference/read.md"
    page.write_text(page.read_text(encoding="utf-8").replace("integer", "int"), encoding="utf-8")
    capsys.readouterr()
    assert _main(tmp_path, monkeypatch) == 1
    assert "`peek` in docs/reference/read.md" in capsys.readouterr().out


def test_the_command_builds_the_examples_from_a_transcript(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jsonl = tmp_path / "transcript.jsonl"
    jsonl.write_text("\n".join(json.dumps(_record(t, "OK", {"status": "ok"}))
                               for t in ("peek", "poke")) + "\n", encoding="utf-8")
    assert _main(tmp_path, monkeypatch, "--examples", str(jsonl), "--write") == 0
    held = json.loads((tmp_path / EXAMPLES).read_text(encoding="utf-8"))
    assert set(held) == {"peek", "poke"}


def test_a_transcript_naming_no_tool_of_the_server_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jsonl = tmp_path / "transcript.jsonl"
    jsonl.write_text(json.dumps(_record("gone", "OK", {"status": "ok"})) + "\n",
                     encoding="utf-8")
    assert _main(tmp_path, monkeypatch, "--examples", str(jsonl)) == 3
    assert not (tmp_path / EXAMPLES).exists()


@pytest.mark.parametrize("content", [None, "{not json\n"])
def test_a_transcript_that_cannot_be_read_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None) -> None:
    jsonl = tmp_path / "transcript.jsonl"
    if content is not None:
        jsonl.write_text(content, encoding="utf-8")
    assert _main(tmp_path, monkeypatch, "--examples", str(jsonl)) == 3


@pytest.mark.parametrize("content", ["{broken", "[1, 2]"])
def test_an_examples_file_that_is_not_an_object_by_tool_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str) -> None:
    (tmp_path / "docs/reference").mkdir(parents=True)
    (tmp_path / EXAMPLES).write_text(content, encoding="utf-8")
    assert _main(tmp_path, monkeypatch) == 3


@pytest.mark.parametrize("spec", ["fixture_registry", "fixture_registry:Path",
                                  "no_such_module:REGISTRY", "fixture_registry:NOPE",
                                  ":REGISTRY", ".relative:REGISTRY"])
def test_a_spec_that_names_no_registry_is_a_usage_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spec: str) -> None:
    _main(tmp_path, monkeypatch)  # the fixture module, importable
    with pytest.raises(SystemExit) as exit_:
        reference.main([spec])
    assert exit_.value.code == 2


_COMMAND_FIXTURE = '''
from pathlib import Path
from typing import Any
from mcp.server.mcpserver import MCPServer
from scry_core import demo, reference, reply_schema, roster
from scry_core.strict_arguments import strict_arguments

server = MCPServer("cli")


@server.tool()
def ping() -> dict[str, Any]:
    """Ping. Reply: nothing of its own."""
    return {"status": "ok"}


strict_arguments(server)
REGISTRY = reference.Registry(server=server, models={"ping": reply_schema.ReplyEnvelope},
                              roster=roster.Roster(families=(("Net", ("ping",)),), answering=()),
                              envelope=reply_schema.ReplyEnvelope, root=Path(__file__).parent)
'''


def test_the_command_run_as_a_module_takes_the_registry_a_server_built(tmp_path: Path) -> None:
    """`python -m` runs this module as `__main__`, a second copy whose `Registry` is not the one a
    server imports: the command must judge the spec with the copy the server used."""
    (tmp_path / "cli_registry.py").write_text(_COMMAND_FIXTURE, encoding="utf-8")
    done = subprocess.run([sys.executable, "-m", "scry_core.reference", "cli_registry:REGISTRY",
                           "--write"], cwd=tmp_path, capture_output=True, text=True,
                          check=False, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "docs/reference/net.md").is_file()


def test_an_example_leaves_out_the_session_block_reference_md_documents_once(
        tmp_path: Path) -> None:
    norm = Normaliser(tmp_path, Path.home(), {})
    reply = {"status": "ok", "value": 1, "session": {"alive": True, "altered": False}}
    shown = reference.examples_from([_record("peek", "OK", reply)], {"peek"}, norm)["peek"]
    assert shown["reply"] == {"status": "ok", "value": 1}, shown


def test_each_mark_spells_a_host_directory_as_the_caller_names_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scratch, bench = tmp_path / "s9.ABCDEF", tmp_path / "bench"
    jsonl = tmp_path / "transcript.jsonl"
    rec = _record("peek", "OK", {"status": "ok", "path": f"{scratch}/job/f7.wav",
                                 "gfx": f"{bench}/m68k/gfx.yaml"})
    jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    assert _main(tmp_path, monkeypatch, "--examples", str(jsonl), "--mark",
                 f"{scratch}=$TMPDIR", "--mark", f"{bench}=$SCRY_BENCH") in (0, 1)
    held = json.loads((tmp_path / EXAMPLES).read_text(encoding="utf-8"))
    assert held["peek"]["reply"]["path"] == "$TMPDIR/job/f7.wav", held
    assert held["peek"]["reply"]["gfx"] == "$SCRY_BENCH/m68k/gfx.yaml", held


def test_a_mark_without_its_spelling_is_a_usage_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as exit_:
        _main(tmp_path, monkeypatch, "--mark", "/tmp/x")
    assert exit_.value.code == 2


def test_a_scratch_spelled_two_ways_is_one_mark_whichever_comes_first(tmp_path: Path) -> None:
    norm = Normaliser(tmp_path, Path.home(), {},
                      marks={"/tmp/s9.X": "$TMPDIR", "/private/tmp/s9.X": "$TMPDIR"})
    assert norm.text("/private/tmp/s9.X/job/a.conf and /tmp/s9.X/b") \
        == "$TMPDIR/job/a.conf and $TMPDIR/b"


def test_an_example_spells_the_repository_as_an_absolute_placeholder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jsonl = tmp_path / "transcript.jsonl"
    rec = _record("peek", "OK", {"status": "ok", "conf": f"{tmp_path}/tests/guest/a.conf"})
    jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    _main(tmp_path, monkeypatch, "--examples", str(jsonl))
    held = json.loads((tmp_path / EXAMPLES).read_text(encoding="utf-8"))
    assert held["peek"]["reply"]["conf"] == f"/path/to/{tmp_path.name}/tests/guest/a.conf", held


def test_a_description_s_indented_line_is_text_and_never_a_code_block(tmp_path: Path) -> None:
    server = MCPServer("indent")

    @server.tool()
    def tidy() -> dict[str, Any]:
        """Tidy.

            Reads files only: it needs no machine.
        Reply: `written`."""
        return {"status": "ok"}

    strict_arguments(server)
    block = reference.tool_block(registered(server)[0], PokeReply, FixtureEnvelope, None)
    assert "\nReads files only: it needs no machine." in block, block


def test_a_tool_s_heading_is_one_level_under_its_page_s_and_its_caption_is_plain(
        tmp_path: Path) -> None:
    _written(_registry(tmp_path))
    text = _read(tmp_path)
    assert "\n## `peek`\n" in text and "### `peek`" not in text, text
    assert "Example, from a live run:" in text and "[A] fixture" not in text, text


def test_a_union_names_each_type_once_and_a_double_backtick_span_is_left_alone(
        tmp_path: Path) -> None:
    server = MCPServer("dedupe")

    @server.tool()
    def mix(bases: dict[str, str] | dict[str, int] | None = None) -> dict[str, Any]:
        """Mix: the cause is ``registerpoint '<ref>'`` as typed. Reply: `written`."""
        return {"status": "ok"}

    strict_arguments(server)
    block = reference.tool_block(registered(server)[0], PokeReply, FixtureEnvelope, None)
    assert "| `bases` | object or null | `null` |" in block, block
    assert "``registerpoint '<ref>'``" in block, block


def test_a_page_s_title_never_shares_its_anchor_with_a_tool(tmp_path: Path) -> None:
    reg = _registry(tmp_path, (("Peek", ("peek",)), ("Write memory", ("poke",))))
    _written(reg)
    assert _read(tmp_path, "peek").startswith("# The Peek tools\n")


def test_a_fence_and_a_nested_list_keep_their_shape_and_spans_stay_spans() -> None:
    server = MCPServer("fence")

    @server.tool()
    def fenced_tool() -> dict[str, Any]:
        """Use:

        ```
        x  <y>
            indented
        ```
        A <ref> and `y<z` and ``a`b <c>``.

        - outer
          - inner
        Reply: `written`."""
        return {"status": "ok"}

    strict_arguments(server)
    block = reference.tool_block(registered(server)[0], PokeReply, FixtureEnvelope, None)
    assert "```\nx  <y>\n    indented\n```" in block, block
    assert "A &lt;ref> and `y<z` and ``a`b <c>``." in block, block
    assert "- outer\n  - inner" in block, block


def test_a_page_titled_the_old_way_is_drift_and_a_rewrite_retitles_it(tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    page = tmp_path / "docs/reference/read.md"
    page.write_text(page.read_text(encoding="utf-8").replace("# The Read tools", "# Read", 1),
                    encoding="utf-8")
    assert "docs/reference/read.md: titled '# Read', not '# The Read tools'" in reference.drift(reg)
    reference.write(reg)
    assert reference.drift(reg) == []


@pytest.mark.parametrize("argv", [["--mark", "=x"], ["--mark", "x="],
                                  ["--mark", "/tmp/x=$T"]])
def test_a_mark_that_cannot_be_used_is_a_usage_error(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        _main(tmp_path, monkeypatch, *argv)
    assert exit_.value.code == 2, "a mark is refused alone, or with no examples to spell"


def test_a_mark_whose_path_holds_an_equals_sign_splits_at_the_last_one(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jsonl = tmp_path / "transcript.jsonl"
    rec = _record("peek", "OK", {"status": "ok", "path": "/tmp/a=b/f"})
    jsonl.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    _main(tmp_path, monkeypatch, "--examples", str(jsonl), "--mark", "/tmp/a=b=$T")
    held = json.loads((tmp_path / EXAMPLES).read_text(encoding="utf-8"))
    assert held["peek"]["reply"]["path"] == "$T/f", held


def test_reference_md_keeps_the_title_its_server_gave_it(tmp_path: Path) -> None:
    reg = _written(_registry(tmp_path))
    ref = tmp_path / "REFERENCE.md"
    ref.write_text(ref.read_text(encoding="utf-8").replace("# Reference", "# scry-x: reference",
                                                           1), encoding="utf-8")
    assert reference.drift(reg) == []
    reference.write(reg)
    assert ref.read_text(encoding="utf-8").startswith("# scry-x: reference\n")


@pytest.mark.parametrize(("example", "named"), [
    ({"call": {"addr": "0x10"}, "reply": {"status": "ok", "gone": 1}},
     "`peek`'s example replies `gone`, which its model does not name"),
    ({"call": {"addr": "0x10", "mode": "nibble"}, "reply": {"status": "ok"}},
     "`peek`'s example call is one the tool refuses"),
])
def test_an_example_the_code_no_longer_answers_is_drift(
        tmp_path: Path, example: dict[str, Any], named: str) -> None:
    reg = _written(_registry(tmp_path))
    held = json.loads((tmp_path / EXAMPLES).read_text(encoding="utf-8"))
    held["peek"] = {"from": "[A] fixture: a cell", **example}
    (tmp_path / EXAMPLES).write_text(json.dumps(held), encoding="utf-8")
    assert any(f.startswith(f"{EXAMPLES}: {named}") for f in reference.drift(reg)), \
        reference.drift(reg)


def test_an_example_call_is_kept_whole_as_a_reader_would_type_it(tmp_path: Path) -> None:
    norm = Normaliser(tmp_path, Path.home(), {})
    rec = {**_record("peek", "OK", {"status": "ok", "rows": list(range(9))}),
           "args": {"keys": list(range(9))}}
    shown = reference.examples_from([rec], {"peek"}, norm)["peek"]
    assert shown["call"] == {"keys": list(range(9))}, shown
    assert shown["reply"]["rows"][-1] == f"... {9 - demo.ABRIDGED_ITEMS} more", shown


def test_an_examples_entry_that_is_not_an_object_is_invalid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "docs/reference").mkdir(parents=True)
    (tmp_path / EXAMPLES).write_text('{"peek": 3}', encoding="utf-8")
    assert _main(tmp_path, monkeypatch) == 3


def test_a_registry_module_that_fails_to_import_is_invalid_not_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    class Boom:
        def __getattr__(self, name: str) -> Any:
            raise RuntimeError("the server could not be built")

    monkeypatch.setitem(sys.modules, "boom_registry", Boom())
    assert reference.main(["boom_registry:REGISTRY"]) == 3
    assert "INVALID" in capsys.readouterr().out


def test_a_failure_while_comparing_is_invalid_not_drift(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    def broken(reg: reference.Registry) -> list[str]:
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "a page that is not UTF-8")

    monkeypatch.setattr(reference, "drift", broken)
    assert _main(tmp_path, monkeypatch) == 3
    assert "INVALID: UnicodeDecodeError" in capsys.readouterr().out


def test_a_module_that_raises_while_it_is_built_is_invalid_not_usage(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "unbuilt_registry.py").write_text('raise ValueError("a tool has no reply model")\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    assert reference.main(["unbuilt_registry:REGISTRY"]) == 3
    assert "a tool has no reply model" in capsys.readouterr().out


def test_a_module_whose_own_import_fails_is_invalid_not_usage(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "half_registry.py").write_text("import no_such_dependency_of_it\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert reference.main(["half_registry:REGISTRY"]) == 3
    assert "no_such_dependency_of_it" in capsys.readouterr().out
