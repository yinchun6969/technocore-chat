"""Offline regression tests. No credentials, services, posts or model API calls.

Run: python3 -m unittest discover -s deploy/a2a-v5 -p 'test_wire_room_v31.py' -v
Historical source fixtures are optional; pure regression tests always run.
"""

import ast
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from urllib.parse import quote


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("repair_v31", HERE / "repair-wire-room-v3.1.py")
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)
FIXTURES = HERE / "fixtures"


def namespace(block):
    value = {"json": json, "hashlib": hashlib, "DID": "did:key:" + "a" * 48,
             "MAILBOX": "mb-p-" + "0" * 32}
    exec(block, value)
    return value


class WireTests(unittest.TestCase):
    def setUp(self):
        self.ns = namespace(repair.WIRE_BLOCK)

    def test_small_payload_unchanged(self):
        expected = 'A2A1 ' + json.dumps(dict(v=1, type="ACK", task_id="wf-1",
            from_did=self.ns["DID"], reply_mailbox=self.ns["MAILBOX"], accepted=True),
            separators=(",", ":"), ensure_ascii=True)
        self.assertEqual(expected, self.ns["payload"]("ACK", "wf-1", accepted=True))

    def test_chinese_emoji_and_escaped_text(self):
        for text in ("中文问题" * 1000, "😀" * 4000, 'a\n"\\\t' * 4000, "X" * 9000):
            wire = self.ns["payload"]("CHALLENGE", "wf-1", goal=text,
                build_result=text, challenge=text, builder_did="did:key:builder",
                scout_did="did:key:scout", reviewer_did=self.ns["DID"])
            value = json.loads(wire[5:])
            self.assertLessEqual(len(wire.encode()), 3400)
            self.assertTrue(wire.isascii())
            self.assertEqual(value["builder_did"], "did:key:builder")
            self.assertEqual(value["task_id"], "wf-1")
            self.assertGreater(len(value["challenge"]), len(value["build_result"]))
            self.assertTrue(value["_wire"]["truncated"])
            self.assertEqual(len(value["_wire"]["original_sha256"]), 64)

    def test_primary_output_each_stage(self):
        for kind, field in [("RESULT", "result"), ("COMPLETE", "final_summary"),
                            ("BUILD_RESULT", "build_result"), ("REVISED_RESULT", "revised_result"),
                            ("SCHEDULER_REQUEST", "goal"), ("WORKFLOW_TASK", "goal")]:
            value = self.ns["payload"](kind, "task", **{field: "中文" * 5000})
            self.assertLessEqual(len(value.encode()), 3400)
            self.assertTrue(json.loads(value[5:])[field])

    def test_protected_fields_not_sliced(self):
        with self.assertRaises(ValueError):
            self.ns["payload"]("ACK", "x", from_did="spoof")
        with self.assertRaisesRegex(ValueError, "structural"):
            self.ns["payload"]("CHALLENGE", "x", builder_did="A" * 4000,
                               goal="中文" * 400, challenge="中文" * 400)

    def test_randomized_serialized_budget(self):
        rng = random.Random(31)
        alphabet = "中文😀\\\n\t\"abc é"
        for _ in range(100):
            texts = {key: ''.join(rng.choices(alphabet, k=rng.randrange(30, 3000)))
                     for key in ("goal", "build_result", "challenge")}
            wire = self.ns["payload"]("CHALLENGE", "wf-fixed", **texts)
            self.assertLessEqual(len(wire.encode()), 3400)
            self.assertEqual(json.loads(wire[5:])["task_id"], "wf-fixed")

    @unittest.skipUnless((FIXTURES / "upstream-wire-installer.sh").exists(), "historical fixture not installed")
    def test_old_guard_reproduces_the_failure(self):
        source = (FIXTURES / "upstream-wire-installer.sh").read_text()
        old = source.split("new=r'''", 1)[1].split("'''", 1)[0]
        args = dict(goal="中文" * 600, build_result="中文" * 900, challenge="中文" * 800)
        with self.assertRaisesRegex(ValueError, "too large after compaction") as caught:
            namespace(old)["payload"]("CHALLENGE", "wf-old", **args)
        new = self.ns["payload"]("CHALLENGE", "wf-old", **args)
        print("\nREPRO:", caught.exception, "->", len(new.encode()), "bytes; JSON valid")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls = []
        self.ns = {"json": json, "hashlib": hashlib, "STATE": Path(self.tmp.name),
                   "fcntl": fcntl, "os": os, "time": time, "AI_MODEL": "test-only",
                   "ai_call": lambda prompt: self.calls.append(prompt) or "完整审查结果" * 600}
        exec(repair.CACHE_BLOCK, self.ns)

    def test_retry_uses_saved_full_result(self):
        review = self.ns["workflow_cached_review_v31"]
        first = review("wf-1", "goal", "build")
        self.assertEqual(first, review("wf-1", "goal", "build"))
        self.assertEqual(len(self.calls), 1)
        cache = next(Path(self.tmp.name).glob('review-cache-v31-*.json'))
        self.assertEqual(json.loads(cache.read_text())["answer"], first)
        self.assertGreater(len(first), 1600)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o660)

    def test_changed_evidence_does_not_use_old_review(self):
        review = self.ns["workflow_cached_review_v31"]
        review("wf-1", "goal", "build")
        review("wf-1", "goal", "different build")
        self.assertEqual(len(self.calls), 2)

    def test_failed_model_call_does_not_cache_success(self):
        def fail(_):
            raise TimeoutError("simulated")
        self.ns["ai_call"] = fail
        with self.assertRaises(TimeoutError):
            self.ns["workflow_cached_review_v31"]("wf-1", "goal", "build")
        self.assertFalse(list(Path(self.tmp.name).glob('*.json')))


class Response:
    def __init__(self, code=200, text="ok", rows=None):
        self.status_code, self.text, self.rows = code, text, rows or []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("simulated HTTP error")

    def json(self):
        return {"messages": self.rows}


class RoomTests(unittest.TestCase):
    def setUp(self):
        self.state = {"active_request": {"request_id": "do-not-change"}, "daily": {"day": 1}}
        self.saved = []
        self.posts = []
        self.rows = []
        self.time = 1000
        self.room = "ai2ai"
        self.enabled = True
        self.cap = 8
        self.response = Response()
        self.logs = []
        self.signed = []
        self.nonces = []
        def reserve(room, floor):
            self.nonces.append((room, floor))
            return 123456 + floor
        def sign(value):
            self.signed.append(value)
            return "test-signature"
        self.ns = {"json": json, "hashlib": hashlib, "BASE": "https://example.invalid",
            "quote": quote, "AI2AI_DID": "did:key:ai2ai",
            "agent": types.SimpleNamespace(reserve_nonce=reserve, sign=sign),
            "discussion_room": lambda: self.room, "discussion_enabled": lambda: self.enabled,
            "now": lambda: self.time, "utc_day": lambda: "day",
            "number": lambda *args: self.cap,
            "clean": lambda value, limit: " ".join(str(value).split())[:limit],
            "public_room_text": lambda value: str(value).replace("\n", " ").strip(),
            "save_state": lambda state: self.saved.append(copy.deepcopy(state)),
            "log": self.log, "ledger": self.log,
            "requests": types.SimpleNamespace(get=lambda *a, **kw: Response(rows=self.rows), post=self.post)}
        exec(repair.ROOM_BLOCK, self.ns)

    def log(self, event, **fields):
        self.logs.append((event, fields))

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    def send(self, text="A real claim", event="topic_selected", key="topic:req-1"):
        return self.ns["discussion_post"](self.state, text, event, key)

    def test_success_checkpoint_deduplicates_and_preserves_state(self):
        self.assertTrue(self.send())
        self.assertFalse(self.send())
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.state["active_request"]["request_id"], "do-not-change")
        self.assertEqual(self.state["daily"], {"day": 1})
        self.assertEqual(self.state["discussion"]["outbox"], {})
        self.assertEqual(self.saved[-1]["discussion"]["last_delivery"], "http_accepted")
        self.assertEqual(self.signed, ["ai2ai|123456|A real claim"])
        self.assertFalse(self.posts[0][1]["allow_redirects"])
        self.assertTrue(any(fields.get("discussion_event") == "topic_selected" for _, fields in self.logs))

    def test_logging_exception_after_success_does_not_resend(self):
        def fail(*args, **kwargs):
            raise OSError("simulated log failure")
        self.ns["ledger"] = fail
        self.assertTrue(self.send())
        self.assertFalse(self.send())
        self.assertEqual(len(self.posts), 1)
        self.assertIn("ai2ai|topic:req-1", self.saved[-1]["discussion"]["posted"])

    def test_room_capacity_backoff_no_room_switch(self):
        self.response = Response(400, "400 room limit reached (20480 is the cap)")
        self.assertFalse(self.send())
        for _ in range(5):
            self.time += 90
            self.assertFalse(self.send())
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.state["discussion"]["daily"], {})
        self.assertEqual(self.room, "ai2ai")
        self.assertIn("room_capacity_full", self.state["discussion"]["last_error"])
        self.time = 2801
        self.response = Response()
        self.ns["flush_discussion_posts_v31"](self.state)
        self.assertEqual(len(self.posts), 2)
        self.assertEqual(self.state["discussion"]["outbox"], {})

    def test_unknown_post_outcome_requires_readback_not_blind_retry(self):
        self.response = TimeoutError("simulated post timeout")
        self.assertFalse(self.send())
        self.time += 130
        self.assertFalse(self.send())
        self.assertEqual(len(self.posts), 1)
        self.rows = [{"from": "did:key:ai2ai", "text": "A real claim", "nonce": "123456"}]
        self.time += 310
        self.assertTrue(self.send())
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(self.state["discussion"]["last_delivery"], "readback_verified")

    def test_old_intro_post_is_reconciled_without_duplicate(self):
        self.ns["ensure_discussion_room"](self.state)
        intro = self.posts[0][1]["json"]["text"]
        self.state = {"discussion": {"posted": {"room-intro-v1": 100}, "daily": {}}}
        self.posts.clear()
        self.rows = [{"from": "did:key:ai2ai", "text": intro, "nonce": "5"}]
        self.ns["ensure_discussion_room"](self.state)
        self.ns["ensure_discussion_room"](self.state)
        self.assertEqual(self.posts, [])
        self.assertTrue(self.state["discussion"]["intro_posted_at"])
        self.assertEqual(self.state["discussion"]["intro_room"], "ai2ai")

    def test_daily_room_cap_does_not_break_research_state(self):
        self.state["discussion"] = {"daily": {"day": 8}}
        self.assertFalse(self.send())
        self.assertEqual(self.posts, [])
        self.assertEqual(len(self.state["discussion"]["outbox"]), 1)
        self.assertEqual(self.state["active_request"]["request_id"], "do-not-change")

    def test_deduplication_scoped_to_room(self):
        self.assertTrue(self.send())
        self.room = "explicitly-changed-room"
        self.assertTrue(self.send())
        self.assertEqual(len(self.posts), 2)

    def test_foreign_sender_is_not_our_receipt(self):
        self.rows = [{"from": "did:key:stranger", "text": "A real claim", "nonce": 999999}]
        self.assertTrue(self.send())
        self.assertEqual(self.nonces, [("ai2ai", 0)])

    def test_disabled_no_posts_or_outbox(self):
        self.enabled = False
        self.assertFalse(self.send())
        self.assertEqual(self.posts, [])
        self.assertEqual(self.state["discussion"]["outbox"], {})

    def test_bad_read_never_posts(self):
        self.ns["requests"].get = lambda *a, **kw: Response(503)
        self.assertFalse(self.send())
        self.assertEqual(self.posts, [])

    def test_outbox_conflict_rejected(self):
        self.response = Response(429)
        self.assertFalse(self.send())
        with self.assertRaisesRegex(ValueError, "different content"):
            self.send(text="changed without a new key")


@unittest.skipUnless((FIXTURES / "upstream-director.py").exists(), "historical fixtures not installed")
class PatchTests(unittest.TestCase):
    def test_director_patch_is_idempotent_and_keeps_scheduling(self):
        source = (FIXTURES / "upstream-director.py").read_text()
        result = repair.patch_director(source)
        self.assertEqual(repair.patch_director(result), result)
        self.assertIn("flush_discussion_posts_v31(state)", result)
        for name in ("active_request", "observe_scheduler_delivery", "workflow_snapshot", "save_state"):
            self.assertEqual(ast.dump(repair.function_node(source, name)),
                             ast.dump(repair.function_node(result, name)))
        compile(result, "director", "exec")

    def test_agent_patch_preserves_trust_and_cursor_logic(self):
        base = (FIXTURES / "upstream-base-installer.sh").read_text()
        source = base.split('cat > "$ROOT_DIR/bin/agent.py" <<\'PY\'\n', 1)[1].split("\nPY\n", 1)[0]
        reviewer = (FIXTURES / "upstream-reviewer-installer.sh").read_text().split("block=r'''", 1)[1].split("'''", 1)[0]
        wire = (FIXTURES / "upstream-wire-installer.sh").read_text().split("new=r'''", 1)[1].split("'''", 1)[0]
        source = repair.replace_function(source, "payload", wire) + "\n" + reviewer
        result = repair.patch_agent(source)
        self.assertEqual(repair.patch_agent(result), result)
        for name in ("run", "handle_message", "trusted_sender", "signed_post", "reserve_nonce"):
            self.assertEqual(ast.dump(repair.function_node(source, name)),
                             ast.dump(repair.function_node(result, name)))
        self.assertIn("workflow_cached_review_v31(tid, goal, build)", result)
        compile(result, "agent", "exec")

    def test_unknown_sources_fail_without_writes(self):
        with self.assertRaises(ValueError):
            repair.patch_agent("print('unrecognized')\n")
        with self.assertRaises(ValueError):
            repair.patch_director("print('unrecognized')\n")


@unittest.skipUnless(os.geteuid() == 0 and (HERE / "install-wire-room-v3.1.sh").exists(),
                     "installer harness needs Linux root and installer source")
class InstallerTests(unittest.TestCase):
    """Run installer/rollback in an isolated fake filesystem with no network/systemd."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = self.root / "opt/technocore-a2a"
        for sub in ("bin", "rnd-v5", "state", "rnd-v5-state", "venv/bin"):
            (self.app / sub).mkdir(parents=True)
        (self.root / "root").mkdir()
        (self.root / "usr/local/bin").mkdir(parents=True)
        self.commands = self.root / "commands"
        self.commands.mkdir()
        self.agent = self.app / "bin/agent.py"
        self.director = self.app / "rnd-v5/autonomous-rnd-v5.py"
        self.agent.write_text("# original agent\n")
        self.director.write_text("# original director\n")
        self.agent.chmod(0o640)
        self.director.chmod(0o750)
        (self.app / ".env").write_text("AGENT_NAME=ai2ai\n")
        (self.app / "state/cursor.txt").write_text("6")
        (self.app / "state/workflow_seen.json").write_text('{"keep":123}')
        (self.app / "venv/bin/python").symlink_to(sys.executable)
        self.states = self.root / "services.json"
        self.initial = {"technocore-a2a.service": True, "technocore-a2a-rnd-v5.service": True}
        self.states.write_text(json.dumps(self.initial))
        self.rollback = self.root / "download-rollback.sh"
        self.rollback.write_text(self.map_paths((HERE / "rollback-wire-room-v3.1.sh").read_text()))
        self.patch = self.root / "download-patch.py"
        self.patch.write_text("import sys\nfrom pathlib import Path\n"
            "if '--apply' in sys.argv:\n"
            f"    for path in [Path({str(self.agent)!r}), Path({str(self.director)!r})]:\n"
            "        path.write_text(path.read_text() + '# patched\\n')\n")
        self.write_command("curl", "import sys,shutil,os\n"
            "args=sys.argv[1:]\n"
            "target=args[args.index('-o')+1]\n"
            "kind='TEST_PATCH' if any('repair-wire-room' in x for x in args) else 'TEST_ROLLBACK'\n"
            "shutil.copyfile(os.environ[kind],target)\n")
        self.write_command("sleep", "pass\n")
        # Model readability only; the harness never switches users or groups.
        self.write_command("runuser", "import sys,os\n"
            "a=sys.argv[1:]\n"
            "assert a[:4]==['-u','root','--','test'] and a[4]=='-r'\n"
            "raise SystemExit(0 if os.access(a[5],os.R_OK) else 1)\n")
        self.write_command("systemctl", "import sys,os,json\nfrom pathlib import Path\n"
            "p=Path(os.environ['TEST_SERVICES']); states=json.loads(p.read_text()); a=sys.argv[1:]\n"
            "if a[0]=='show':\n"
            "    print('root' if 'User' in a else 'loaded')\n"
            "elif a[0] in ('start','stop'):\n"
            "    if a[0]=='start' and os.environ.get('TEST_FAIL_START')=='1' and '# patched' in Path(os.environ['TEST_AGENT']).read_text():\n"
            "        raise SystemExit(1)\n"
            "    for s in a[1:]: states[s] = a[0]=='start'\n"
            "    p.write_text(json.dumps(states))\n"
            "elif a[0]=='is-active':\n"
            "    active=states.get(a[-1],False)\n"
            "    if '--quiet' not in a: print('active' if active else 'inactive')\n"
            "    raise SystemExit(0 if active else 3)\n"
            "else: raise SystemExit(2)\n")
        self.env = {**os.environ, "PATH": str(self.commands) + os.pathsep + os.environ["PATH"],
                    "TEST_PATCH": str(self.patch), "TEST_ROLLBACK": str(self.rollback),
                    "TEST_SERVICES": str(self.states), "TEST_AGENT": str(self.agent)}
        self.script = self.map_paths((HERE / "install-wire-room-v3.1.sh").read_text())
        # Replace only fixed-value assignment lines, regardless of final release pins.
        lines = self.script.splitlines()
        values = {"fix_source_ref": "test-commit", "fix_patch_sha": hashlib.sha256(self.patch.read_bytes()).hexdigest(),
                  "fix_rollback_sha": hashlib.sha256(self.rollback.read_bytes()).hexdigest()}
        self.script = '\n'.join(key + '=' + values[key] if (key := line.split('=', 1)[0]) in values else line for line in lines)

    def map_paths(self, text):
        for prefix in ("/root/", "/opt/", "/usr/local/"):
            text = text.replace(prefix, str(self.root) + prefix)
        return text

    def write_command(self, name, source):
        path = self.commands / name
        path.write_text('#!' + sys.executable + '\n' + source)
        path.chmod(0o700)

    def run_install(self):
        return subprocess.run(['bash'], input=self.script, text=True, env=self.env,
                              capture_output=True, timeout=20)

    def assert_preserved(self):
        self.assertEqual((self.app / "state/cursor.txt").read_text(), "6")
        self.assertEqual((self.app / "state/workflow_seen.json").read_text(), '{"keep":123}')
        self.assertEqual(json.loads(self.states.read_text()), self.initial)

    def test_install_and_manual_rollback(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('# patched', self.agent.read_text())
        self.assert_preserved()
        cli = self.root / "usr/local/bin/tc-a2a-wire-room-v31-rollback"
        result = subprocess.run(['bash', str(cli)], env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.agent.read_text(), '# original agent\n')
        self.assertEqual(self.director.read_text(), '# original director\n')
        self.assertEqual(self.agent.stat().st_mode & 0o777, 0o640)
        self.assertEqual(self.director.stat().st_mode & 0o777, 0o750)
        self.assert_preserved()

    def test_service_start_failure_rolls_back(self):
        self.env['TEST_FAIL_START'] = '1'
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ROLLBACK=COMPLETE', result.stdout, result.stdout + result.stderr)
        self.assertEqual(self.agent.read_text(), '# original agent\n')
        self.assertEqual(self.director.read_text(), '# original director\n')
        self.assert_preserved()

    def test_bad_download_checksum_never_changes_code(self):
        self.script = self.script.replace('fix_patch_sha=' + hashlib.sha256(self.patch.read_bytes()).hexdigest(),
                                          'fix_patch_sha=' + '0' * 64)
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.agent.read_text(), '# original agent\n')
        self.assert_preserved()

    def test_inactive_service_is_not_silently_started(self):
        self.initial['technocore-a2a.service'] = False
        self.states.write_text(json.dumps(self.initial))
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_preserved()


if __name__ == "__main__":
    unittest.main()
