#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SOURCE_REF="a81f5310fdab2359880ab93d96c0e77037ea5edc"
SOURCE_SHA256="abe9ff6146d34c0e50d548e1a48479f56baf841662c204daa78d5b618e5d06da"
SOURCE_URL="https://raw.githubusercontent.com/yinchun6969/technocore-chat/$SOURCE_REF/deploy/a2a-v5/repair-aizong-cursor-poll-v3.6.py"
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

[[ $EUID -eq 0 ]] || die "run as root on Aizong Builder"
for command in curl sha256sum python3 systemctl; do
  command -v "$command" >/dev/null || die "$command is required"
done
[[ -f /opt/technocore-collab/bin/collab.py && -f /opt/technocore-collab/.env ]] || \
  die "existing Aizong collaboration sidecar not found"

stage="$(mktemp -d /root/tc-aizong-cursor-v36.XXXXXX)"
trap 'rm -rf "$stage"' EXIT
curl -fLsS --retry 5 --retry-delay 2 --connect-timeout 10 --max-time 120 \
  "$SOURCE_URL" -o "$stage/repair.py"
printf '%s  %s\n' "$SOURCE_SHA256" "$stage/repair.py" | sha256sum -c -
python3 -m py_compile "$stage/repair.py"
python3 "$stage/repair.py" --check

echo "AIZONG_CURSOR_V36_PREFLIGHT=PASS"
echo "source_ref=$SOURCE_REF"
echo "polling=cursor-aware-since+bounded-wait"
echo "preserved=did,private-key,mailbox,peers,cursor,nonces,provenance,workflow-history"
[[ $MODE == apply ]] || { echo "CHECK_ONLY: no files, services or state changed"; exit 0; }

python3 "$stage/repair.py" --apply
systemctl is-active --quiet technocore-collab.service
grep -Fq '# AIZONG_CURSOR_POLL_V36' /opt/technocore-collab/bin/collab.py
grep -Fq "params={'since':cursor,'wait':10" /opt/technocore-collab/bin/collab.py

echo "AIZONG_CURSOR_V36_ACCEPTED=INSTALL_OK"
echo "service=active"
echo "next=run a new signed workflow; do not manually complete or rewind the old task"
