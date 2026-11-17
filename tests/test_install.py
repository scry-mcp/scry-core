"""The table of clients and the README block it renders: every entry starts the same server
the same way, in the form its client takes, and a README is checked and rewritten from it."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest

from scry_core import example, install
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

ORDER = ["Claude Code", "Codex", "Claude Desktop", "Cursor", "VS Code", "Copilot CLI",
         "Gemini CLI", "Antigravity", "Devin", "Another client"]
README = f"# A server\n\n## Install\n\n{install.BEGIN}\nold\n{install.END}\n\nAfter.\n"


def test_a_package_names_its_server() -> None:
    assert install.server("scry_mame") == install.Server("mame", "scry-mame")
    assert install.server("scry_dosbox_x") == install.Server("dosbox-x", "scry-dosbox-x")
    assert install.server("scry_mame").clone == "/path/to/scry-mame"
    for wrong in ("mame", "scry-mame", "scry_", "scry_ma me"):
        with pytest.raises(Invalid, match="names no SCRY server"):
            install.server(wrong)


def test_the_clients_are_the_ten_in_their_order_each_from_its_vendor_s_page() -> None:
    assert [client.name for client in install.CLIENTS] == ORDER
    pages = [client.page for client in install.CLIENTS]
    assert all(page.startswith("https://") for page in pages[:-1]) and pages[-1] == ""
    assert len(set(pages)) == len(pages), "two clients share a page"


@pytest.mark.parametrize("package", ["scry_mame", "scry_dosbox_x"])
def test_every_entry_starts_the_same_server_the_same_way(package: str) -> None:
    to = install.server(package)
    for client in install.CLIENTS:
        entry = client.entry(to)
        if client.language == "sh":
            words = shlex.split(entry.replace(install.HERE, to.clone))
            launch = [w for w in words if w != "--"][-5:]
            if client.name != "Another client":
                assert words[1:3] == ["mcp", "add"] and to.name in words[3:6], entry
        else:
            body = json.loads(entry)
            (key, servers), = body.items()
            assert key in ("mcpServers", "servers") and list(servers) == [to.name], entry
            launch = [servers[to.name]["command"], *servers[to.name]["args"]]
            assert set(servers[to.name]) - {"type"} == {"command", "args"}, entry
        assert launch == ["uv", "run", "--directory", to.clone, to.command], (client.name, entry)


def test_the_clients_whose_page_asks_for_a_type_carry_it() -> None:
    to = install.server("scry_mame")
    typed = {client.name: json.loads(client.entry(to)) for client in install.CLIENTS
             if client.language == "json"}
    assert typed["Cursor"]["mcpServers"]["mame"]["type"] == "stdio"
    assert typed["VS Code"]["servers"]["mame"]["type"] == "stdio"
    assert "type" not in typed["Claude Desktop"]["mcpServers"]["mame"]
    assert "type" not in typed["Antigravity"]["mcpServers"]["mame"]


def test_gemini_takes_the_dashed_words_after_the_separator() -> None:
    gemini = next(client for client in install.CLIENTS if client.name == "Gemini CLI")
    assert gemini.entry(install.server("scry_mame")) == \
        'gemini mcp add --scope user mame uv run -- --directory "$PWD" scry-mame'


def test_the_block_folds_one_entry_per_client_within_a_readme_s_limits() -> None:
    block = install.block("scry_dosbox_x")
    heads = re.findall(r"^<details( open)?><summary>(.+)</summary>$", block, re.MULTILINE)
    assert [name for _, name in heads] == ORDER
    assert [bool(is_open) for is_open, _ in heads] == [True] + [False] * 9, "only the first"
    assert block.count("</details>") == len(ORDER)
    for client in install.CLIENTS:
        assert example.sentences(client.says) <= 2, client.name
        assert all(len(s.split()) <= 30 for s in re.split(r"(?<=[.?!])\s+", client.says)), \
            client.name
    for code in re.findall(r"```(?:sh|json)\n(.*?)\n```", block, re.DOTALL):
        lines = code.splitlines()
        assert len(lines) <= example.REPLY_LINES and all(
            len(line) <= example.COLUMNS for line in lines), code
    assert block.count("```sh\n") == 6 and block.count("```json\n") == 4


def test_a_readme_is_checked_and_rewritten_from_the_table(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README)
    assert install.drift(readme, "scry_mame").startswith("line 1: the README has 'old', the "
                                                         "table of clients has '<details open>")
    assert install.main(["scry_mame", "--readme", str(readme)]) == EXIT_FAIL
    said = capsys.readouterr().out
    assert "the install block is out of date: line 1" in said \
        and "python -m scry_core.install scry_mame --write" in said
    assert readme.read_text() == README, "a check wrote the README"
    assert install.main(["scry_mame", "--readme", str(readme), "--write"]) == EXIT_PASS
    assert "was rewritten for 10 clients" in capsys.readouterr().out
    text = readme.read_text()
    assert text.startswith("# A server\n\n## Install\n\n") and text.endswith("\n\nAfter.\n")
    assert install.drift(readme, "scry_mame") == ""
    assert install.main(["scry_mame", "--readme", str(readme)]) == EXIT_PASS
    assert install.main(["scry_mame", "--readme", str(readme), "--write"]) == EXIT_PASS
    assert readme.read_text() == text, "a current block was written again differently"
    assert install.drift(readme, "scry_dosbox_x") != "", "another server's block passed"


@pytest.mark.parametrize(("text", "package", "why"), [
    ("# no markers\n", "scry_mame", "exactly once each"),
    (README, "mame", "names no SCRY server"),
    (None, "scry_mame", "cannot be read"),
])
def test_a_readme_or_a_package_that_cannot_be_read_is_invalid(
        tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str | None, package: str,
        why: str) -> None:
    readme = tmp_path / "README.md"
    if text is not None:
        readme.write_text(text)
    assert install.main([package, "--readme", str(readme), "--write"]) == EXIT_INVALID
    assert why in capsys.readouterr().out
    assert text is None or readme.read_text() == text


def test_the_command_line_refuses_what_it_does_not_know() -> None:
    with pytest.raises(SystemExit) as stop:
        install.main(["scry_mame", "--wrte"])
    assert stop.value.code == 2
