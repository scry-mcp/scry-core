# scry-core

What the Scry emulator MCP servers ([scry-mame](https://github.com/scry-mcp/scry-mame) and
[scry-dosbox-x](https://github.com/scry-mcp/scry-dosbox-x)) share, held once:

| Module | What it holds |
|---|---|
| `scry_core.reply_contract` | the refusal contract (`status`, `code`, `message`), its class and its envelope check |
| `scry_core.strict_arguments` | the schema as part of a tool's contract: what it does not declare is refused |
| `scry_core.value_format` | the grammar of a watched value: scalars, arrays, strings, structs, pointers |
| `scry_core.reply_shapes` | the pytest plugin running the test-time guard (`reply_shapes_guard`) that holds one word to one shape in every reply |
| `scry_core.client_cap` | the prefix of a text the MCP client delivers, in its own unit |
| `scry_core.probe` | what a model calls when all it holds is what the client delivers |
| `scry_core.probe_checks` | what each server's suite checks on its own probe surface: tasks, captures, the cap |
| `scry_core.live_bench` | the pinned copies a server's live tier runs on |
| `scry_core.hook` | the pre-commit every pinning repository runs: new duplication, and the probe's tasks |
| `scry_core.demo` | the runner of a server's `demos/`: its steps over stdio, their checks, and the README block they generate |

Each server pins it by a release tag, never by a branch:

```toml
dependencies = ["scry-core @ git+https://github.com/scry-mcp/scry-core@<tag>"]
```

The probe and the bench take what they act on as required options, so neither reads a tree it was
not pointed at. The probe's paths below are a server repository's own; the bench is the directory a
server's live tier resolved, and its manifest is `<bench>/bench.json`. The hook takes none: it runs
from inside a repository that tracks `.jscpd-baseline.json`, has `jscpd` on the path and keeps its
probe at `mcp_probe/servers.py` and `mcp_probe/tasks/`:

```sh
python -m scry_core.probe all --check --servers mcp_probe/servers.py --tasks mcp_probe/tasks
python -m scry_core.live_bench check --bench <bench>
python -m scry_core.hook
```

`--help` on each is its contract. A real probe run asks the `claude` CLI and needs the network;
`--check` and the replay seam need neither. `fill` runs the `capture` commands its manifest names,
so it fills only from checkouts you trust. Each repository's `.githooks/pre-commit.sh` is the one
line that calls the hook through its own `uv run`.

`reply_shapes` is a pytest plugin, loaded through the `pytest11` entry point wherever this package
is installed. A suite declares the modules it wraps in its own configuration, and a run that
declares none is refused:

```toml
[tool.pytest.ini_options]
reply_shapes_anchors = ["scry_core.reply_contract", "server"]
```

## Demos

Each server keeps its demos in `demos/<name>/`: a README with the prompt to give an MCP client, a
`demo.py` making the same calls and checking each answer, and the transcript and `screen.png` that
`demo.py --update-readme` writes from a run where every step passed, so what the README shows is
what the server answered. `scry_core.demo` is the runner both servers share, and its module
docstring is the contract.

## Trying a server by hand

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) calls either server directly
and shows each raw request and reply. It starts its own copy of the server, so it cannot see a
session another client holds. One config covers both servers, which is why it lives here. The
UI labels an entry by its key, and a server given on the command line is labelled by its command,
`uv`, so save the servers under their names as `inspector.json`:

```json
{
  "mcpServers": {
    "Scry - MAME MCP": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/scry-mame", "python", "server.py"],
      "env": {"MAME_BINARY": "/path/to/mame"}
    },
    "Scry - DOSBox-X MCP": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/scry-dosbox-x", "python", "dosbox_x_server.py"]
    }
  }
}
```

`MAME_BINARY` is optional: without it `start` takes `mame` from the `PATH`, and either way the
build needs what the scry-mame README lists. Run this beside the file and open the URL it prints,
token included; `HOST` keeps the UI on loopback:

```sh
HOST=127.0.0.1 npx -y @modelcontextprotocol/inspector@2.11.0 --web --config inspector.json
```

`--cli` starts a fresh server per call, so the emulator a `start` opened dies with it; use the
web UI for anything that spans calls. `--cli` exits 0 on a refusal: an `INVALID` reply is a
result, `isError: false`, so read its `status`. A non-zero exit is the call itself failing,
such as an unknown tool.

## Developing

```sh
uv sync
uv run ruff check .
uv run mypy --strict .
uv run pytest -q
```

Licence: MIT.
