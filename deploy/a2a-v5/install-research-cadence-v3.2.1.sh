#!/usr/bin/env bash
set -euo pipefail

# Immutable repair helper; never execute a moving branch download.
core_ref="7401649503d229bc8489d0aa1321b586169a2185"
core_sha256="a4b1f0ea139831ec4b6b1c024600488cd823d414359799b66457a9c3981abfb6"
config="/opt/technocore-a2a/.env"

if [[ $# != 0 ]]; then
  echo "No arguments accepted; this repair is only for an existing AI2AI v3.2 installation." >&2
  exit 2
fi
if [[ $(id -u) != 0 ]]; then
  echo "Run on AI2AI as root." >&2
  exit 2
fi
python3 - "$config" <<'PY'
import sys
from pathlib import Path
values = []
for line in Path(sys.argv[1]).read_text().splitlines():
    key, sep, value = line.partition('=')
    if sep and key.strip() == 'AGENT_NAME':
        values.append(value.strip())
if len(values) != 1 or values[0] not in ('ai2ai', '"ai2ai"', "'ai2ai'"):
    raise SystemExit('AI2AI configuration required; nothing changed')
PY

stage=$(mktemp -d /root/tc-a2a-cadence-v321-stage.XXXXXX)
trap 'if [[ -n "${stage:-}" && -d "$stage" ]]; then rm -r -- "$stage"; fi' EXIT
chmod 700 "$stage"
component="$stage/repair-research-cadence-v3.2.1.py"
curl -fL --retry 3 --retry-delay 2 --connect-timeout 10 --max-time 90 \
  "https://raw.githubusercontent.com/yinchun6969/technocore-chat/$core_ref/deploy/a2a-v5/repair-research-cadence-v3.2.1.py" \
  -o "$component"
printf '%s  %s\n' "$core_sha256" "$component" | sha256sum -c -
python3 -m py_compile "$component"
python3 -B "$component"
