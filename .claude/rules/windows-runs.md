---
paths:
  - "scripts/windows/**"
---

# The Windows run scripts

The host they drive (the run root, its ssh and `uv` traps, the scheduled task) is the owner's
`~/.claude/reference/windows-host.md` and `scry-dev.md`; these are the scripts' own contract.

- The recipe, from `scripts/windows/` in scry-core, with `SCRY_WIN_SSH` (user@host) and `SCRY_WIN_ROOT` (the run root) set: `bundle.sh` copies main and tags of the three repos as bundles, with the `sync.sh` of the scry-core `main` it carries, and runs that `sync.sh` to bring the mirrors and clones to them (git only, fine over ssh); a sync that could not bring a repository fails it; `push-tree.sh <repo>` copies a working tree under test over its clone (sync resets the clones); `run-task.sh <step> <secs>` registers the task, waits, confirms none is left and fetches `logs/<step>/`. `scry-run.sh` and `scry-run.cmd` live only on the host. A step is sourced with `$W`, `$step` and `$L` set; before each run it lists the `dosbox`, `mame` and `python` processes, and never starts one over ssh.
- `scripts/windows/display_scale.py read|set <pct>` sets the primary display's scale through the undocumented `DisplayConfigSetDeviceInfo` (types -3 get, -4 set; `read` matches the registry's `AppliedDPI`). A step that changes it restores the owner's scale in a trap and reads it back afterwards.
