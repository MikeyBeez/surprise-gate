#!/bin/sh
# Every test here stubs the model. Nothing in this suite needs a GPU or a server.
set -e
cd "$(dirname "$0")"
fail=0
for t in test_*.py; do
  python3 "$t" 2>&1 | tail -3 | sed "s|^|$t: |" || fail=1
done
exit $fail
