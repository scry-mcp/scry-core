#!/usr/bin/env bash
# Copy the three repositories' main and tags to the Windows host as bundles, with the sync.sh of
# the scry-core main carried, then run it: a copy left on the host would run stale.
set -euo pipefail
: "${SCRY_WIN_SSH:?set SCRY_WIN_SSH to the Windows host, user@host}"
: "${SCRY_WIN_ROOT:?set SCRY_WIN_ROOT to the Windows run root, C:/.../scry-win}"
here=$(cd "$(dirname "$0")" && pwd)
code=$(cd "$here/../../.." && pwd)
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
for repo in scry-core scry-mame scry-dosbox-x; do
  git -C "$code/$repo" bundle create -q "$out/$repo.bundle" main --tags
  scp -q "$out/$repo.bundle" "$SCRY_WIN_SSH:$SCRY_WIN_ROOT/$repo.bundle"
done
git -C "$code/scry-core" show main:scripts/windows/sync.sh > "$out/sync.sh"
scp -q "$out/sync.sh" "$SCRY_WIN_SSH:$SCRY_WIN_ROOT/sync.sh"
"$here/msys.sh" <<< "bash \"\$(cygpath -u '$SCRY_WIN_ROOT')/sync.sh\"" | tr -d '\r'
