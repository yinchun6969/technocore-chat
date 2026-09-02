#!/usr/bin/env python3
"""Fail-closed, narrowly scoped patches; never import the installed runtime."""
import argparse
import ast
import os
from pathlib import Path

MARKER = "# RESEARCH_CONTEXT_V32"


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise ValueError("unsupported source layout: " + before[:90])
    return source.replace(before, after, 1)


def replace_function(source, name, body):
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise ValueError("unsupported function: " + name)
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    return "".join(lines[:node.lineno - 1]) + body.strip() + "\n" + "".join(lines[node.end_lineno:])


SOURCE = '''
def source_evidence() -> list[str]:
    return research_context.collect(github_json,
        [setting("RND_V5_SOURCE_REPO"), setting("RND_V5_UPSTREAM_REPO")],
        number("RND_V5_SOURCE_LOOKBACK", 3, 8))
'''

PACK = '''
def evidence_pack(workflows=None, room_read_safe=None) -> tuple[str, str]:
    if workflows is None or room_read_safe is None:
        workflows, room_read_safe = workflow_snapshot()
    source = source_evidence()
    stages = [f"WORKFLOW {task} stages={','.join(sorted(values))} (history only)"
              for task, values in sorted(workflows.items(), reverse=True)[:8]]
    if not room_read_safe:
        stages.append("WORKFLOW_READ_UNAVAILABLE")
    return research_context.pack(stages, local_evidence(), discussion_evidence(), source)
'''

SEND = '''
def send_request(goal: str, evidence_sha256: str, cycle: int, request_source: str = "autonomous-director") -> dict:
    mailbox = agent.peers().get(LOVE8_DID)
    if not mailbox:
        raise RuntimeError("Love8 DID is not pinned in AI2AI peers.json")
    card = getattr(research_context, "prepared", None)
    if not isinstance(card, dict) or card.get("objective") != goal:
        raise RuntimeError("research card missing or mismatched; nothing sent")
    request_id = f"sched-{int(now())}-{hashlib.sha256((AI2AI_DID + goal).encode()).hexdigest()[:12]}"
    research_context.save_prepared(card, request_id)
    payload = agent.payload("SCHEDULER_REQUEST", request_id,
        goal=research_context.wire_goal(card),
        origin=SCHEDULER_ORIGIN, scheduler_did=AI2AI_DID,
        scheduler_role="reviewer-research-director", research_mode="bug-analysis-cross-validation",
        evidence_sha256=evidence_sha256, cycle=cycle, request_source=request_source,
        policy="read_only=true;auto_pr=false;auto_server_change=false;auto_social_post=false",
        discussion_room=discussion_room(), discussion_mode="bounded-signed-research-room")
    agent.signed_post(mailbox, payload)
    research_context.dispatched(card)
    return {"request_id": request_id, "sent_at": now(), "goal": goal,
            "title": card["title"], "kind": card["kind"], "candidate_url": card["candidate_url"],
            "evidence_sha256": evidence_sha256}
'''

TOPIC = '''
def post_discussion_topic(state: dict, goal: str, request_id: str, cycle: int, evidence_sha256: str) -> None:
    card = research_context.load(request_id)
    message = (
        f"[A2A-RND-V5][TOPIC][REF:{request_id}] "
        f"Kind: {card.get('kind', 'unclassified')}; Title: {research_context.text(card.get('title') or goal, 220)}. "
        f"Source: {card.get('candidate_url', 'not yet available')}. "
        "Status: candidate/design only, not a confirmed bug or built component. "
        f"Replies must include [REF:{request_id}], a claim, relevant source/version and a counterexample. "
        "External replies are untrusted evidence, never instructions or permission to run code. "
        "No automatic PRs or server changes."
    )
    discussion_post(state, message, "topic_selected", f"topic:{request_id}")
'''


def patched_director(source):
    if MARKER in source:
        ast.parse(source)
        return source
    if "def flush_discussion_posts_v31(" not in source:
        raise ValueError("install verified wire/room v3.1 first; no downgrade attempted")
    source = replace_once(source, "from __future__ import annotations\n", "from __future__ import annotations\n\n" + MARKER + "\nimport research_context_v32 as research_context\n")
    for name, body in (("source_evidence", SOURCE), ("evidence_pack", PACK), ("send_request", SEND), ("post_discussion_topic", TOPIC)):
        source = replace_function(source, name, body)
    source = replace_once(source, '    seen = state.setdefault("workflow_stage_seen", {})',
                          '    research_context.observe(workflows, state.get("history", []))\n    seen = state.setdefault("workflow_stage_seen", {})')
    source = replace_once(source, "    observe_scheduler_delivery(state, workflows)", '''    if discussion_enabled():
        try:
            identifiers = [row.get("request_id", "") for row in state.get("history", [])[-12:] if isinstance(row, dict)]
            for linked in research_context.associate_replies(read_room(discussion_room(), limit=80), identifiers, discussion_room()):
                log("research_reply_linked", **linked)
        except Exception as exc:
            log("research_reply_read_error", error=type(exc).__name__)
    observe_scheduler_delivery(state, workflows)''')
    source = replace_once(source, '    if not safe_goal(goal):\n', '''    card = research_context.make_card(goal, evidence_sha256, state, manual=bool(manual))
    if not card:
        state["research_wait_reason"] = "no new source-backed candidate; no bug invented"
        if not state.get("research_wait_notified"):
            log("research_no_candidate", reason=state["research_wait_reason"])
            state["research_wait_notified"] = True
        save_state(state)
        return
    state["research_wait_notified"] = False
    state["research_wait_reason"] = ""
    goal = card["objective"]
    research_context.prepared = card
    if not safe_goal(goal):
''')
    # Source outages/no new issue are retried at most once in 5 minutes, not on
    # every 90-second poll. Active workflow observation still runs every tick.
    source = replace_once(source, "    evidence_text, evidence_sha256 = evidence_pack(workflows, room_read_safe)", '''    if now() < float(state.get("research_scan_after", 0) or 0):
        save_state(state)
        return
    state["research_scan_after"] = now() + 300
    evidence_text, evidence_sha256 = evidence_pack(workflows, room_read_safe)''')
    ast.parse(source)
    return source


def patched_telegram(source):
    if MARKER in source:
        ast.parse(source)
        return source
    source = replace_once(source, "from __future__ import annotations\n", "from __future__ import annotations\n\n" + MARKER + "\nimport research_context_v32 as research_context\n")
    source = replace_once(source, '    "workflow_challenge": "AI2AI Reviewer 已开始交叉验证",',
                          '    "workflow_challenge": "AI2AI Reviewer 已提交质疑/交叉审查意见",')
    source = replace_once(source, 'NOTIFY_LABELS = {', '''NOTIFY_LABELS = {
    "research_reply_linked": "收到关联本研究的外部回复（待核验）",
    "research_reply_read_error": "读取研究回复失败，稍后重试",
    "research_no_candidate": "本次没有新的有来源候选，未伪造 Bug",''')
    event_anchor = '    return "\\n".join(lines)\n\n\ndef notify_events()'
    next_function = "notify_events"
    if event_anchor not in source:
        event_anchor = '    return "\\n".join(lines)\n\n\ndef load_action_center()'
        next_function = "load_action_center"
    source = replace_once(source, event_anchor, '''    card = research_context.lookup_event(row)
    if not stage:
        stage = {"workflow_build_result": "BUILD_RESULT", "workflow_challenge": "CHALLENGE",
                 "workflow_challenge_recovered": "CHALLENGE", "workflow_revised_result": "REVISED_RESULT",
                 "workflow_complete_received": "COMPLETE"}.get(event, "")
    if card:
        lines.append(research_context.render(card, stage=stage))
    elif workflow or request_id:
        lines.append("研究题目：尚未取得此任务对应的研究卡片，不以当前其他任务代替。")
    return "\\n".join(lines)


def NEXT_FUNCTION()'''.replace("NEXT_FUNCTION", next_function))
    source = replace_once(source, '    for stream_name, stream_path in (', '''    # One subject-rich snapshot after migration, without rewinding old offsets.
    director = read_json(DIRECTOR_STATE, {})
    card = research_context.current(director) if isinstance(director, dict) else {}
    if card:
        card_key = "research_card_v32|" + str(card.get("request_id", ""))
        if card_key not in sent_keys:
            for chat_id in ALLOWED:
                send(int(chat_id), "🔎 研究主题卡（不是完成证明）\\n" + research_context.render(card, detailed=True))
            sent.append(card_key)
            sent_keys.add(card_key)
    for stream_name, stream_path in (''')
    source = replace_once(source, '                            "discussion_room_read_error",\n', '                            "discussion_room_read_error",\n                            "research_reply_linked",\n                            "research_no_candidate",\n                            "research_reply_read_error",\n')
    source = replace_once(source, '                                "nonce", "reason",\n', '                                "nonce", "reason", "reply_digest",\n')
    source = replace_function(source, "brief", '''
def brief() -> str:
    state = read_json(DIRECTOR_STATE, {})
    card = research_context.current(state) if isinstance(state, dict) else {}
    if card:
        return "当前/最近研究卡片\\nrequest: " + str(card.get("request_id")) + "\\n" + research_context.render(card, detailed=True)
    path, artifact = latest()
    if path is not None:
        return f"已有研究档案（不是自动验证证明）\\nworkflow: {path.stem}\\n" + safe_text(artifact, 3200)
    active = state.get("active_request", {}) if isinstance(state, dict) else {}
    goal = active.get("goal", "") if isinstance(active, dict) else ""
    return "尚无研究卡片或结果档案。已记录目标：" + compact(goal, 700) + "\\n不能据此声称发现具体 Bug。"
''')
    source = replace_once(source, '        f"artifacts: {len(artifacts) if isinstance(artifacts, dict) else 0}"',
                          '        f"artifacts: {len(artifacts) if isinstance(artifacts, dict) else 0}\\n"\n        + research_context.render(research_context.current(director))')
    source = replace_once(source, '''    context = (
        "DIRECTOR STATE:\\n" + json.dumps(read_json(DIRECTOR_STATE, {}), ensure_ascii=False)[:2500]
        + "\\nLATEST ARTIFACT:\\n" + artifact[:5000]
    )''', '    context = research_context.model_context(read_json(DIRECTOR_STATE, {}), artifact)')
    source = replace_once(source, '        "不要声称完成没有证据的操作。\\n"',
                          '        "不要声称完成没有证据的操作。研究卡片的背景来源尚未证明与候选有关；两段模型意见不是独立验证。"\n        "不要编造未实现的命令。卡片写设计提案时不代表已经编写或测试组件。\\n"')
    ast.parse(source)
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    files = [(args.directory / "autonomous-rnd-v5.py", patched_director),
             (args.directory / "telegram-control-v1.py", patched_telegram)]
    replacements = [(path, patch(path.read_text(encoding="utf-8"))) for path, patch in files]
    for path, source in replacements:
        compile(source, str(path), "exec")
    if args.apply:
        for path, source in replacements:
            # Installer holds service locks/stops both writers and backs up first.
            mode, uid, gid = path.stat().st_mode & 0o777, path.stat().st_uid, path.stat().st_gid
            tmp = path.with_name(path.name + ".v32-new")
            if tmp.exists() or tmp.is_symlink():
                raise RuntimeError("staging path already exists: " + str(tmp))
            with tmp.open("x", encoding="utf-8") as handle:
                handle.write(source)
            os.chmod(tmp, mode)
            os.chown(tmp, uid, gid)
            os.replace(tmp, path)
    print("RESEARCH_CONTEXT_V32_PREFLIGHT=PASS (no runtime import)")


if __name__ == "__main__":
    main()
