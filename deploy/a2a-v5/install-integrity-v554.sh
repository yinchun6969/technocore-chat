#!/usr/bin/env bash
# Local immutable-checkout entry. Never pipe an installer into a login shell.
set -euo pipefail
[[ "$(id -u)" == 0 ]] || { echo 'Run as root on AI2AI' >&2; exit 2; }
case "${1:---check}" in
  --check|--install) TC_MODE="${1:---check}" ;;
  *) echo 'usage: bash install-integrity-v554.sh [--check|--install]' >&2; exit 2 ;;
esac
TC_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$TC_DIR"
sha256sum -c integrity-v554.sha256
TC_TEST_LOG="$TC_DIR/offline-self-test.log"
if python3 -B -m unittest -q test_integrity_v554.py >"$TC_TEST_LOG" 2>&1; then
  echo 'OFFLINE_SELF_TEST=PASS; production installation has not started'
else
  cat "$TC_TEST_LOG"
  echo 'OFFLINE_SELF_TEST=FAIL; no production changes' >&2
  exit 1
fi
python3 -B - "$TC_DIR" <<'PY'
import importlib.util
import re
import sys
from pathlib import Path
stage = Path(sys.argv[1])
config = Path('/opt/technocore-a2a/.env').read_text()
roles = re.findall(r'^AGENT_NAME\s*=\s*[\'\"]?([a-zA-Z0-9_-]+)[\'\"]?\s*$', config, re.M)
if roles != ['ai2ai']:
    raise SystemExit('AI2AI only; no changes made')
spec = importlib.util.spec_from_file_location('repair554', stage / 'repair-integrity-v554.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)
base = Path('/opt/technocore-a2a/rnd-v5')
for name, transform in [('autonomous-rnd-v5.py', repair.director),
                        ('telegram-control-v1.py', repair.telegram),
                        ('human_action_center_v1.py', repair.actions)]:
    compile(transform((base / name).read_text()), name, 'exec')
print('INTEGRITY_V554_PREFLIGHT=PASS; no production changes yet')
PY
if [[ "$TC_MODE" == --install ]]; then
  [[ "$(id -u)" == 0 ]] || { echo 'Run install as root on AI2AI' >&2; exit 2; }
  python3 -B "$TC_DIR/deploy-integrity-v554.py" --install "$TC_DIR"
fi
