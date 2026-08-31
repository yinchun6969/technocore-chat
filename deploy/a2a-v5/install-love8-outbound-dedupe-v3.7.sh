#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SOURCE_REF="29d72c384722169edadb0a7f5839ace92d161a24"
SOURCE_SHA256="1b90877019b987dda96fc0edbf84ba77e4582d96dec56be61abcaacfbae12b2c"
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
for command in curl sha256sum python3 systemctl; do
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
systemctl is-active --quiet technocore-collab.service
grep -Fq '# LOVE8_OUTBOUND_DEDUPE_RETRY_V37' /opt/technocore-collab/bin/collab.py
grep -Fq "OUTBOUND_DEDUPE_UNAVAILABLE: retry later; no stage sent" /opt/technocore-collab/bin/collab.py

echo "LOVE8_OUTBOUND_V37_ACCEPTED=INSTALL_OK"
echo "service=active"
echo "next=start a new signed workflow; the failed invocation created no task"
