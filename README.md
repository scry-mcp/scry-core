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

## Developing

```sh
uv sync
uv run ruff check .
uv run mypy --strict .
uv run pytest -q
```

Licence: MIT.
