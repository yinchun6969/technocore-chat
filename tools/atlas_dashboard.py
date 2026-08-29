#!/usr/bin/env python3
"""Server-rendered, mobile-first Atlas v2 workflow dashboard."""

from __future__ import annotations

from html import escape
from typing import Any

from tools.technocore_atlas import (
    WORKFLOW_AGENTS,
    WORKFLOW_STAGE_ORDER,
    Snapshot,
    WorkflowStage,
    WorkflowTrace,
    snapshot_from_dict,
)

STAGE_LABELS = {
    "WORKFLOW_TASK": "创建任务",
    "BUILD_RESULT": "初步分析",
    "CHALLENGE": "交叉质疑",
    "REVISED_RESULT": "修订结果",
    "COMPLETE": "最终总结",
}
AGENT_DESCRIPTIONS = {
    "Love8": "Scout · 分派与汇总",
    "Aizong": "Builder · 分析与修订",
    "AI2AI": "Reviewer · 质疑与核验",
}


def _h(value: Any) -> str:
    return escape(str(value), quote=True)


def _time(value: str) -> str:
    return value.replace("T", " ").removesuffix("Z") + (" UTC" if value else "")


def _latest_by_agent(snapshot: Snapshot) -> dict[str, WorkflowStage]:
    latest: dict[str, WorkflowStage] = {}
    for workflow in snapshot.workflows:
        for stage in workflow.stages:
            previous = latest.get(stage.agent)
            if previous is None or (stage.ts, stage.seq or -1) > (
                previous.ts,
                previous.seq or -1,
            ):
                latest[stage.agent] = stage
    return latest


def _agent_cards(snapshot: Snapshot) -> str:
    latest = _latest_by_agent(snapshot)
    cards: list[str] = []
    for agent in ("Love8", "Aizong", "AI2AI"):
        stage = latest.get(agent)
        if stage:
            activity = f"最近阶段：{STAGE_LABELS[stage.kind]}"
            when = _time(stage.ts) or "时间未知"
            state_class = "observed"
        else:
            activity = "尚未观察到签名阶段"
            when = "不代表 Agent 离线"
            state_class = "unknown"
        cards.append(
            f'<article class="agent {state_class}"><div class="agent-head">'
            f'<span class="agent-dot" aria-hidden="true"></span><h3>{_h(agent)}</h3></div>'
            f"<p>{_h(AGENT_DESCRIPTIONS[agent])}</p><strong>{_h(activity)}</strong>"
            f"<time>{_h(when)}</time></article>"
        )
    return "".join(cards)


def _progress(workflow: WorkflowTrace) -> str:
    present = {stage.kind for stage in workflow.stages}
    items: list[str] = []
    for kind in WORKFLOW_STAGE_ORDER:
        agent, _ = WORKFLOW_AGENTS[kind]
        classes = ["step"]
        if kind in present:
            classes.append("done")
        if kind == workflow.current_stage and workflow.status != "complete":
            classes.append("current")
        items.append(
            f'<li class="{" ".join(classes)}"><span class="step-mark">'
            f"{'✓' if kind in present else '·'}</span><span><b>{_h(STAGE_LABELS[kind])}</b>"
            f"<small>{_h(agent)}</small></span></li>"
        )
    return f'<ol class="progress" aria-label="工作流阶段">{"".join(items)}</ol>'


def _stage_message(stage: WorkflowStage) -> str:
    side = "left" if stage.agent in {"Love8", "Aizong"} else "right"
    truncated = '<span class="truncated">内容已截断</span>' if stage.content_truncated else ""
    return (
        f'<article class="message {side}"><header><b>{_h(stage.agent)}</b>'
        f"<span>{_h(stage.role)} · {_h(STAGE_LABELS[stage.kind])}</span>"
        f"<time>{_h(_time(stage.ts))}</time></header>"
        f'<div class="message-text">{_h(stage.content)}</div>{truncated}</article>'
    )


def _workflow(workflow: WorkflowTrace, *, opened: bool) -> str:
    complete = workflow.status == "complete"
    status_text = (
        "已完成" if complete else f"进行到：{STAGE_LABELS.get(workflow.current_stage, '等待阶段')}"
    )
    warning = (
        f'<p class="warning">检测到 {workflow.conflicts} 个同阶段冲突签名版本，请人工核对。</p>'
        if workflow.conflicts
        else ""
    )
    messages = "".join(_stage_message(stage) for stage in workflow.stages)
    return (
        f'<details class="workflow" {"open" if opened else ""}><summary><span>'
        f"<b>{_h(workflow.task_id)}</b><small>{_h(_time(workflow.updated_at))}</small></span>"
        f'<span class="workflow-status {"complete" if complete else "active"}">{_h(status_text)}</span>'
        f'</summary><div class="workflow-body">{_progress(workflow)}{warning}'
        f'<section class="conversation" aria-label="Agent 交流时间线">{messages}</section></div></details>'
    )


def dashboard_document(state: dict[str, Any], observation: dict[str, Any]) -> bytes:
    raw_snapshot = state.get("snapshot")
    snapshot = snapshot_from_dict(raw_snapshot) if isinstance(raw_snapshot, dict) else None
    status_name = str(observation.get("status", "waiting"))
    status_label = {
        "ok": "采集正常",
        "degraded": "采集降级",
        "stale": "数据过期",
        "waiting": "等待数据",
    }.get(status_name, status_name)
    if snapshot:
        workflows = "".join(
            _workflow(workflow, opened=index == 0)
            for index, workflow in enumerate(snapshot.workflows)
        )
        if not workflows:
            workflows = (
                '<div class="empty"><b>尚未观察到可验证工作流</b>'
                "<p>Atlas 只显示五类签名阶段；普通聊天、未知发送者和无正文信封不会进入时间线。</p></div>"
            )
        agents = _agent_cards(snapshot)
        summary = snapshot.summary
        room_names = "、".join(f"/r/{room.name}" for room in snapshot.rooms) or "无"
        observed_at = snapshot.observed_at
    else:
        workflows = '<div class="empty"><b>正在等待首次采集</b></div>'
        agents = _agent_cards(Snapshot("technocore-atlas/v2", "", "", (), {}, workflows=()))
        summary = {}
        room_names = "无"
        observed_at = "尚未成功"

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30"><title>Technocore Atlas v2</title>
<style>
:root{{--bg:#07101f;--panel:#101b2e;--panel2:#14243a;--line:#263853;--text:#edf6ff;--muted:#94a9bf;--cyan:#28d7f5;--green:#43dc8c;--amber:#ffbf69;--red:#ff7185}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top,#102746 0,#07101f 42%);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Noto Sans SC",sans-serif}}
main{{max-width:1040px;margin:auto;padding:18px 14px 56px}}header.hero{{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}}h1{{font-size:24px;margin:0;color:var(--cyan);letter-spacing:.04em}}.subtitle{{margin:3px 0;color:var(--muted)}}.health{{white-space:nowrap;border:1px solid var(--line);border-radius:999px;padding:7px 12px;background:var(--panel)}}.health.ok{{color:var(--green)}}.health.degraded,.health.stale{{color:var(--amber)}}
.notice{{background:#0d2135;border-left:3px solid var(--cyan);padding:10px 12px;margin:0 0 18px;color:#c7d8e8}}h2{{font-size:17px;margin:24px 0 10px}}.agents{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.agent{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:13px;min-width:0}}.agent-head{{display:flex;align-items:center;gap:8px}}.agent h3{{font-size:16px;margin:0}}.agent p{{margin:4px 0;color:var(--muted);font-size:13px}}.agent strong,.agent time{{display:block}}.agent time{{font-size:12px;color:var(--muted);margin-top:5px}}.agent-dot{{width:9px;height:9px;border-radius:50%;background:var(--muted)}}.agent.observed .agent-dot{{background:var(--green);box-shadow:0 0 12px var(--green)}}
.workflow{{background:var(--panel);border:1px solid var(--line);border-radius:14px;margin-bottom:12px;overflow:hidden}}.workflow summary{{cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px;min-height:58px}}.workflow summary span:first-child{{min-width:0}}.workflow summary b,.workflow summary small{{display:block;overflow:hidden;text-overflow:ellipsis}}.workflow summary small{{color:var(--muted);font-weight:400}}.workflow-status{{font-size:12px;border-radius:999px;padding:5px 9px;white-space:nowrap;background:#26364d}}.workflow-status.complete{{color:var(--green)}}.workflow-status.active{{color:var(--amber)}}.workflow-body{{border-top:1px solid var(--line);padding:14px}}
.progress{{display:grid;grid-template-columns:repeat(5,1fr);list-style:none;padding:0;margin:0 0 18px;gap:4px}}.step{{display:flex;gap:7px;align-items:center;color:var(--muted);min-width:0}}.step:not(:last-child)::after{{content:"";height:1px;background:var(--line);flex:1;order:3}}.step-mark{{display:grid;place-items:center;width:24px;height:24px;flex:0 0 24px;border-radius:50%;background:#1b2a40;border:1px solid var(--line)}}.step b,.step small{{display:block;font-size:12px;white-space:nowrap}}.step small{{font-size:11px}}.step.done{{color:var(--green)}}.step.current .step-mark{{box-shadow:0 0 12px var(--amber);color:var(--amber)}}
.conversation{{display:flex;flex-direction:column;gap:12px}}.message{{width:min(88%,760px);background:var(--panel2);border:1px solid var(--line);border-radius:12px;padding:12px}}.message.right{{align-self:flex-end;border-color:#285b70}}.message header{{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;margin-bottom:7px}}.message header b{{color:var(--cyan)}}.message header span,.message header time{{color:var(--muted);font-size:12px}}.message header time{{margin-left:auto}}.message-text{{white-space:pre-wrap;overflow-wrap:anywhere}}.truncated{{display:block;color:var(--amber);font-size:12px;margin-top:7px}}.warning{{color:var(--amber)}}.empty{{padding:24px;text-align:center;background:var(--panel);border:1px dashed var(--line);border-radius:12px;color:var(--muted)}}.empty b{{color:var(--text)}}footer{{color:var(--muted);font-size:12px;margin-top:24px;border-top:1px solid var(--line);padding-top:14px}}footer code{{color:var(--cyan)}}
@media(max-width:700px){{header.hero{{display:block}}.health{{display:inline-block;margin-top:10px}}.agents{{grid-template-columns:1fr}}.progress{{grid-template-columns:1fr;gap:7px}}.step:not(:last-child)::after{{display:none}}.message{{width:94%}}.workflow summary{{align-items:flex-start}}}}
</style></head><body><main>
<header class="hero"><div><h1>TECHNOCORE // ATLAS v2</h1><p class="subtitle">三 Agent 工作流观察台 · 每 30 秒自动刷新</p></div><div class="health {_h(status_name)}">● {_h(status_label)}</div></header>
<p class="notice">这里显示的是已观察到的签名阶段，不等于实时在线状态；正文只来自固定字段白名单，并仅通过本机 SSH 隧道查看。</p>
<h2>Agent 最近活动</h2><section class="agents">{agents}</section>
<h2>工作流与交流时间线</h2><section>{workflows}</section>
<footer>公共房间：{_h(room_names)} · 公开消息：{int(summary.get("messages_observed", 0))} · 工作流：{int(summary.get("workflows_observed", 0))}<br>
最近采集：<code>{_h(observed_at)}</code> · 状态含义：公开观察与本机固定工作流来源，不构成身份、质量或持续在线证明。</footer>
</main></body></html>"""
    return html.encode("utf-8")
