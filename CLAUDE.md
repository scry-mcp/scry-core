# scry-core

Context for a coding assistant working on this repository. The public documentation starts at
`README.md`; this file says what the repository is, how to check a change, and where its rules
live.

## What this repository is

The Python package the SCRY MCP servers share: the reply envelope, the reference and install
generators, the demo and motion tools, the test plugins and the commit hook the servers run.
Each server (scry-dosbox-x, scry-mame) pins it by a git tag, so a change to `src/` reaches a
server only through a release and a pin. `docs/modules.md` lists the modules; a module's
contract is in its docstring.

## Checking a change

```sh
uv run ruff check .
uv run mypy --strict .
uv run mypy --strict --platform win32 .
uv run pytest -q
```

`README.md`, *Developing* and *Opt-in tests*, says what each proves and how Windows differs.

## How work is done here

- English everywhere: code, comments, documents, commit messages.
- Conventional Commits; the body says why.
- A new test is seen failing first, by breaking the line it covers.
- No new check, hook or CI step is added without the maintainers asking for it.

## Rules

Path-scoped rules live in `.claude/rules/` and load when a file they govern is opened.

- The harness, mandates, reports and source material the knowledge base was written from live in the private repository `scry-mcp/scry-kb`.
