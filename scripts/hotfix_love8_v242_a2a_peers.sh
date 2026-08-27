#!/usr/bin/env bash
set -Eeuo pipefail
RAW="${REPO_RAW:-https://raw.githubusercontent.com/yinchun6969/technocore-chat/love8-social-v2}"
SOCIAL=/opt/love8-agent/social
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo '[x] use root'; exit 1; }
[[ -s "$SOCIAL/love8_deep_rooms_v242.py" ]] || { echo '[x] Love8 v2.4.2 not installed'; exit 1; }
echo '===== LOVE8 v2.4.2 A2A PEER HOTFIX ====='
curl -fsSL "$RAW/scripts/love8_a2a_peer_import_v2421.py" -o "$SOCIAL/love8_a2a_peer_import_v2421.py"
chmod 700 "$SOCIAL/love8_a2a_peer_import_v2421.py"
python3 -m py_compile "$SOCIAL/love8_a2a_peer_import_v2421.py"
cat >/usr/local/bin/love8-a2a-peers-repair <<'EOF'
#!/usr/bin/env bash
python3 /opt/love8-agent/social/love8_a2a_peer_import_v2421.py
rc=$?
echo
python3 /opt/love8-agent/social/love8_deep_rooms_v242.py --status
exit $rc
EOF
chmod 755 /usr/local/bin/love8-a2a-peers-repair
set +e
python3 "$SOCIAL/love8_a2a_peer_import_v2421.py"
RC=$?
set -e
echo
python3 "$SOCIAL/love8_deep_rooms_v242.py" --status
if [[ $RC -ne 0 ]]; then
  echo
  echo '[!] Auto-discovery still has fewer than 2 internal A2A peers.'
  echo '    The A2A v1 design stores the trusted group in /opt/technocore-a2a/strategy.json -> a2a.allowed_dids.'
  echo '    Add any missing controlled peer locally, without sending private keys:'
  echo "      love8-a2a-peer-add aizong 'did:key:...' 'mb-p-...'"
  echo "      love8-a2a-peer-add ai2ai 'did:key:...' 'mb-p-...'"
  echo '    Then run: love8-deep-rooms-run-now'
  exit 0
fi
echo
echo '[+] A2A peer threshold reached. Refresh attention and try first deep-room selection.'
love8-attention-refresh || true
love8-deep-rooms-dry-run || true
echo
echo 'If dry-run shows a room/topic/external candidate, run:'
echo '  love8-deep-rooms-run-now'
