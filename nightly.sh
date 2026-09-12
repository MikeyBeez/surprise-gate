#!/bin/sh
# The nightly consolidation pass. Installed in cron; see README.
#
# Two guards, both because this runs unattended on a box that does real work.
#
# A lock (mkdir, portable and atomic) so a slow pass cannot overlap the next
# night's and probe the same spool twice.
#
# A GPU check on UTILISATION, not memory. The first version of this script
# checked memory.used and would have skipped every single night: a resident
# llama-server holds ~15.8 GiB of a 16 GiB card permanently, so by that
# measure the GPU is never free. What matters is whether anything is running,
# and the whole point of this job is to use the card when nothing is.
# SG_FORCE=1 runs regardless.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
LOGDIR=${SG_LOGDIR:-$HOME/.surprise-gate}
mkdir -p "$LOGDIR"
LOG=$LOGDIR/consolidate.log
BUSY_PCT=${SG_BUSY_PCT:-25}
LOCK=$LOGDIR/nightly.lock.d

say() { echo "$(date -Is) $*" >> "$LOG"; }

if [ "${SG_FORCE:-}" != "1" ] && command -v nvidia-smi >/dev/null 2>&1; then
  # Three readings a few seconds apart: one sample catches an idle instant in
  # the middle of a busy run.
  peak=0
  for _ in 1 2 3; do
    u=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
    u=${u:-0}
    [ "$u" -gt "$peak" ] && peak=$u
    sleep 3
  done
  if [ "$peak" -gt "$BUSY_PCT" ]; then
    say "skip: GPU busy (peak ${peak}% > ${BUSY_PCT}%); the spool can wait"
    exit 0
  fi
  say "GPU idle (peak ${peak}%)"
fi

if mkdir "$LOCK" 2>/dev/null; then
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT INT TERM
  say "start"
  cd "$HERE"
  python3 consolidate.py >> "$LOG" 2>&1 || say "consolidate exited non-zero"
  say "done"
else
  say "skip: another pass holds the lock"
fi
