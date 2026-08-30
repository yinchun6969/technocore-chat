from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from email.message import Message
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

import pytest

from tools import atlas_observer as observer
from tools.atlas_config import resolve_workflow_rooms
from tools.atlas_dashboard import dashboard_document
from tools.technocore_atlas import (
    WORKFLOW_SIGNERS,
    _a2a_metadata,
    _base_url,
    _is_public_room,
    collect_snapshot,
    fetch_json,
    snapshot_from_dict,
)

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def running_server(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def sample():
    return snapshot_from_dict(
        json.loads((ROOT / "examples/technocore-atlas.sample.json").read_text())
    )


@pytest.mark.parametrize(
    "room",
    ["p-secret", "mb-public", "d-e-p-secret", "e-d-mb-public", "e-mb-p-secret", "../x", "x?y"],
)
def test_observer_rejects_private_and_mailbox_classes(room):
    assert not _is_public_room(room)
    with pytest.raises(ValueError):
        collect_snapshot(
            "https://example.test",
            selected_rooms=(room,),
            fetcher=lambda *_: pytest.fail("network call"),
        )


def test_selected_room_is_read_even_when_not_in_recent_directory():
    calls = []

    def fetch(url, timeout):
        calls.append(url)
        return {"messages": [], "last_seq": 0}

    snapshot = collect_snapshot(
        "https://example.test", selected_rooms=("yinchun-a2a-rnd-v5",), fetcher=fetch
    )
    assert len(calls) == 1
    assert "/r/yinchun-a2a-rnd-v5?" in calls[0]
    assert snapshot.rooms[0].name == "yinchun-a2a-rnd-v5"


def test_malformed_room_is_counted_as_failure():
    snapshot = collect_snapshot(
        "https://example.test", selected_rooms=("lobby",), fetcher=lambda *_: {"unexpected": []}
    )
    assert not snapshot.rooms and snapshot.collection_errors == 1


@pytest.mark.parametrize(
    "origin",
    [
        "https://user:password@example.test",
        "https://example.test/r/lobby/say/x/y",
        "https://example.test?q=1",
    ],
)
def test_origin_is_not_a_write_route_or_credential_container(origin):
    with pytest.raises(ValueError):
        _base_url(origin)


def test_scheduler_type_is_observable_without_executing_it():
    assert _a2a_metadata('A2A1 {"type":"SCHEDULER_REQUEST","task_id":"sched-1"}') == (
        "SCHEDULER_REQUEST",
        "sched-1",
    )


def test_config_resolves_only_required_pinned_workflow_rooms(tmp_path):
    peers = tmp_path / "peers.json"
    peers.write_text(
        json.dumps(
            {
                WORKFLOW_SIGNERS["WORKFLOW_TASK"]: "mb-p-" + "a" * 32,
                WORKFLOW_SIGNERS["BUILD_RESULT"]: "mb-p-" + "b" * 32,
                "did:key:unrelated": "mb-p-" + "c" * 32,
                "api_key": "must-not-be-read",
            }
        )
    )
    assert resolve_workflow_rooms(peers) == (
        "d-aizong",
        "mb-p-" + "a" * 32,
        "mb-p-" + "b" * 32,
    )


def test_config_deduplicates_existing_aizong_fallback_route(tmp_path):
    peers = tmp_path / "peers.json"
    peers.write_text(
        json.dumps(
            {
                WORKFLOW_SIGNERS["WORKFLOW_TASK"]: "mb-p-" + "a" * 32,
                WORKFLOW_SIGNERS["BUILD_RESULT"]: "d-aizong",
            }
        )
    )
    assert resolve_workflow_rooms(peers) == ("d-aizong", "mb-p-" + "a" * 32)


def test_dashboard_is_mobile_html_and_escapes_workflow_content():
    raw = sample().to_dict()
    raw.update(
        schema="technocore-atlas/v2",
        workflows=[
            {
                "task_id": "wf-mobile-1",
                "status": "active",
                "current_stage": "CHALLENGE",
                "started_at": "2026-08-29T02:20:00Z",
                "updated_at": "2026-08-29T02:22:00Z",
                "conflicts": 0,
                "stages": [
                    {
                        "kind": "CHALLENGE",
                        "seq": 3,
                        "ts": "2026-08-29T02:22:00Z",
                        "agent": "AI2AI",
                        "role": "Reviewer",
                        "content_field": "challenge",
                        "content": "核对 <script>alert(1)</script> 与反例",
                        "content_truncated": False,
                        "text_sha256": "a" * 64,
                    }
                ],
            }
        ],
    )
    raw["summary"]["workflows_observed"] = 1
    state = {"snapshot": raw}
    body = dashboard_document(state, {"status": "ok"}).decode()
    assert '<meta name="viewport"' in body
    assert "TECHNOCORE // PIXEL QUEST" in body
    assert 'fetch("/atlas.json"' in body
    assert "setInterval(refresh,10000)" in body
    assert '<canvas id="world"' in body
    assert '<svg class="brand-mark" viewBox="0 0 100 132"' in body
    assert 'class="logo-white"' in body and 'class="logo-cut"' in body
    assert 'class="logo-cyan"' in body and '#14bee1' in body
    assert "technocore" in body and "Atlas v3.6" in body
    assert 'navy="#081631",cyan="#20e2f2",white="#f7f8ff"' in body
    assert 'px(x+5,fy,58,34,"#ff5b5b")' not in body
    assert "const STEP_MS=7600,MOVE_END=.36,WORK_END=.76" in body
    assert 'phase=progress<MOVE_END?"move":progress<WORK_END?"work":"handoff"' in body
    assert 'document.getElementById("replay").addEventListener("click",beginReplay)' in body
    assert 'id="language"' in body
    assert 'localStorage.setItem("atlas-language",lang)' in body
    assert 'navigator.language?.toLowerCase().startsWith("zh")' in body
    assert 'Agent Relay Workflow Observer' in body
    assert 'Signed original' in body
    assert 'applyLanguage(lang,false)' in body
    assert 'id="focus"' in body and 'id="progress-fill"' in body
    assert 'role="progressbar"' in body
    assert 'document.documentElement.requestFullscreen?.()' in body
    assert 'screen.orientation?.lock?.("landscape")' in body
    assert 'document.addEventListener("fullscreenchange"' in body
    assert "updateProgress(journey)" in body
    assert "Signed handoff" in body and "签名交接" in body
    assert "Signed & observed" in body and "Awaiting signature" in body
    assert "Not observed" in body and "does not prove failure" in body
    assert "Signed original (source language, unchanged)" in body
    assert "const homes={Love8:70,Aizong:250,AI2AI:430}" in body
    assert "present.size/order.length" in body
    assert 'const bubbleCopy=lang==="en"?actions[kind]' in body
    assert "S.replayStart+=held" in body
    assert "签名交接" in body and "Scout/Gate" in body
    assert "wf-mobile-1" in body and "审查挑战" in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "<script>alert(1)</script>" not in body
    assert "innerHTML" not in body


def test_redirect_to_write_route_is_never_followed():
    hits = []

    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/r/lobby/say/nick/write")
            self.end_headers()

        def log_message(self, format, *args):
            pass

    with running_server(Redirect) as base:
        with pytest.raises(HTTPError):
            fetch_json(base + "/rooms", timeout=2)
    assert hits == ["/rooms"]


def test_failed_refresh_preserves_snapshot_and_hides_error_details(tmp_path):
    path = tmp_path / "state.json"
    assert observer.refresh(path, collector=lambda *a, **k: sample()) == 0
    before = observer.load_state(path)

    def failure(*args, **kwargs):
        raise OSError("https://secret.invalid/private?token=hidden")

    assert observer.refresh(path, collector=failure) == 1
    after = observer.load_state(path)
    assert after["snapshot"] == before["snapshot"]
    assert after["last_success"] == before["last_success"]
    assert observer.status(after)["status"] == "degraded"
    assert "hidden" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".atlas-*"))


def test_refresh_exposes_only_sanitized_http_error_code(tmp_path, monkeypatch):
    def unavailable(url, timeout):
        raise HTTPError(url, 503, "secret details", Message(), None)

    monkeypatch.setattr(observer, "fetch_json", unavailable)
    path = tmp_path / "state.json"
    assert observer.refresh(path) == 1
    state = observer.load_state(path)
    assert state["error_code"] == "HTTP_503"
    assert "secret" not in path.read_text()


def test_no_sample_is_substituted_on_first_failure(tmp_path):
    path = tmp_path / "state.json"
    empty = sample().to_dict()
    empty["rooms"] = []
    assert observer.refresh(path, collector=lambda *a, **k: snapshot_from_dict(empty)) == 1
    state = observer.load_state(path)
    assert "snapshot" not in state
    assert observer.status(state)["status"] == "waiting"
    assert b"WAITING" in observer.svg_document(state)


def test_stale_and_current_graphs_are_valid_svg(tmp_path):
    path = tmp_path / "state.json"
    observer.refresh(path, collector=lambda *a, **k: sample())
    state = observer.load_state(path)
    assert observer.status(state)["status"] == "ok"
    ElementTree.fromstring(observer.svg_document(state))
    state["last_success_epoch"] = 1
    assert observer.status(state, now=10000)["stale"]
    assert b"STALE" in observer.svg_document(state)
    ElementTree.fromstring(observer.svg_document(state))


def test_allowlisted_http_routes_no_file_access_and_no_writes(tmp_path):
    path = tmp_path / "state.json"
    observer.refresh(path, collector=lambda *a, **k: sample())
    before = path.read_bytes()
    with running_server(observer.make_handler(path)) as base:
        with urlopen(base + "/", timeout=2) as response:
            assert response.headers.get_content_type() == "text/html"
            policy = response.headers["Content-Security-Policy"]
            assert "script-src 'unsafe-inline'" in policy
            assert "connect-src 'self'" in policy
            assert b"PIXEL QUEST" in response.read()
        with urlopen(base + "/atlas.svg", timeout=2) as response:
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
            ElementTree.fromstring(response.read())
        with urlopen(base + "/atlas.json", timeout=2) as response:
            assert json.load(response)["observation"]["status"] == "ok"
        for route in ["/observer.json", "/.env", "/../../etc/passwd", "/r/lobby/say/x/y"]:
            with pytest.raises(HTTPError) as error:
                urlopen(base + route, timeout=2)
            assert error.value.code == 404
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/status.json", headers={"Host": "evil.test"}), timeout=2)
        assert error.value.code == 403
        with pytest.raises(HTTPError) as error:
            urlopen(Request(base + "/", data=b"write"), timeout=2)
        assert error.value.code == 405
    assert path.read_bytes() == before


def test_corrupt_state_returns_service_unavailable(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("invalid JSON")
    with running_server(observer.make_handler(path)) as base:
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/status.json", timeout=2)
        assert error.value.code == 503


def test_install_check_does_not_write_or_change_units(tmp_path):
    if os.geteuid() != 0:
        pytest.skip("installer preflight requires root; no install is performed")
    log = tmp_path / "calls"
    systemctl = tmp_path / "systemctl"
    systemctl.write_text(
        '#!/bin/bash\nprintf "%s\\n" "$*" >> "$ATLAS_TEST_CALLS"\n'
        'case "$1" in\n show-environment|is-active) exit 0;;\n show) echo not-found;;\n *) exit 90;;\n esac\n'
    )
    systemctl.chmod(0o755)
    peers = tmp_path / "peers.json"
    peers.write_text(
        json.dumps(
            {
                WORKFLOW_SIGNERS["WORKFLOW_TASK"]: "mb-p-" + "a" * 32,
                WORKFLOW_SIGNERS["BUILD_RESULT"]: "mb-p-" + "b" * 32,
            }
        )
    )
    env = dict(
        os.environ,
        PATH=f"{tmp_path}:{os.environ['PATH']}",
        ATLAS_TEST_CALLS=str(log),
        ATLAS_PEERS_FILE=str(peers),
    )
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/atlas/install.sh"), "--check", "--room", "atlas-test"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "CHECK_ONLY" in result.stdout
    assert "start" not in log.read_text()
    assert not Path("/opt/technocore-atlas").exists()


def test_installer_resolves_current_identity_room_without_env_or_keys():
    script = (ROOT / "deploy/atlas/install.sh").read_text()
    assert "/opt/technocore-a2a/rnd-v5-state/identity-room-name" in script
    assert "95-identity-room-v520.conf" in script
    assert "/opt/technocore-a2a/.env" not in script
    assert "Cannot establish the current v5 identity room" in script


def test_units_are_separate_and_web_is_read_only():
    folder = ROOT / "deploy/atlas"
    for name in ("technocore-atlas-refresh.service", "technocore-atlas-web.service"):
        text = (folder / name).read_text()
        assert "DynamicUser=yes" in text and "ProtectSystem=strict" in text
        assert "InaccessiblePaths=-/opt/technocore-a2a -/opt/technocore-collab" in text
        assert "EnvironmentFile=/opt/" not in text
    web = (folder / "technocore-atlas-web.service").read_text()
    assert "ReadOnlyPaths=/var/lib/technocore-atlas" in web
    assert "IPAddressDeny=any" in web


def test_v2_upgrade_is_atlas_only_and_keeps_automatic_backup():
    script = (ROOT / "deploy/atlas/upgrade-v2.sh").read_text()
    assert "v1-to-v2-" in script and "BACKUP=" in script
    assert "technocore-a2a-rnd-v5.service" in script
    assert "systemctl restart technocore-a2a-rnd-v5.service" not in script
    assert "technocore-collab.service" not in script
    assert "A2A/TG not restarted" in script


def test_v3_upgrade_changes_only_atlas_ui_and_keeps_versioned_backup():
    script = (ROOT / "deploy/atlas/upgrade-v3.sh").read_text()
    assert "v2-to-v3" in script and "v3-to-v3.6" in script and "BACKUP=" in script
    assert "tools/atlas_dashboard.py" in script and "tools/atlas_observer.py" in script
    assert "technocore-a2a-rnd-v5.service" in script
    assert "systemctl restart technocore-a2a-rnd-v5.service" not in script
    assert "technocore-collab.service" not in script
    assert "A2A/TG not restarted" in script
    assert "wait_for_dashboard 'TECHNOCORE // PIXEL QUEST'" in script
    assert 'wait_for_dashboard "$ROLLBACK_MARKER"' in script
    assert "$PREVIOUS_RELEASE restored and listening" in script
    assert "install -d -m 0755 /opt/technocore-atlas" in script
    assert "import tools.atlas_observer" in script
    assert "ATLAS_V3_CURRENT_RELEASE_ALREADY_INSTALLED" in script
