# scry-core

What the Scry emulator MCP servers ([scry-mame](https://github.com/scry-mcp/scry-mame) and
[scry-dosbox-x](https://github.com/scry-mcp/scry-dosbox-x)) share, held once:

| Module | What it holds |
|---|---|
| `scry_core.reply_contract` | the refusal contract (`status`, `code`, `message`), its class and its envelope check |
| `scry_core.strict_arguments` | the schema as part of a tool's contract: what it does not declare is refused |
| `scry_core.value_format` | the grammar of a watched value: scalars, arrays, strings, structs, pointers |
| `scry_core.reply_shapes` | the test-time guard holding one word to one shape in every reply |
| `scry_core.client_cap` | the prefix of a text the MCP client delivers, in its own unit |
| `scry_core.probe` | what a model calls when all it holds is what the client delivers |
| `scry_core.live_bench` | the pinned copies a server's live tier runs on |

Each server pins it by a release tag, never by a branch:

```toml
dependencies = ["scry-core @ git+https://github.com/scry-mcp/scry-core@<tag>"]
```

The two programs take what they act on as required options, so neither reads a tree it was not
pointed at. The probe's paths below are a server repository's own; the manifest is the bench's:

```sh
python -m scry_core.probe all --check --servers mcp_probe/servers.py --tasks mcp_probe/tasks
python -m scry_core.live_bench check --server mame --manifest <bench>/bench.json
```

`--help` on either is its contract. A real probe run asks the `claude` CLI and needs the network;
`--check` and the replay seam need neither. `live_bench` reads its bench from `MAME_LIVE_BENCH` or
`DOSBOX_X_LIVE_BENCH` (by default `~/.local/share/scry-bench/<server>`), and `fill` runs the
`capture` commands its manifest names, so it fills only from checkouts you trust.

`reply_shapes` is a pytest fixture module: a server's root `conftest.py` imports
`one_word_one_shape` from it, with the `pytest` extra installed in its test tier.

## Developing

```sh
uv sync
uv run ruff check .
uv run mypy --strict .
uv run pytest -q
```

Licence: MIT.
