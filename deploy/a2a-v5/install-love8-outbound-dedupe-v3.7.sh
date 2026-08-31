#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SOURCE_REF="808a903bf68154ad17812e9d806a0a30e82e5c53"
SOURCE_SHA256="502cbab3132c3c5ec825bbd981b27002a85075e0a2884e37baa98df0b61ef655"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5/repair-love8-outbound-dedupe-v3.7.py"
MODE="check"

die() { echo "ERROR: $*" >&2; exit 1; }
while (($#)); do
  case "$1" in
    --check) MODE="check" ;;
    --apply) MODE="apply" ;;
    *) die "usage: $0 --check | --apply" ;;
  esac
  shift
done

[[ $EUID -eq 0 ]] || die "run as root on Love8 Scout"
for command in curl sha256sum python3; do
  command -v "$command" >/dev/null || die "$command is required"
done
[[ -f /opt/technocore-collab/bin/collab.py && -f /opt/technocore-collab/.env ]] || \
  die "existing Love8 collaboration sidecar not found"

stage="$(mktemp -d /root/tc-love8-outbound-v37.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
curl -fLsS --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
  "$SOURCE_URL" -o "$stage/repair.py"
printf '%s  %s\n' "$SOURCE_SHA256" "$stage/repair.py" | sha256sum -c -
python3 -m py_compile "$stage/repair.py"
python3 "$stage/repair.py" --check

echo "LOVE8_OUTBOUND_V37_PREFLIGHT=PASS"
echo "source_ref=$SOURCE_REF"
echo "dedupe_read=retry-429-5xx-network; attempts=5; fail_closed=true"
echo "preserved=did,private-key,mailbox,peers,cursor,nonces,provenance,workflow-history"
[[ $MODE == apply ]] || { echo "CHECK_ONLY: no files, services or state changed"; exit 0; }

python3 "$stage/repair.py" --apply
if command -v systemctl >/dev/null 2>&1 && \
   [[ "$(systemctl show -p LoadState --value technocore-collab.service 2>/dev/null || true)" == loaded ]]; then
  systemctl is-active --quiet technocore-collab.service
  runtime=systemd
elif command -v tc-collab-process-status >/dev/null 2>&1 && \
     tc-collab-process-status | grep -q 'runner: ACTIVE'; then
  runtime=process-runner
else
  die "Love8 runtime is not active after repair"
fi
grep -Fq '# LOVE8_OUTBOUND_DEDUPE_RETRY_V37' /opt/technocore-collab/bin/collab.py
grep -Fq "OUTBOUND_DEDUPE_UNAVAILABLE: retry later; no stage sent" /opt/technocore-collab/bin/collab.py

echo "LOVE8_OUTBOUND_V37_ACCEPTED=INSTALL_OK"
echo "runtime=$runtime; active=true"
echo "next=start a new signed workflow; the failed invocation created no task"
