#!/usr/bin/env bash
# Copy the three repositories' main and tags to the Windows host as bundles, then sync its clones.
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
"$here/msys.sh" <<< "bash \"\$(cygpath -u '$SCRY_WIN_ROOT')/sync.sh\"" | tr -d '\r'
