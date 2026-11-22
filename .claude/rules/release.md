---
paths:
  - "pyproject.toml"
  - "CHANGELOG.md"
  - "src/**"
---

# A release of scry-core, and the servers' pins

The servers take scry-core by its git tag, so a change to `src/` reaches them only through a
release and a pin; a change to the docs or the tests needs neither.

1. **The release**, one commit `chore(release): X.Y.Z`: the version in `pyproject.toml`, the
   `## Unreleased` heading of `CHANGELOG.md` renamed `## X.Y.Z`, and `uv lock` so `uv.lock` names
   it. Then the tag `vX.Y.Z` on that commit, pushed with it.
2. **The pin**, in each server, one commit `build(deps): pin scry-core X.Y.Z`: the
   `scry-core @ git+https://github.com/scry-mcp/scry-core@vX.Y.Z` line of its `pyproject.toml`,
   `uv lock`, and a line under its own `## Unreleased` for what a client notices.
3. **Before a Windows run** that tests the pin, `scripts/windows/bundle.sh` first: the clones there
   resolve the tag against the bundles copied over, and one that has not seen it fails `uv sync`.

Each of these is a commit and a push, so each waits for a maintainer's yes.

scry-core's own commit runs its CI (ruff, mypy on both platforms, pytest); the pre-commit hook
`scry_core.hook` (jscpd, the prose ceiling, the probe) is the servers', run in their
repositories.
