"""What the Scry emulator MCP servers share, held once and pinned by each server by tag.

`reply_contract` (the refusal contract and its envelope check), `strict_arguments` (the schema as
part of a tool's contract), `value_format` (the grammar of a watched value), `reply_shapes` (the
test-time guard holding one word to one shape), `client_cap` (the prefix of a text the MCP client
delivers), `probe` (what a model calls from the delivered texts) and `live_bench` (the pinned
copies a live tier runs on).
"""
