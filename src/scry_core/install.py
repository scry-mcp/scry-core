"""The clients a SCRY server is added to, and the block a server's README carries for them.

One table, `CLIENTS`: each client's name, the page of its vendor the entry is built from, what
that page says to do in at most two sentences, and how it spells a local server over stdio.
Every entry starts the same server the same way, `uv run --directory <the clone> <command>`,
under the server's own name; a shell entry is run from the clone, a file entry names the
clone's absolute path. A server's README and the site render the same table, so they cannot
disagree.

Run `python -m scry_core.install <package> [--readme PATH] [--write]` from the server's
repository: `<package>` is the server's package (`scry_mame`), the block sits between `BEGIN` and
`END` in `PATH` (default `README.md`). Without `--write` nothing is written.

EXIT: 0 the block is current, or was written; 1 it is out of date; 2 a usage error; 3 INVALID
(a package that names no SCRY server, a README that cannot be read, markers not there once).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from scry_core import demo
from scry_core.verdict import EXIT_FAIL, EXIT_INVALID, EXIT_PASS, Invalid

BEGIN = "<!-- scry-install:begin -->"
END = "<!-- scry-install:end -->"
PACKAGE_PREFIX = "scry_"
#: The clone's directory as a shell entry names it: the entry is run from inside the clone.
HERE = '"$PWD"'


@dataclass(frozen=True)
class Server:
    """A SCRY server as a client is told about it: the `name` it is added under, the `command`
    that starts it, and the `clone` a file entry names."""

    name: str
    command: str

    @property
    def clone(self) -> str:
        return f"/path/to/{self.command}"

    def launch(self, clone: str) -> list[str]:
        """The words that start the server over stdio from the clone at `clone`."""
        return ["uv", "run", "--directory", clone, self.command]


def server(package: str) -> Server:
    """The server whose package is `package`: `scry_dosbox_x` is `scry-dosbox-x`, added as
    `dosbox-x`."""
    if not package.startswith(PACKAGE_PREFIX) or not package.removeprefix(
            PACKAGE_PREFIX).replace("_", "").isalnum():
        raise Invalid(f"{package!r} names no SCRY server: its package is `{PACKAGE_PREFIX}"
                      "<emulator>`, as in `scry_mame`")
    command = package.replace("_", "-")
    return Server(command.removeprefix(PACKAGE_PREFIX.replace("_", "-")), command)


@dataclass(frozen=True)
class Client:
    """One client: its `name`, the vendor's `page` its entry is built from, what that page says
    to do (`says`), the `language` of the entry and the entry itself for a server."""

    name: str
    page: str
    says: str
    language: str
    entry: Callable[[Server], str]


def _shell(*before: str) -> Callable[[Server], str]:
    """A client's own `add` command: its words, the server's name, `--`, then the launch."""
    def entry(to: Server) -> str:
        return " ".join([*before, to.name, "--", *to.launch(HERE)])
    return entry


def _gemini(to: Server) -> str:
    """Gemini CLI takes the command's plain words first and those that begin with a dash after
    `--`."""
    command, verb, *dashed = to.launch(HERE)
    return " ".join(["gemini", "mcp", "add", "--scope", "user", to.name, command, verb, "--",
                     *dashed])


def _file(key: str, **fields: str) -> Callable[[Server], str]:
    """A client's configuration file: the server under `key`, with `fields` before its command."""
    def entry(to: Server) -> str:
        command, *args = to.launch(to.clone)
        body = {**fields, "command": command, "args": args}
        rows = [f"      {json.dumps(k)}: {json.dumps(v)}" for k, v in body.items()]
        return "\n".join(["{", f"  {json.dumps(key)}: {{", f"    {json.dumps(to.name)}: {{",
                          ",\n".join(rows), "    }", "  }", "}"])
    return entry


CLIENTS: tuple[Client, ...] = (
    Client("Claude Code", "https://code.claude.com/docs/en/mcp",
           "Run this from the clone. `--scope user` makes the server available to you across "
           "all projects, and `claude mcp list` shows it.",
           "sh", _shell("claude", "mcp", "add", "--scope", "user")),
    Client("Codex", "https://learn.chatgpt.com/docs/extend/mcp?surface=cli",
           "Run this from the clone. `codex mcp list` shows the server.",
           "sh", _shell("codex", "mcp", "add")),
    Client("Claude Desktop", "https://modelcontextprotocol.io/docs/develop/connect-local-servers",
           "In Settings, open the Developer tab and choose Edit Config, which opens "
           "`claude_desktop_config.json`; add this with the clone's absolute path. Then quit "
           "Claude Desktop completely and start it again.",
           "json", _file("mcpServers")),
    Client("Cursor", "https://cursor.com/docs/context/mcp",
           "Put this in `~/.cursor/mcp.json` to have the server everywhere, or in "
           "`.cursor/mcp.json` inside one project, with the clone's absolute path.",
           "json", _file("mcpServers", type="stdio")),
    Client("VS Code", "https://code.visualstudio.com/docs/agents/reference/mcp-configuration",
           "Put this in `.vscode/mcp.json` in your workspace, with the clone's absolute path.",
           "json", _file("servers", type="stdio")),
    Client("Copilot CLI",
           "https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/"
           "add-mcp-servers",
           "Run this from the clone. `copilot mcp list` shows the server.",
           "sh", _shell("copilot", "mcp", "add")),
    Client("Gemini CLI", "https://geminicli.com/docs/tools/mcp-server/",
           "Run this from the clone. `--scope user` keeps it in your own settings, and "
           "`gemini mcp list` shows it, disabled while the folder you are in is not trusted.",
           "sh", _gemini),
    Client("Antigravity", "https://antigravity.google/docs/mcp",
           "Put this in `~/.gemini/config/mcp_config.json` for every workspace, or in "
           "`.agents/mcp_config.json` inside one, with the clone's absolute path.",
           "json", _file("mcpServers")),
    Client("Devin", "https://docs.devin.ai/cli/extensibility/mcp/configuration.md",
           "Run this from the clone. `--scope user` keeps it in your own configuration, "
           "`~/.config/devin/mcp_config.json`, and `devin mcp list` shows the server.",
           "sh", _shell("devin", "mcp", "add", "--scope", "user")),
    Client("Another client", "",
           "Any client that runs a local server over stdio starts this command, with the "
           "clone's absolute path.",
           "sh", lambda to: " ".join(to.launch(to.clone))),
)


def block(package: str) -> str:
    """The README block for the server `package`: one folded entry per client, the first open."""
    to = server(package)
    parts = []
    for n, client in enumerate(CLIENTS):
        parts.append("\n".join([
            f"<details{' open' if n == 0 else ''}><summary>{client.name}</summary>", "",
            client.says, "", f"```{client.language}", client.entry(to), "```", "",
            "</details>"]))
    return "\n\n".join(parts)


def drift(readme: Path, package: str) -> str:
    """How the README's block departs from the table, or empty; `Invalid` when the README or its
    markers cannot be read."""
    return demo.first_difference(demo.block_of(_read(readme), BEGIN, END), block(package),
                                 ("the README", "the table of clients"))


def _read(readme: Path) -> str:
    try:
        return readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise Invalid(f"{readme} cannot be read ({type(e).__name__})") from e


def write(readme: Path, package: str) -> None:
    """Rewrite the README's block from the table; `Invalid` when it cannot be written."""
    text = demo.with_block(_read(readme), block(package), BEGIN, END)
    try:
        readme.write_text(text, encoding="utf-8")
    except OSError as e:
        raise Invalid(f"{readme} cannot be written ({type(e).__name__})") from e


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m scry_core.install", allow_abbrev=False,
                                description="Check or rewrite the block of a server's README "
                                            "that says how to add it to each client.",
                                epilog="Exit codes: 0 current or written, 1 out of date, 2 a "
                                       "usage error, 3 the package or the README cannot be read.")
    p.add_argument("package", help="the server's package, as in scry_mame")
    p.add_argument("--readme", type=Path, default=Path("README.md"),
                   help="the README that carries the block (default: README.md)")
    p.add_argument("--write", action="store_true", help="rewrite the block")
    ns = p.parse_args(argv)
    try:
        found = drift(ns.readme, ns.package)
        if found and ns.write:
            write(ns.readme, ns.package)
            print(f"{ns.readme}: the install block was rewritten for {len(CLIENTS)} clients")
            return EXIT_PASS
    except Invalid as e:
        print(f"INVALID: {e}")
        return EXIT_INVALID
    if found:
        print(f"{ns.readme}: the install block is out of date: {found}")
        print(f"rewrite it: python -m scry_core.install {ns.package} --write")
        return EXIT_FAIL
    print(f"{ns.readme}: the install block is current, {len(CLIENTS)} clients")
    return EXIT_PASS


if __name__ == "__main__":  # pragma: no cover -- a thin entry, `main` is what the tests run
    sys.exit(main())
