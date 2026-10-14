"""What the Scry emulator MCP servers share, held once and pinned by each server by tag.

`reply_contract` (the refusal contract and its envelope check), `strict_arguments` (the schema as
part of a tool's contract), `value_format` (the grammar of a watched value), `reply_shapes` (the
pytest plugin running `reply_shapes_guard`, which holds one word to one shape), `client_cap` (the
prefix of a text the MCP client delivers), `probe` (what a model calls from the delivered texts),
`probe_checks` (what each server's suite checks on its own probe surface), `live_bench` (the pinned
copies a live tier runs on) and `hook` (the pre-commit of every pinning repository).
"""
