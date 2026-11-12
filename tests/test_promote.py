"""`scry_core.promote`: the draft a session keeps and the approved promotion that writes it."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from scry_core import (
    file_names,
    fresh,
    project_store,
    promote,
    promote_diff,
    reply_schema,
    screen_map,
    scry_readme,
)
from scry_core.promote import Drafts
from scry_core.reply_contract import Invalid


def start_doc(**values: Any) -> dict[str, Any]:
    return {"format": "scry-start/1", **values}


def map_doc(*screens: str, application: str = "lineup") -> dict[str, Any]:
    return {"format": "scry-screen-map/1", "application": application, "mode": "verified",
            "screens": [{"name": s, "kind": "pixel", "size": [320, 200],
                         "match": [{"crop": [0, 0, 8, 8], "signature": "0123456789abcdef"}],
                         "controls": []} for s in screens]}


def perform_doc(checks: int = 1) -> dict[str, Any]:
    return {"version": 3, "server": "mame", "entry": "lineup",
            "start": {"system": "lineup", "rompath": "/roms", "boot_seconds": 8.0},
            "steps": [{"op": "read_memory", "ref": "0x10", "length": 2,
                       **({"recorded": {"data": "abcd"}} if checks else {})}],
            "needs": {"states": [], "declarations": {}}}


def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def drafted(kind: str, name: str, document: dict[str, Any], **keep: Any) -> Drafts:
    drafts = Drafts()
    drafts.keep(kind, name, document, **keep)
    return drafts


def review(drafts: Drafts, root: Path, **values: Any) -> dict[str, Any]:
    return promote.promote(drafts, dry_run=True, starting=[root], root=str(root), **values)


def refused(drafts: Drafts, root: Path, **values: Any) -> str:
    """The reason a review gives for the one entry it cannot write."""
    reply = review(drafts, root, **values)
    assert reply["candidates"] == [] and len(reply["unwritable"]) == 1
    return str(reply["unwritable"][0]["reason"])


def write(drafts: Drafts, root: Path, entries: list[str], **values: Any) -> dict[str, Any]:
    return promote.promote(drafts, entries=entries, starting=[root], root=str(root), **values)


def test_a_start_without_its_program_proposes_nothing() -> None:
    drafts = drafted("start", "lineup", start_doc(rompath="/roms"), needs=("system",))
    assert drafts.entries() == []
    assert len(drafts) == 0


def test_a_start_with_its_program_is_kept() -> None:
    drafts = drafted("start", "lineup", start_doc(system="lineup"), needs=("system",))
    assert drafts.entries() == ["start/lineup"]


def test_a_map_with_a_verified_screen_is_kept_and_an_empty_one_is_not() -> None:
    assert drafted("maps", "lineup", map_doc("play")).entries() == ["maps/lineup"]
    assert drafted("maps", "lineup", map_doc()).entries() == []


def test_a_perform_with_a_check_is_kept_and_one_without_is_not() -> None:
    assert drafted("perform", "dos", perform_doc()).entries() == ["perform/dos"]
    assert drafted("perform", "dos", perform_doc(checks=0)).entries() == []


def test_the_identity_is_the_pair_kind_and_name() -> None:
    drafts = drafted("start", "lineup", start_doc(system="lineup"), needs=("system",))
    drafts.keep("start", "lineup", start_doc(system="speedf"), needs=("system",))
    assert drafts.entries() == ["start/lineup"]
    assert drafts.kept["start", "lineup"].document["system"] == "speedf"


def test_two_kinds_may_share_a_name() -> None:
    drafts = Drafts()
    drafts.keep("start", "lineup", start_doc(system="lineup"), needs=("system",))
    drafts.keep("maps", "lineup", map_doc("play"))
    assert drafts.entries() == ["maps/lineup", "start/lineup"]


def test_a_loaded_entry_names_the_candidate_the_session_learned_from() -> None:
    drafts = Drafts()
    drafts.loaded_entry("start", "dos")
    assert drafts.loaded_name("start") == "dos"
    assert drafts.loaded_name("maps") == ""


def test_a_name_a_kind_cannot_take_is_refused() -> None:
    drafts = Drafts()
    with pytest.raises(Invalid, match="not an entry name"):
        drafts.keep("start", "a/b", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="not a kind"):
        drafts.keep("knowledge", "x", start_doc())


def test_reviewing_an_empty_draft_names_how_a_candidate_is_kept(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="needs_call|nothing is kept"):
        review(Drafts(), repo(tmp_path))


def test_a_name_the_store_already_holds_is_an_update_with_its_diff(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    (root / ".scry" / "start" / "lineup.json").write_text(json.dumps(
        start_doc(system="lineup", rompath="/roms", boot_seconds=8.0)))
    drafts = drafted("start", "lineup",
                     start_doc(system="lineup", rompath="/roms", boot_seconds=30.0),
                     needs=("system",))
    entry = review(drafts, root)["candidates"][0]
    assert entry["change"] == "update"
    assert entry["diff"]["added"] == [] and entry["diff"]["removed"] == []
    assert entry["diff"]["changed"] == [{"path": "boot_seconds", "was": 8.0, "now": 30.0}]


def test_a_name_the_store_does_not_hold_is_new(tmp_path: Path) -> None:
    entry = review(drafted("start", "lineup", start_doc(system="lineup"), needs=("system",)),
                   repo(tmp_path))["candidates"][0]
    assert entry["change"] == "new" and "diff" not in entry
    assert entry["file"] == ".scry/start/lineup.json"


def test_the_diff_names_what_a_screen_change_adds_removes_and_changes(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "maps").mkdir(parents=True)
    (root / ".scry" / "maps" / "lineup-screen-map.json").write_text(json.dumps(
        map_doc("play", "over")))
    learned = map_doc("play", "hiscores")
    learned["screens"][0]["size"] = [320, 240]
    entry = review(drafted("maps", "lineup", learned), root)["candidates"][0]
    assert entry["diff"]["added"] == ["screens.hiscores"]
    assert entry["diff"]["removed"] == ["screens.over"]
    assert [c["path"] for c in entry["diff"]["changed"]] == ["screens.play"]
    assert entry["diff"]["changed"][0]["was"]["size"] == [320, 200]
    assert entry["diff"]["changed"][0]["now"]["size"] == [320, 240]


def test_the_diff_walks_a_step_and_a_list_of_names(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "perform").mkdir(parents=True)
    (root / ".scry" / "perform" / "dos.json").write_text(json.dumps(perform_doc()))
    learned = perform_doc()
    learned["steps"][0]["length"] = 4
    learned["needs"]["states"] = ["first"]
    entry = review(drafted("perform", "dos", learned), root)["candidates"][0]
    assert [c["path"] for c in entry["diff"]["changed"]] == ["needs.states", "steps[0].length"]


def test_dry_run_writes_nothing_and_creates_no_store(tmp_path: Path) -> None:
    root = repo(tmp_path)
    review(drafted("start", "lineup", start_doc(system="lineup"), needs=("system",)), root)
    assert not (root / ".scry").exists()


def test_an_approved_promotion_creates_the_store_and_its_kind_directory(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    reply = write(drafted("start", "lineup", start_doc(system="lineup"), needs=("system",)),
                  root, ["start/lineup"])
    target = root / ".scry" / "start" / "lineup.json"
    assert reply["written"][0]["change"] == "new"
    assert json.loads(target.read_text()) == start_doc(system="lineup")


def _about(root: Path) -> dict[str, Any]:
    return json.loads((root / ".scry" / "about.json").read_text())  # type: ignore[no-any-return]


def _lineup() -> Drafts:
    return drafted("start", "lineup", start_doc(system="lineup"), needs=("system",))


def test_an_approved_promotion_into_a_bare_repository_sets_up_the_whole_store(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    reply = write(_lineup(), root, ["start/lineup"], server="dosbox-x")
    assert reply["created"] == [".scry/", ".scry/about.json", ".scry/README.md"]
    assert _about(root) == {
        "format": "scry-about/1", "server": "dosbox-x",
        "purpose": "What this repository declares for SCRY's `dosbox-x` server.",
        "files": {"start/lineup.json": "boots `lineup`."}}
    page = (root / ".scry" / "README.md").read_bytes()
    assert page == scry_readme.render(root).encode()
    assert scry_readme.main(["--check", str(root)]) == 0


def test_a_review_lists_what_an_approval_would_create_and_writes_nothing(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    reply = review(_lineup(), root, server="mame")
    assert reply["would_create"] == [".scry/", ".scry/about.json", ".scry/README.md"]
    assert not (root / ".scry").exists()
    assert promote.promote_line({}, reply).endswith(
        "; would create .scry/, .scry/about.json, .scry/README.md")


def test_the_approved_line_says_what_it_created(tmp_path: Path) -> None:
    reply = write(_lineup(), repo(tmp_path), ["start/lineup"], server="mame")
    assert promote.promote_line({}, reply).endswith(
        "0 entries still kept; created .scry/, .scry/about.json, .scry/README.md")


def test_a_promotion_with_no_server_writes_the_entry_and_nothing_else(tmp_path: Path) -> None:
    root = repo(tmp_path)
    assert "would_create" not in review(_lineup(), root)
    reply = write(_lineup(), root, ["start/lineup"])
    assert "created" not in reply
    assert sorted(p.name for p in (root / ".scry").rglob("*")) == ["lineup.json", "start"]


def test_a_server_the_readme_does_not_know_is_refused_before_anything_is_written(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    with pytest.raises(Invalid, match="bochs"):
        write(_lineup(), root, ["start/lineup"], server="bochs")
    assert not (root / ".scry").exists()


def test_a_later_promotion_keeps_the_lines_written_by_hand_and_names_only_the_new_entry(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"], server="mame")
    about = _about(root)
    about["files"]["start/lineup.json"] = "boots the arcade board the way the bench does."
    about["server"] = "dosbox-x"
    (root / ".scry" / "about.json").write_text(json.dumps(about))
    reply = write(drafted("maps", "lineup", map_doc("play")), root, ["maps/lineup"],
                  server="mame")
    assert "created" not in reply
    assert _about(root)["files"] == {
        "start/lineup.json": "boots the arcade board the way the bench does.",
        "maps/lineup-screen-map.json": "the screens of lineup."}
    assert _about(root)["server"] == "dosbox-x"
    page = (root / ".scry" / "README.md").read_text()
    assert "boots the arcade board the way the bench does." in page
    assert page == scry_readme.render(root)


def test_a_manifest_that_already_covers_every_entry_is_left_as_it_is(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"], server="mame")
    handwritten = json.dumps(_about(root), indent=4) + "\n"
    (root / ".scry" / "about.json").write_text(handwritten)
    changed = drafted("start", "lineup", start_doc(system="lineup", boot_seconds=3.0),
                      needs=("system",))
    write(changed, root, ["start/lineup"], server="mame")
    assert (root / ".scry" / "about.json").read_text() == handwritten


def test_a_store_with_no_manifest_gets_a_line_for_every_file_it_holds(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    (root / ".scry" / "start" / "old.json").write_text(json.dumps(start_doc(program="OLD.EXE")))
    (root / ".scry" / "start" / "bad.json").write_text("not json")
    reply = write(_lineup(), root, ["start/lineup"], server="mame")
    assert reply["created"] == [".scry/about.json", ".scry/README.md"]
    assert _about(root)["files"] == {
        "start/bad.json": "a run recipe.", "start/lineup.json": "boots `lineup`.",
        "start/old.json": "boots `OLD.EXE`."}


def test_a_renamed_entry_gets_its_line_under_the_name_it_is_written_as(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"], names={"start/lineup": "dos"}, server="mame")
    assert list(_about(root)["files"]) == ["start/dos.json"]


@pytest.mark.parametrize("make, message", [
    (lambda about: about.write_text("{not json"), "not JSON"),
    (lambda about: about.write_text(json.dumps({"format": "scry-about/1", "purpose": "p",
                                                "server": "mame",
                                                "files": {"start/ghost.json": "gone."}})),
     r"start/ghost\.json"),
    (lambda about: about.mkdir(), "about.json is not a file"),
    (lambda about: about.write_text(json.dumps({"format": "scry-about/1", "purpose": "p",
                                                "server": "mame", "files": ["start/x.json"]})),
     "files must map"),
])
def test_a_manifest_the_page_cannot_be_rendered_from_refuses_the_whole_promotion(
        tmp_path: Path, make: Any, message: str) -> None:
    root = repo(tmp_path)
    (root / ".scry").mkdir()
    make(root / ".scry" / "about.json")
    with pytest.raises(Invalid, match=message):
        write(_lineup(), root, ["start/lineup"], server="mame")
    assert not (root / ".scry" / "start").exists()
    with pytest.raises(Invalid, match=message):
        review(_lineup(), root, server="mame")


def test_a_page_that_is_a_directory_refuses_the_promotion_before_the_entry_is_written(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "README.md").mkdir(parents=True)
    with pytest.raises(Invalid, match="README.md is not a file"):
        write(_lineup(), root, ["start/lineup"], server="mame")
    assert not (root / ".scry" / "start").exists()


def test_a_review_with_nothing_to_change_has_nothing_to_create(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"], server="mame")
    again = review(_lineup(), root, server="mame")
    assert again["candidates"] == [] and "would_create" not in again


def test_the_store_s_total_with_its_setup_is_the_same_before_and_after(tmp_path: Path) -> None:
    root = repo(tmp_path)
    before = review(_lineup(), root, server="mame")["store_bytes"]
    after = write(_lineup(), root, ["start/lineup"], server="mame")["store_bytes"]
    assert before == after > len(scry_readme.render(root))


def test_the_setup_counts_toward_the_store_s_cap(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain, set_up = tmp_path / "plain", tmp_path / "set_up"
    plain.mkdir()
    set_up.mkdir()
    monkeypatch.setattr(project_store, "STORE_BYTES_MAX",
                        review(_lineup(), plain)["total_bytes"] + 10)
    assert write(_lineup(), plain, ["start/lineup"])["written"]
    with pytest.raises(Invalid, match="past the"):
        write(_lineup(), set_up, ["start/lineup"], server="mame")


def test_a_setup_that_fails_to_land_says_what_was_written_before_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    real = fresh.replace

    def refuse_the_manifest(path: Path, data: bytes, what: str, *rest: Any) -> None:
        if path.name == "about.json":
            raise Invalid("host_failed", "disk full")
        real(path, data, what, *rest)

    monkeypatch.setattr(fresh, "replace", refuse_the_manifest)
    drafts = _lineup()
    with pytest.raises(Invalid, match=r"about\.json could not be written.*before it: start/lineup"):
        write(drafts, root, ["start/lineup"], server="mame")
    assert drafts.entries() == []


def test_a_server_the_readme_does_not_know_is_refused_whatever_the_store_holds(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"], server="mame")
    with pytest.raises(Invalid, match="bochs"):
        write(drafted("maps", "lineup", map_doc("play")), root, ["maps/lineup"], server="bochs")
    assert not (root / ".scry" / "maps").exists()


def test_a_review_of_unchanged_entries_still_names_the_setup_an_approval_would_create(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(_lineup(), root, ["start/lineup"])
    again = review(_lineup(), root, server="mame")
    assert again["candidates"] == []
    assert again["would_create"] == [".scry/about.json", ".scry/README.md"]
    assert write(_lineup(), root, ["start/lineup"], server="mame")["created"] == \
        again["would_create"]


def test_only_the_entries_chosen_are_written_and_the_rest_stay_kept(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = Drafts()
    drafts.keep("start", "lineup", start_doc(system="lineup"), needs=("system",))
    drafts.keep("maps", "lineup", map_doc("play"))
    reply = write(drafts, root, ["maps/lineup"])
    assert [w["entry"] for w in reply["written"]] == ["maps/lineup"]
    assert (root / ".scry" / "maps" / "lineup-screen-map.json").is_file()
    assert not (root / ".scry" / "start").exists()
    assert reply["draft"] == ["start/lineup"]


def test_an_entry_the_draft_does_not_hold_is_refused_naming_the_draft(
        tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="maps/lineup"):
        write(drafted("start", "lineup", start_doc(system="lineup"), needs=("system",)),
              repo(tmp_path), ["maps/lineup"])


def test_a_promotion_names_one_gesture(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "lineup", start_doc(system="lineup"), needs=("system",))
    with pytest.raises(Invalid, match="dry_run"):
        promote.promote(drafts, dry_run=True, entries=["start/lineup"],
                        starting=[root], root=str(root))
    with pytest.raises(Invalid, match="entries"):
        promote.promote(drafts, starting=[root], root=str(root))


def test_an_entry_can_be_renamed_as_it_is_written(tmp_path: Path) -> None:
    root = repo(tmp_path)
    reply = write(drafted("start", "v30", start_doc(system="lineup"), needs=("system",)),
                  root, ["start/v30"], names={"start/v30": "lineup"})
    assert reply["written"][0]["name"] == "lineup"
    assert (root / ".scry" / "start" / "lineup.json").is_file()


def test_an_entry_is_kept_written_and_approved_under_one_spelling_of_its_name(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "M68k_Dual", start_doc(system="m68k_dual"), needs=("system",))
    assert drafts.entries() == ["start/m68k-dual"]
    reply = write(drafts, root, ["start/M68K dual"], names={"start/M68K dual": "Line_Up"})
    assert reply["written"][0]["name"] == "line-up"
    assert reply["written"][0]["file"] == ".scry/start/line-up.json"
    assert [p.name for p in (root / ".scry" / "start").iterdir()] == ["line-up.json"]
    assert project_store.locate([root], "Line Up") == root / ".scry" / "start" / "line-up.json"
    maps = drafted("maps", "Line_Up", map_doc("title", application="line-up"))
    written = write(maps, root, ["maps/line-up"])["written"][0]
    assert written["file"] == ".scry/maps/line-up-screen-map.json"
    assert file_names.outside(root / ".scry") == []


def test_without_a_store_or_a_root_the_promotion_names_root(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="root"):
        promote.promote(drafted("start", "x", start_doc(system="x"), needs=("system",)),
                        dry_run=True, starting=[repo(tmp_path)])


def test_a_root_that_names_the_store_itself_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry").mkdir()
    with pytest.raises(Invalid, match="root"):
        review(drafted("start", "x", start_doc(system="x"), needs=("system",)),
               root / ".scry")


def test_a_store_above_a_starting_directory_is_found(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    below = root / "guest"
    below.mkdir()
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    assert promote.promote(drafts, dry_run=True, starting=[below])["store"] == str(
        root / ".scry")


def test_a_path_under_the_root_is_written_against_it(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=str(root / "roms")),
                     needs=("system",), path_keys=("rompath",))
    document = review(drafts, root)["candidates"][0]
    written = write(drafts, root, ["start/x"])["written"][0]
    assert document["bytes"] > 0
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == \
        "${root}/roms"
    assert written["bytes"] == document["bytes"]


def test_a_path_under_the_home_is_written_against_it(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=str(Path.home() / "roms")),
                     needs=("system",), path_keys=("rompath",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == \
        "${home}/roms"


def test_a_path_under_the_state_or_a_variable_is_written_against_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    monkeypatch.setenv("SCRY_PROMOTE_BENCH", str(tmp_path / "bench"))
    drafts = drafted("start", "x", start_doc(system="x",
                                             rompath=str(tmp_path / "run"),
                                             reference_rom=str(tmp_path / "bench" / "r.bin")),
                     needs=("system",), path_keys=("rompath", "reference_rom"))
    write(drafts, root, ["start/x"], state=str(tmp_path / "run"))
    document = json.loads((root / ".scry" / "start" / "x.json").read_text())
    assert document["rompath"] == "${state}"
    assert document["reference_rom"] == "${env:SCRY_PROMOTE_BENCH}/r.bin"


def test_a_path_of_this_machine_is_listed_apart_and_refused_when_approved(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = Drafts()
    drafts.keep("start", "lost", start_doc(system="x", rompath="/opt/somewhere/roms"),
                needs=("system",), path_keys=("rompath",))
    drafts.keep("start", "good", start_doc(system="y", rompath=f"{root}/roms"),
                needs=("system",), path_keys=("rompath",))
    reply = review(drafts, root, environ={})
    assert [item["entry"] for item in reply["candidates"]] == ["start/good"]
    assert reply["total_bytes"] == reply["candidates"][0]["bytes"]
    assert [item["entry"] for item in reply["unwritable"]] == ["start/lost"]
    assert "rompath" in reply["unwritable"][0]["reason"]
    assert "unwritable" not in review(
        drafted("start", "y", start_doc(system="y"), needs=("system",)), root)
    with pytest.raises(Invalid, match="rompath"):
        write(drafts, root, ["start/lost"], environ={})
    assert write(drafts, root, ["start/good"], environ={})["draft"] == ["start/lost"]


def test_a_review_of_nothing_writable_names_each_entry_and_its_line_says_so(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "lost", start_doc(system="x", rompath="/opt/somewhere/roms"),
                     needs=("system",), path_keys=("rompath",))
    reply = review(drafts, root, environ={})
    assert reply["candidates"] == [] and reply["total_bytes"] == 0
    assert promote.promote_line({}, reply).endswith("1 entry cannot be written")


def test_a_list_of_paths_is_each_written(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x",
                                             rompath=f"{root}/a;{root}/b"),
                     needs=("system",), path_keys=("rompath",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == \
        "${root}/a;${root}/b"


def test_a_perform_document_s_paths_are_written_against_the_root(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("perform", "dos", perform_doc(), path_keys=("rompath",))
    drafts.kept["perform", "dos"].document["start"]["rompath"] = f"{root}/roms"
    write(drafts, root, ["perform/dos"])
    written = json.loads((root / ".scry" / "perform" / "dos.json").read_text())
    assert written["start"]["rompath"] == "${root}/roms"


def test_a_profile_past_its_cap_is_refused(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x", view="v" * (64 * 1024)),
                     needs=("system",))
    assert re.search("start/x", refused(drafts, repo(tmp_path)))


def test_a_kind_directory_past_its_entries_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    store = root / ".scry" / "start"
    store.mkdir(parents=True)
    for n in range(project_store.ENTRIES_MAX):
        (store / f"p{n}.json").write_text("{}")
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="start/x"):
        review(drafts, root)


def test_a_store_past_its_bytes_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    store = root / ".scry" / "maps"
    store.mkdir(parents=True)
    (store / "big-screen-map.json").write_text("x" * project_store.STORE_BYTES_MAX)
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="start/x"):
        review(drafts, root)


def test_an_existing_entry_the_reader_cannot_parse_is_never_overwritten(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    (root / ".scry" / "start" / "x.json").write_text("not json")
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    assert re.search("x.json", refused(drafts, root))


def test_the_same_candidate_is_written_as_the_same_bytes(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", boot_seconds=30.0), needs=("system",))
    write(drafts, root, ["start/x"])
    first = (root / ".scry" / "start" / "x.json").read_bytes()
    write(drafted("start", "x", start_doc(system="x", boot_seconds=30.0), needs=("system",)),
          root, ["start/x"])
    assert (root / ".scry" / "start" / "x.json").read_bytes() == first


def test_the_store_s_total_is_reported_before_and_after(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    before = review(drafts, root)["store_bytes"]
    after = write(drafts, root, ["start/x"])["store_bytes"]
    assert before > 0 and after == before


def test_what_is_left_unkept_is_named_for_close() -> None:
    drafts = Drafts()
    drafts.keep("start", "lineup", start_doc(system="lineup"), needs=("system",))
    drafts.keep("maps", "lineup", map_doc("play"))
    drafts.loaded_entry("perform", "dos")
    assert promote.unkept(drafts, lambda: []) == ["maps/lineup", "start/lineup"]


def test_a_map_document_is_written_the_way_its_own_save_writes_it(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("maps", "lineup", map_doc("play"))
    data = write(drafts, root, ["maps/lineup"])["written"][0]
    text = (root / ".scry" / "maps" / "lineup-screen-map.json").read_text()
    assert text == json.dumps(map_doc("play"), indent=1) + "\n"
    assert data["bytes"] == len(text.encode())


def test_a_kind_that_is_not_read_names_nothing_and_an_empty_name_is_no_identity() -> None:
    drafts = Drafts()
    drafts.loaded_entry("knowledge", "x")
    drafts.loaded_entry("start", "")
    assert drafts.loaded == {}


def test_a_document_that_is_not_an_object_is_refused() -> None:
    drafts = Drafts()
    with pytest.raises(Invalid, match="not a document"):
        drafts.keep("maps", "lineup", ["play"])  # type: ignore[arg-type]


def test_a_root_that_is_relative_or_a_file_is_refused(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="absolute"):
        promote.promote(drafts, dry_run=True, starting=[tmp_path], root="repo")
    file = tmp_path / "repo"
    file.write_text("")
    with pytest.raises(Invalid, match="not a directory"):
        promote.promote(drafts, dry_run=True, starting=[tmp_path], root=str(file))


def test_an_entry_named_twice_is_refused(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="twice"):
        write(drafts, repo(tmp_path), ["start/x", "start/x"])


def test_an_entry_that_is_no_pair_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="<kind>/<name>"):
        write(drafts, root, ["x"])
    with pytest.raises(Invalid, match="<kind>/<name>"):
        write(drafts, root, ["knowledge/x"])
    with pytest.raises(Invalid, match="not an entry name"):
        write(drafts, root, ["start/bad.json"])


def test_a_perform_document_with_no_start_block_is_written_as_it_is(tmp_path: Path) -> None:
    root = repo(tmp_path)
    document = perform_doc()
    del document["start"]
    write(drafted("perform", "dos", document, path_keys=("rompath",)), root, ["perform/dos"])
    assert json.loads((root / ".scry" / "perform" / "dos.json").read_text())["steps"]


def test_a_long_diff_says_how_many_changes_it_shows(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    before = start_doc(system="x", **{f"k{n}": n for n in range(25)})
    after = start_doc(system="x", **{f"k{n}": n + 1 for n in range(25)})
    (root / ".scry" / "start" / "x.json").write_text(json.dumps(before))
    entry = review(drafted("start", "x", after, needs=("system",)), root)["candidates"][0]
    assert len(entry["diff"]["changed"]) == promote_diff.CHANGES_SHOWN
    assert entry["diff"]["changed_total"] == 25


def test_the_diff_names_a_key_added_and_leaves_an_equal_list_of_names_alone(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "perform").mkdir(parents=True)
    before = perform_doc()
    before["needs"]["states"] = ["first"]
    (root / ".scry" / "perform" / "dos.json").write_text(json.dumps(before))
    after = perform_doc()
    after["needs"]["states"] = ["first"]
    after["steps"].append({"op": "run_for", "frames": 2})
    entry = review(drafted("perform", "dos", after), root)["candidates"][0]
    assert entry["diff"]["added"] == ["steps[1]"]
    assert entry["diff"]["changed"] == []
    (root / ".scry" / "start").mkdir(parents=True)
    (root / ".scry" / "start" / "lineup.json").write_text(
        json.dumps(start_doc(system="lineup")))
    added = review(drafted("start", "lineup", start_doc(system="lineup", boot_seconds=30.0),
                           needs=("system",)), root)["candidates"][0]
    assert added["diff"]["added"] == ["boot_seconds"]


def test_a_named_item_that_holds_is_no_change(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "maps").mkdir(parents=True)
    (root / ".scry" / "maps" / "lineup-screen-map.json").write_text(json.dumps(
        map_doc("play")))
    entry = review(drafted("maps", "lineup", map_doc("play", "hiscores")), root)["candidates"][0]
    assert entry["diff"]["added"] == ["screens.hiscores"]
    assert entry["diff"]["changed"] == []


def test_a_path_key_may_hold_a_table_and_a_list(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(
        system="x", symbols={"maincpu": f"{root}/symbols.yaml"},
        guest_files=[f"{root}/a.txt"]),
        needs=("system",), path_keys=("symbols", "guest_files", "boot_lua"))
    write(drafts, root, ["start/x"])
    document = json.loads((root / ".scry" / "start" / "x.json").read_text())
    assert document["symbols"] == {"maincpu": "${root}/symbols.yaml"}
    assert document["guest_files"] == ["${root}/a.txt"]


def test_a_path_key_that_is_no_path_is_refused_by_name(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x", boot_seconds=8),
                     needs=("system",), path_keys=("boot_seconds",))
    assert re.search("boot_seconds", refused(drafts, repo(tmp_path)))


def test_a_tilde_and_a_relative_path_are_written_as_they_resolve(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", inipath="~/ini",
                                             cfg="cfg/game.cfg"),
                     needs=("system",), path_keys=("inipath", "cfg"))
    write(drafts, root, ["start/x"])
    document = json.loads((root / ".scry" / "start" / "x.json").read_text())
    assert document["inipath"] == "${home}/ini"
    assert document["cfg"] == "${root}/cfg/game.cfg"


def test_an_empty_value_in_a_path_key_is_left_alone(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", cfg=""), needs=("system",),
                     path_keys=("cfg",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["cfg"] == ""


def test_the_root_itself_is_written_as_the_placeholder_alone(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=str(root)), needs=("system",),
                     path_keys=("rompath",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == "${root}"


def test_with_no_starting_point_the_refusal_says_where_it_looked() -> None:
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="this process's directory"):
        promote.promote(drafts, dry_run=True, starting=[])


def test_keep_says_whether_the_candidate_entered() -> None:
    drafts = Drafts()
    assert drafts.keep("start", "x", start_doc(system="x"), needs=("system",)) is True
    assert drafts.keep("start", "y", start_doc(rompath="/r"), needs=("system",)) is False


def test_forgetting_an_entry_leaves_the_next_one_to_name_itself() -> None:
    drafts = Drafts()
    drafts.loaded_entry("start", "dos")
    drafts.forget("start")
    assert drafts.loaded_name("start") == ""


def test_a_map_document_is_what_its_own_save_writes(tmp_path: Path) -> None:
    maps = screen_map.Maps()
    maps.application = "lineup"
    maps.session["play"] = screen_map.parse(map_doc("play"), "the test's map")[2]["play"]
    dest = tmp_path / "lineup-screen-map.json"
    maps.save(str(dest), overwrite=False)
    assert dest.read_bytes() == promote.serialised("maps", maps.document("lineup"))


# ---------------------------------------------------------------- the review's blocking fixes


def test_a_path_that_climbs_out_of_the_root_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/../shared/roms"),
                     needs=("system",), path_keys=("rompath",))
    assert re.search("rompath", refused(drafts, root, environ={}))


def test_a_relative_path_is_resolved_against_the_root(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath="roms",
                                             cfg="../outside.cfg"),
                     needs=("system",), path_keys=("rompath", "cfg"))
    assert re.search("cfg", refused(drafts, root, environ={}))
    drafts = drafted("start", "x", start_doc(system="x", rompath="roms"), needs=("system",),
                     path_keys=("rompath",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == \
        "${root}/roms"


def test_a_tilde_user_path_is_refused_and_a_tilde_name_is_a_relative_file(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    tilde = drafted("start", "x", start_doc(system="x", rompath="~bob/roms"),
                    needs=("system",), path_keys=("rompath",))
    assert re.search("rompath", refused(tilde, root))
    drafts = drafted("start", "x", start_doc(system="x", cfg="~draft.cfg"),
                     needs=("system",), path_keys=("cfg",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["cfg"] == "~draft.cfg"


def test_close_leaves_out_what_the_store_already_holds_unchanged(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(drafted("start", "same", start_doc(system="s"), needs=("system",)), root,
          ["start/same"])
    drafts = drafted("start", "same", start_doc(system="s"), needs=("system",))
    assert "draft" not in promote.after_close(drafts, {}, starting=lambda: [root])
    drafts.keep("start", "other", start_doc(system="o"), needs=("system",))
    assert promote.after_close(drafts, {}, starting=lambda: [root])["draft"] == ["start/other"]


def test_close_with_no_store_to_compare_names_the_whole_draft(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    assert promote.after_close(drafts, {}, starting=lambda: [tmp_path])["draft"] == ["start/x"]


def test_close_outlives_a_working_directory_that_is_gone() -> None:
    def gone() -> list[str]:
        raise FileNotFoundError("the working directory")
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    assert promote.after_close(drafts, {}, starting=gone)["draft"] == ["start/x"]


def stored(root: Path, name: str, document: dict[str, Any]) -> Path:
    target = root / ".scry" / "start" / f"{name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document))
    return target


@pytest.mark.parametrize("spelling", ["roms", "./roms", "sub/../roms"])
def test_a_stored_relative_path_that_resolves_the_same_is_unchanged(
        tmp_path: Path, spelling: str) -> None:
    root = repo(tmp_path)
    stored(root, "x", start_doc(system="x", rompath=spelling))
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms"),
                     needs=("system",), path_keys=("rompath",))
    reply = review(drafts, root, environ={})
    assert reply["candidates"] == [] and reply["unchanged"] == ["start/x"]


def test_an_update_keeps_the_authors_spelling_of_an_equivalent_path(tmp_path: Path) -> None:
    root = repo(tmp_path)
    target = stored(root, "x", start_doc(system="x", rompath="roms"))
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms", speed=2),
                     needs=("system",), path_keys=("rompath",))
    candidate = review(drafts, root, environ={})["candidates"][0]
    assert candidate["diff"] == {"added": ["speed"], "removed": [], "changed": []}
    write(drafts, root, ["start/x"], environ={})
    assert json.loads(target.read_text())["rompath"] == "roms"


def test_a_stored_absolute_path_is_rewritten_never_kept_as_the_authors(tmp_path: Path) -> None:
    root = repo(tmp_path)
    target = stored(root, "x", start_doc(system="x", rompath=f"{root}/roms"))
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms"),
                     needs=("system",), path_keys=("rompath",))
    assert review(drafts, root, environ={})["unchanged"] == []
    write(drafts, root, ["start/x"], environ={})
    assert json.loads(target.read_text())["rompath"] == "${root}/roms"


def test_a_stored_path_that_resolves_elsewhere_is_still_a_change(tmp_path: Path) -> None:
    root = repo(tmp_path)
    stored(root, "x", start_doc(system="x", rompath="other"))
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms"),
                     needs=("system",), path_keys=("rompath",))
    assert review(drafts, root, environ={})["candidates"][0]["diff"]["changed"] == [
        {"path": "rompath", "was": "other", "now": "${root}/roms"}]


def test_a_perform_start_block_keeps_the_authors_spelling_too(tmp_path: Path) -> None:
    root = repo(tmp_path)
    document = perform_doc()
    document["start"]["rompath"] = "roms"
    target = root / ".scry" / "perform" / "dos.json"
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(document))
    drafts = drafted("perform", "dos", perform_doc(), path_keys=("rompath",))
    drafts.kept["perform", "dos"].document["start"]["rompath"] = f"{root}/roms"
    assert review(drafts, root, environ={})["unchanged"] == ["perform/dos"]


@pytest.mark.skipif(os.sep != "/", reason="a backslash is a separator here")
def test_a_backslash_in_a_posix_name_is_the_name(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/a\\b"),
                     needs=("system",), path_keys=("rompath",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["rompath"] == \
        "${root}/a\\b"


def test_a_store_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry").write_text("")
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="not a directory"):
        review(drafts, root)


def test_a_symlinked_entry_is_never_replaced(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    outside = tmp_path / "shared.json"
    outside.write_text(json.dumps(start_doc(system="x")))
    (root / ".scry" / "start" / "x.json").symlink_to(outside)
    drafts = drafted("start", "x", start_doc(system="x", boot_seconds=30.0), needs=("system",))
    with pytest.raises(Invalid, match="link"):
        write(drafts, root, ["start/x"])
    assert (root / ".scry" / "start" / "x.json").is_symlink()


def test_a_target_that_is_a_directory_is_refused_before_anything_is_written(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start" / "b.json").mkdir(parents=True)
    drafts = Drafts()
    drafts.keep("start", "a", start_doc(system="a"), needs=("system",))
    drafts.keep("start", "b", start_doc(system="b"), needs=("system",))
    with pytest.raises(Invalid, match="b.json"):
        write(drafts, root, ["start/a", "start/b"])
    assert not (root / ".scry" / "start" / "a.json").exists()
    assert drafts.entries() == ["start/a", "start/b"]


def test_two_entries_written_to_one_name_are_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = Drafts()
    drafts.keep("start", "a", start_doc(system="a"), needs=("system",))
    drafts.keep("start", "b", start_doc(system="b"), needs=("system",))
    with pytest.raises(Invalid, match="own file"):
        write(drafts, root, ["start/a", "start/b"],
              names={"start/a": "z", "start/b": "z"})
    assert drafts.entries() == ["start/a", "start/b"]


def test_a_names_key_that_names_no_entry_of_the_call_is_refused(tmp_path: Path) -> None:
    drafts = drafted("start", "x", start_doc(system="x"), needs=("system",))
    with pytest.raises(Invalid, match="start/y"):
        write(drafts, repo(tmp_path), ["start/x"], names={"start/y": "z"})


def test_a_start_without_its_format_proposes_nothing() -> None:
    assert drafted("start", "x", {"system": "x"}, needs=("system",)).entries() == []


def test_a_map_without_its_format_proposes_nothing() -> None:
    assert drafted("maps", "lineup", {"screens": [{}]}).entries() == []


def test_a_map_the_reader_refuses_is_refused_by_name(tmp_path: Path) -> None:
    document = map_doc("play")
    document["screens"][0]["match"][0]["signature"] = "not-a-signature"
    assert re.search("maps/lineup", refused(drafted("maps", "lineup", document), repo(tmp_path)))


def test_a_renamed_map_is_written_under_its_new_application(tmp_path: Path) -> None:
    root = repo(tmp_path)
    write(drafted("maps", "lineup", map_doc("play")), root, ["maps/lineup"],
          names={"maps/lineup": "speedf"})
    written = root / ".scry" / "maps" / "speedf-screen-map.json"
    assert json.loads(written.read_text())["application"] == "speedf"
    maps = screen_map.Maps()
    assert maps.load(str(written))["application"] == "speedf"


def test_a_reordered_named_list_is_a_change(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "maps").mkdir(parents=True)
    (root / ".scry" / "maps" / "lineup-screen-map.json").write_text(json.dumps(
        map_doc("play", "over")))
    entry = review(drafted("maps", "lineup", map_doc("over", "play")), root)["candidates"][0]
    assert entry["diff"] == {"added": [], "removed": [],
                             "changed": [{"path": "screens[order]", "was": ["play", "over"],
                                          "now": ["over", "play"]}]}


def test_a_perform_step_s_name_is_no_identity_a_reorder_can_hide(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "perform").mkdir(parents=True)
    first = perform_doc()
    first["steps"] = [{"op": "state_write", "method": "load", "name": "boss",
                       "recorded": {"loaded": True}},
                      {"op": "state_write", "method": "load", "name": "title"}]
    (root / ".scry" / "perform" / "dos.json").write_text(json.dumps(first))
    swapped = perform_doc()
    swapped["steps"] = list(reversed(first["steps"]))
    entry = review(drafted("perform", "dos", swapped), root)["candidates"][0]
    assert entry["diff"]["changed"], entry["diff"]


def test_a_document_whose_name_is_not_a_string_is_no_identity_list(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "maps").mkdir(parents=True)
    broken = map_doc("play")
    broken["screens"][0]["name"] = ["play"]
    (root / ".scry" / "maps" / "lineup-screen-map.json").write_text(json.dumps(broken))
    entry = review(drafted("maps", "lineup", map_doc("play")), root)["candidates"][0]
    assert entry["change"] == "update"


def test_an_update_is_measured_without_double_counting_the_bytes_it_replaces(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    entry = root / ".scry" / "start" / "x.json"
    entry.write_text(json.dumps(start_doc(system="x")))
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms"),
                     needs=("system",), path_keys=("rompath",))
    reviewed = review(drafts, root)
    data = json.dumps(start_doc(system="x", rompath="${root}/roms"), indent=2,
                      sort_keys=True).encode() + b"\n"
    assert reviewed["store_bytes"] == len(data), (reviewed["store_bytes"], len(data))


def test_an_update_into_a_full_kind_directory_is_allowed(tmp_path: Path) -> None:
    root = repo(tmp_path)
    store = root / ".scry" / "start"
    store.mkdir(parents=True)
    for n in range(project_store.ENTRIES_MAX - 1):
        (store / f"p{n}.json").write_text("{}")
    (store / "x.json").write_text(json.dumps(start_doc(system="x")))
    drafts = drafted("start", "x", start_doc(system="x", boot_seconds=30.0), needs=("system",))
    assert review(drafts, root)["candidates"][0]["change"] == "update"


def test_a_review_leaves_the_draft_s_own_documents_untouched(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", rompath=f"{root}/roms"),
                     needs=("system",), path_keys=("rompath",))
    review(drafts, root)
    assert drafts.kept["start", "x"].document["rompath"] == f"{root}/roms"


def test_kept_line_and_the_close_and_summary_helpers_say_what_they_mean() -> None:
    drafts = Drafts()
    drafts.keep("start", "x", start_doc(system="x"), needs=("system",))
    assert promote.kept_line(drafts) == "kept 1 (promote to review)"
    assert promote.kept_line(drafts, has_store=False) == (
        "kept 1 (promote to review); there is no .scry/ above this project: "
        "promote(dry_run=true, root=<the repository>) lists what an approval would create")
    reply = promote.after_close(drafts, {"closed": True}, starting=lambda: [])
    assert reply["draft"] == ["start/x"]
    empty = promote.after_close(Drafts(), {"closed": False}, starting=lambda: [])
    assert empty == {"closed": False}
    assert promote.promote_line({}, {"store": "/s", "candidates": [1, 2]}) == \
        "promote: 2 candidates in /s"
    assert promote.promote_line({}, {"store": "/s", "written": [1], "draft": []}) == \
        "promote: 1 entry written to /s, 0 entries still kept"


def test_an_export_is_kept_from_the_file_it_wrote(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    path.write_text(json.dumps(perform_doc()))
    drafts = Drafts()
    reply = promote.after_export(drafts, {"path": str(path)}, ("rompath",))
    assert reply["kept"] == "kept 1 (promote to review)"
    assert drafts.entries() == ["perform/session"]
    bare = promote.after_export(Drafts(), {"path": str(path)}, ("rompath",), has_store=False)
    assert "no .scry/ above this project" in bare["kept"]


def test_a_write_that_fails_says_what_landed_and_keeps_the_rest(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    drafts = Drafts()
    drafts.keep("start", "a", start_doc(system="a"), needs=("system",))
    drafts.keep("start", "b", start_doc(system="b"), needs=("system",))
    real = fresh.replace

    def failing(target: Path, data: bytes, what: str) -> None:
        if target.name == "b.json":
            raise OSError("the disk said no")
        real(target, data, what)

    monkeypatch.setattr(fresh, "replace", failing)
    with pytest.raises(Invalid, match="start/a"):
        write(drafts, root, ["start/a", "start/b"])
    assert (root / ".scry" / "start" / "a.json").is_file()
    assert drafts.entries() == ["start/b"]


def test_a_perform_document_with_no_steps_is_written_as_it_is(tmp_path: Path) -> None:
    root = repo(tmp_path)
    document = perform_doc()
    document["start"] = {"rompath": f"{root}/roms"}
    del document["steps"]
    document["steps"] = []
    assert drafted("perform", "dos", document).entries() == []
    document["needs"] = {"states": [], "declarations": {}}
    document["steps"] = [{"op": "read_memory", "recorded": {"data": "ab"}}]
    del document["steps"]
    drafts = Drafts()
    drafts.kept["perform", "dos"] = promote.Candidate("perform", "dos", document, ("rompath",))
    write(drafts, root, ["perform/dos"])
    assert "steps" not in json.loads((root / ".scry" / "perform" / "dos.json").read_text())


def test_a_tilde_alone_is_the_home_and_a_step_s_own_relative_paths_are_left_alone(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "x", start_doc(system="x", cfg="~"), needs=("system",),
                     path_keys=("cfg",))
    write(drafts, root, ["start/x"])
    assert json.loads((root / ".scry" / "start" / "x.json").read_text())["cfg"] == "${home}"
    document = perform_doc()
    document["start"] = {"rompath": f"{root}/roms"}
    document["steps"] = [{"op": "symbols_load", "path": "relative/x.yaml",
                          "recorded": {"placed": True}},
                         {"op": "guest_file", "path": "/opt/x.bin", "recorded": {}},
                         {"op": "memdump", "ref": "0x0"},
                         {"op": "find", "pattern": None}]
    document["steps"][3]["pattern"] = 3
    drafts = drafted("perform", "dos", document, path_keys=("rompath",))
    write(drafts, root, ["perform/dos"])
    steps = json.loads((root / ".scry" / "perform" / "dos.json").read_text())["steps"]
    assert steps[0]["path"] == "relative/x.yaml" and steps[1]["path"] == "/opt/x.bin"
    assert steps[3]["pattern"] == 3


def test_an_export_with_no_check_is_kept_as_nothing(tmp_path: Path) -> None:
    path = tmp_path / "session.json"
    document = perform_doc()
    document["steps"] = [{"op": "run_for", "frames": 2}]
    path.write_text(json.dumps(document))
    drafts = Drafts()
    assert promote.after_export(drafts, {"path": str(path)}, ()) == {"path": str(path)}
    assert drafts.entries() == []


def test_an_export_whose_file_names_no_entry_is_written_and_not_proposed(tmp_path: Path) -> None:
    path = tmp_path / ("x" * 70 + ".json")
    path.write_text(json.dumps(perform_doc()))
    drafts = Drafts()
    assert promote.after_export(drafts, {"path": str(path)}, ()) == {"path": str(path)}
    assert drafts.entries() == []


def test_an_update_keeps_the_keys_the_run_owns_and_proposes_nothing_when_only_those_differ(
        tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    stored = start_doc(system="lineup", logfile="${root}/TMP/run.log", boot_seconds=8.0)
    (root / ".scry" / "start" / "lineup.json").write_text(json.dumps(stored))
    drafts = drafted("start", "lineup", start_doc(system="lineup", boot_seconds=8.0),
                     needs=("system",), own=("logfile",))
    seen = review(drafts, root)
    assert seen["candidates"] == [] and seen["unchanged"] == ["start/lineup"]
    drafts = drafted("start", "lineup", start_doc(system="lineup", boot_seconds=30.0),
                     needs=("system",), own=("logfile",))
    entry = review(drafts, root)["candidates"][0]
    assert entry["diff"]["removed"] == []
    assert entry["diff"]["changed"] == [{"path": "boot_seconds", "was": 8.0, "now": 30.0}]
    write(drafts, root, ["start/lineup"])
    written = json.loads((root / ".scry" / "start" / "lineup.json").read_text())
    assert written["logfile"] == "${root}/TMP/run.log" and written["boot_seconds"] == 30.0


def test_a_symlinked_kind_directory_is_refused_by_name(tmp_path: Path) -> None:
    root = repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / ".scry").mkdir()
    (root / ".scry" / "maps").symlink_to(elsewhere, target_is_directory=True)
    drafts = drafted("maps", "lineup", map_doc("insert"))
    with pytest.raises(Invalid, match="maps.*link"):
        review(drafts, root)
    assert list(elsewhere.iterdir()) == []


def test_a_windows_path_at_another_case_is_written_against_the_root() -> None:
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath="c:/repo/roms"),
                                  ("rompath",))
    document = promote.tracked(candidate, Path("C:/repo"))
    assert document["rompath"] == "${root}/roms"


@pytest.mark.skipif(os.sep != "/", reason="a drive path is read as Windows reads it")
def test_a_posix_path_at_another_case_is_written_only_where_it_is_the_same_directory(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = repo(tmp_path)
    candidate = promote.Candidate(
        "start", "x", start_doc(system="x", rompath=str(root).swapcase() + "/roms"),
        ("rompath",))

    def refuses() -> None:
        with pytest.raises(Invalid, match="rompath"):
            promote.tracked(candidate, root)

    asked: list[tuple[str, str]] = []

    def same(first: str, second: str) -> bool:
        asked.append((first, second))
        return True

    monkeypatch.setattr(os.path, "samefile", same)
    assert promote.tracked(candidate, root)["rompath"] == "${root}/roms"
    assert asked == [(str(root).swapcase(), str(root))]
    monkeypatch.setattr(os.path, "samefile", lambda first, second: False)
    refuses()

    def gone(first: str, second: str) -> bool:
        raise FileNotFoundError(first)

    monkeypatch.setattr(os.path, "samefile", gone)
    refuses()


def test_an_empty_variable_covers_no_path(tmp_path: Path) -> None:
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath="/elsewhere/roms"),
                                  ("rompath",))
    with pytest.raises(Invalid, match="rompath"):
        promote.tracked(candidate, repo(tmp_path), environ={"EMPTY": ""})


def test_a_steps_tilde_user_path_is_refused_by_name(tmp_path: Path) -> None:
    document = perform_doc()
    document["steps"].append({"op": "symbols_load", "path": "~bob/x.yaml"})
    drafts = drafted("perform", "lineup", document)
    assert re.search("steps.*~bob/x.yaml", refused(drafts, repo(tmp_path)))


@pytest.mark.parametrize("path", ["c:/repository/roms", "c:/repo2"])
def test_a_windows_path_at_another_case_is_held_to_the_roots_own_segment(path: str) -> None:
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath=path), ("rompath",))
    with pytest.raises(Invalid, match="rompath"):
        promote.tracked(candidate, Path("C:/repo"), environ={})


def test_the_root_itself_at_another_case_is_the_root() -> None:
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath="c:/repo"),
                                  ("rompath",))
    assert promote.tracked(candidate, Path("C:/repo"))["rompath"] == "${root}"


def test_a_host_directory_at_another_case_is_asked_of_the_real_filesystem(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / "roms").mkdir()
    spelled = str(root).swapcase()
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath=spelled + "/roms"),
                                  ("rompath",))
    if Path(spelled).exists():
        assert promote.tracked(candidate, root)["rompath"] == "${root}/roms"
    else:
        with pytest.raises(Invalid, match="rompath"):
            promote.tracked(candidate, root)


def test_a_key_the_run_owns_that_the_store_lacks_is_not_invented(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    stored = start_doc(system="lineup", logfile="${root}/run.log")
    target = root / ".scry" / "start" / "lineup.json"
    target.write_text(json.dumps(stored))
    own = ("logfile", "size")
    drafts = drafted("start", "lineup", start_doc(system="lineup"), needs=("system",), own=own)
    assert review(drafts, root)["unchanged"] == ["start/lineup"]
    drafts = drafted("start", "lineup", start_doc(system="lineup", boot_seconds=3.0),
                     needs=("system",), own=own)
    write(drafts, root, ["start/lineup"])
    assert "size" not in json.loads(target.read_text())


def test_a_stored_entry_that_is_no_object_is_shown_replaced(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    (root / ".scry" / "start" / "lineup.json").write_text("[]")
    drafts = drafted("start", "lineup", start_doc(system="lineup"), needs=("system",),
                     own=("logfile",))
    entry = review(drafts, root)["candidates"][0]
    assert entry["change"] == "update" and entry["diff"]["changed"][0]["was"] == []


def test_a_review_bills_only_what_it_offers(tmp_path: Path) -> None:
    root = repo(tmp_path)
    (root / ".scry" / "start").mkdir(parents=True)
    stored = start_doc(system="same")
    (root / ".scry" / "start" / "same.json").write_text(json.dumps(stored))
    drafts = drafted("start", "same", start_doc(system="same"), needs=("system",))
    drafts.keep("start", "fresh", start_doc(system="fresh"), needs=("system",))
    seen = review(drafts, root)
    assert seen["unchanged"] == ["start/same"]
    assert [item["entry"] for item in seen["candidates"]] == ["start/fresh"]
    assert seen["total_bytes"] == seen["candidates"][0]["bytes"]


def test_a_symlinked_kind_directory_is_never_written_through(tmp_path: Path) -> None:
    root = repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / ".scry").mkdir()
    (root / ".scry" / "maps").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(Invalid, match="maps.*link"):
        write(drafted("maps", "lineup", map_doc("insert")), root, ["maps/lineup"])
    assert list(elsewhere.iterdir()) == []


def test_a_store_that_is_a_link_is_refused_by_name(tmp_path: Path) -> None:
    root = repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / ".scry").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(Invalid, match=r"\.scry.*link"):
        write(drafted("maps", "lineup", map_doc("insert")), root, ["maps/lineup"])
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("text", ["~3/4 done", "~/not a path", "~bob/x"])
def test_a_steps_free_text_starting_with_a_tilde_is_left_alone(tmp_path: Path, text: str) -> None:
    document = perform_doc()
    document["steps"].append({"op": "send_keys", "keys": text})
    candidate = promote.Candidate("perform", "x", document)
    assert promote.tracked(candidate, repo(tmp_path))["steps"][-1]["keys"] == text


def test_a_steps_home_path_is_still_written_as_the_home(tmp_path: Path) -> None:
    document = perform_doc()
    document["steps"].append({"op": "symbols_load", "path": "~/x.yaml"})
    candidate = promote.Candidate("perform", "x", document)
    assert promote.tracked(candidate, repo(tmp_path))["steps"][-1]["path"] == "${home}/x.yaml"


def test_a_home_path_that_climbs_out_of_the_home_is_refused(tmp_path: Path) -> None:
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath="~/../other"),
                                  ("rompath",))
    with pytest.raises(Invalid, match="rompath"):
        promote.tracked(candidate, repo(tmp_path))


def test_two_entries_differing_only_in_case_are_one_file_and_refused(tmp_path: Path) -> None:
    root = repo(tmp_path)
    drafts = drafted("start", "lineup", start_doc(system="a"), needs=("system",))
    drafts.keep("start", "Lineup", start_doc(system="b"), needs=("system",))
    with pytest.raises(Invalid, match="twice"):
        write(drafts, root, ["start/lineup", "start/Lineup"])


def test_only_the_run_is_a_subset_and_unknown_names_are_never_it() -> None:
    own = frozenset({"profile", "state_dir"})
    assert promote.only_the_run(frozenset({"profile"}), own)
    assert not promote.only_the_run(frozenset({"profile", "system"}), own)
    assert not promote.only_the_run(None, own)


def rom_paths(block: Any) -> list[str]:
    return str(block.get("rompath") or "").split(";")


def test_the_store_is_looked_for_from_the_loaded_file_first_even_with_no_recipe_kept(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "game" / ".scry" / "start" / "x.json"
    drafts = Drafts()
    drafts.loaded_entry("start", "x", source=str(source))
    drafts.keep("maps", "x", map_doc("insert"))
    assert promote.starting(drafts, rom_paths) == [str(source), os.getcwd()]
    drafts.forget("start")
    assert promote.starting(drafts, rom_paths) == [os.getcwd()]


def test_the_store_is_looked_for_from_a_perform_documents_start_block(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    document = perform_doc()
    document["start"] = {"rompath": "/game/roms;/game/more"}
    drafts = drafted("perform", "x", document)
    assert promote.starting(drafts, rom_paths) == ["/game/roms", "/game/more", os.getcwd()]


def test_the_stores_starting_points_are_absolute_and_stripped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    drafts = drafted("start", "x", start_doc(system="x", rompath="~/g;roms; /abs/a;"),
                     needs=("system",))
    starts = promote.starting(drafts, rom_paths)
    assert [Path(start) for start in starts] == [tmp_path / "g", Path("/abs/a"), Path.cwd()]


def test_a_found_store_is_the_one_a_write_lands_in_with_the_recipe_elsewhere(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "here").mkdir()
    (tmp_path / "game").mkdir()
    here = repo(tmp_path / "here")
    (here / ".scry").mkdir()
    game = repo(tmp_path / "game")
    (game / ".scry" / "start").mkdir(parents=True)
    monkeypatch.chdir(here)
    source = game / ".scry" / "start" / "x.json"
    drafts = Drafts()
    drafts.loaded_entry("start", "x", source=str(source))
    drafts.keep("maps", "x", map_doc("insert", application="x"))
    seen = promote.review(drafts, starting=promote.starting(drafts, rom_paths))
    assert Path(seen["store"]).resolve() == (game / ".scry").resolve()


@pytest.mark.parametrize("root_value", ["/", "C:", "C:/", "C:\\"])
def test_a_variable_holding_a_filesystem_root_covers_no_path(
        tmp_path: Path, root_value: str) -> None:
    drive = "C:/elsewhere/roms" if root_value.startswith("C") else "/elsewhere/roms"
    candidate = promote.Candidate("start", "x", start_doc(system="x", rompath=drive), ("rompath",))
    with pytest.raises(Invalid, match="rompath"):
        promote.tracked(candidate, repo(tmp_path), environ={"OLDPWD": root_value})


def test_the_promote_description_says_the_conditions_its_reply_model_promises() -> None:
    doc = promote.DOC_VALUES["PROMOTE"]
    assert reply_schema.conditions_unsaid(doc, promote.PromoteFields) == []


def test_a_root_that_reaches_the_store_through_dotdot_is_refused(
        tmp_path: Path) -> None:
    (tmp_path / ".scry" / "start").mkdir(parents=True)
    with pytest.raises(Invalid, match="names the store itself"):
        promote.store([tmp_path], root=str(tmp_path / ".scry" / "start" / ".."))
