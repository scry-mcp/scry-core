#!/usr/bin/env bash
# Run the bash script on stdin in the Windows host's MSYS2 login shell.
set -euo pipefail
: "${SCRY_WIN_SSH:?set SCRY_WIN_SSH to the Windows host, user@host}"
exec ssh -o BatchMode=yes "$SCRY_WIN_SSH" \
  'C:\msys64\usr\bin\env.exe MSYSTEM=UCRT64 C:\msys64\usr\bin\bash.exe -l -s'
