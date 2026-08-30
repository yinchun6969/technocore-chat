#!/usr/bin/env python3
"""Server-rendered, mobile-first Atlas pixel workflow dashboard."""

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
    "WORKFLOW_TASK": "任务分派",
    "BUILD_RESULT": "构建执行",
    "CHALLENGE": "审查挑战",
    "REVISED_RESULT": "修订提交",
    "COMPLETE": "验收升旗",
}
AGENT_DESCRIPTIONS = {
    "Love8": "Scout/Gate · 任务分派、入口校验与汇总",
    "Aizong": "Builder · 兼容构建、修订与安全恢复",
    "AI2AI": "Reviewer · 研究核验、节奏与交付挑战",
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
            activity = STAGE_LABELS[stage.kind]
            when = _time(stage.ts) or "时间未知"
            state_class = "observed"
        else:
            activity = "等待签名事件"
            when = "不代表 Agent 离线"
            state_class = "unknown"
        cards.append(
            f'<article class="agent-card {state_class}" data-agent="{_h(agent)}">'
            f'<span class="mini-face" '
            f'data-agent="{_h(agent)}" aria-hidden="true"></span><div><b>{_h(agent)}</b>'
            f"<small>{_h(AGENT_DESCRIPTIONS[agent])}</small>"
            f"<strong data-activity>{_h(activity)}</strong>"
            f"<time data-time>{_h(when)}</time></div></article>"
        )
    return "".join(cards)


def _progress(workflow: WorkflowTrace) -> str:
    present = {stage.kind for stage in workflow.stages}
    highest_observed = max(
        (
            WORKFLOW_STAGE_ORDER.index(kind)
            for kind in present
            if kind in WORKFLOW_STAGE_ORDER
        ),
        default=-1,
    )
    next_missing = (
        WORKFLOW_STAGE_ORDER[highest_observed + 1]
        if highest_observed + 1 < len(WORKFLOW_STAGE_ORDER)
        else None
    )
    items: list[str] = []
    for number, kind in enumerate(WORKFLOW_STAGE_ORDER, 1):
        agent, _ = WORKFLOW_AGENTS[kind]
        classes = ["quest-step"]
        if kind in present:
            classes.append("done")
            stage_state = "已观察签名"
        elif kind == next_missing and workflow.status != "complete":
            classes.append("current")
            stage_state = "等待签名"
        else:
            stage_state = "尚未观察到"
        items.append(
            f'<li class="{" ".join(classes)}"><span>{number}</span><div>'
            f"<b>{_h(STAGE_LABELS[kind])}</b><small>{_h(agent)}</small>"
            f'<small class="stage-state">{_h(stage_state)}</small></div></li>'
        )
    return f'<ol class="quest-map" aria-label="工作流关卡">{"".join(items)}</ol>'


def _stage_message(stage: WorkflowStage) -> str:
    truncated = '<span class="truncated">内容已安全截断</span>' if stage.content_truncated else ""
    return (
        f'<article class="event-row" data-agent="{_h(stage.agent)}">'
        f'<span class="event-icon" aria-hidden="true"></span><div><header>'
        f"<b>{_h(stage.agent)}</b><span>{_h(stage.role)} · {_h(STAGE_LABELS[stage.kind])}</span>"
        f"<time>{_h(_time(stage.ts))}</time></header>"
        f"<p>{_h(stage.content)}</p>{truncated}</div></article>"
    )


def _workflow(workflow: WorkflowTrace, *, opened: bool) -> str:
    complete = workflow.status == "complete"
    status_text = "已通关" if complete else STAGE_LABELS.get(workflow.current_stage, "等待事件")
    warning = (
        f'<p class="warning">发现 {workflow.conflicts} 个同阶段冲突版本，请人工核对。</p>'
        if workflow.conflicts
        else ""
    )
    messages = "".join(_stage_message(stage) for stage in workflow.stages)
    return (
        f'<details class="workflow" {"open" if opened else ""}><summary><span>'
        f"<b>{_h(workflow.task_id)}</b><small>{_h(_time(workflow.updated_at))}</small></span>"
        f'<em class="status {"complete" if complete else "active"}">{_h(status_text)}</em>'
        f'</summary><div class="workflow-body">{_progress(workflow)}{warning}'
        f'<section class="event-list" aria-label="Agent 交流时间线">{messages}</section></div></details>'
    )


def dashboard_document(state: dict[str, Any], observation: dict[str, Any]) -> bytes:
    raw_snapshot = state.get("snapshot")
    snapshot = snapshot_from_dict(raw_snapshot) if isinstance(raw_snapshot, dict) else None
    status_name = str(observation.get("status", "waiting"))
    status_label = {
        "ok": "LIVE",
        "degraded": "DEGRADED",
        "stale": "STALE",
        "waiting": "WAITING",
    }.get(status_name, status_name.upper())
    if snapshot:
        workflows = "".join(
            _workflow(workflow, opened=index == 0)
            for index, workflow in enumerate(snapshot.workflows)
        )
        if not workflows:
            workflows = (
                '<div class="empty"><b>等待第一条可验证工作流</b>'
                "<p>小队会继续巡逻；新签名阶段到达后将自动进入关卡。</p></div>"
            )
        agents = _agent_cards(snapshot)
        summary = snapshot.summary
        room_names = "、".join(f"/r/{room.name}" for room in snapshot.rooms) or "无"
        observed_at = snapshot.observed_at
    else:
        workflows = '<div class="empty"><b>正在载入像素世界</b></div>'
        agents = _agent_cards(Snapshot("technocore-atlas/v2", "", "", (), {}, workflows=()))
        summary = {}
        room_names = "无"
        observed_at = "尚未成功"

    template = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Technocore Atlas v3.7 Relay Quest</title>
<style>
:root{--ink:#11172d;--paper:#fff7d6;--sky:#49bdf2;--blue:#2155a4;--cyan:#20e2f2;--green:#43d36f;--gold:#ffd84a;--red:#ff5b5b;--purple:#a66cff;--line:#15244c;--shadow:#091329}
*{box-sizing:border-box}html{background:#091329}body{margin:0;color:var(--paper);font:15px/1.45 ui-monospace,"SFMono-Regular",Consolas,"Noto Sans SC",monospace;background:linear-gradient(#10295a,#091329 60%);min-height:100vh}
button,select{font:inherit}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px max(12px,env(safe-area-inset-left));background:#091329ee;border-bottom:3px solid #253a70;box-shadow:0 4px 0 #050a17}.brand{display:flex;align-items:center;gap:9px;min-width:0}.brand-copy{min-width:0}.brand b{display:block;color:var(--cyan);font-size:clamp(16px,4vw,23px);letter-spacing:.04em;text-shadow:2px 2px 0 #133376}.brand small{display:block;color:#9bb2df;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.brand-mark{position:relative;width:30px;height:32px;flex:0 0 30px;background:#f7f8ff;clip-path:polygon(0 0,22% 18%,100% 18%,100% 100%,78% 78%,0 78%);filter:drop-shadow(3px 3px 0 #050914)}.brand-mark:before{content:"";position:absolute;left:7px;top:9px;width:17px;height:6px;background:#091329;box-shadow:5px 5px 0 -1px #091329,5px 10px 0 -1px #091329}.brand-mark:after{content:"";position:absolute;right:0;bottom:0;border-left:8px solid transparent;border-top:8px solid var(--cyan)}.top-actions{display:flex;align-items:center;gap:7px;flex:0 0 auto}.lang-switch{min-width:42px;border:2px solid #20e2f2;background:#101f42;color:#fff;padding:5px 7px;box-shadow:3px 3px 0 #050a17}.lang-switch:focus-visible{outline:3px solid var(--gold);outline-offset:2px}.live{flex:0 0 auto;border:2px solid #344d84;padding:5px 8px;background:#101f42;box-shadow:3px 3px 0 #050a17;font-size:12px}.live.ok{color:#62f59c}.live.degraded,.live.stale{color:var(--gold)}
main{width:min(1120px,100%);margin:auto;padding:14px 12px 56px}.game-shell{position:relative;background:#050b18;border:4px solid #29447d;box-shadow:0 0 0 3px #071126,8px 8px 0 #050914;overflow:hidden}.game-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-bottom:3px solid #29447d;background:#0e1c3b}.game-title{color:var(--gold);font-weight:900;text-shadow:2px 2px 0 #8e4d1f}.controls{display:flex;gap:6px}.pixel-btn{border:2px solid #5e78ad;background:#182b54;color:#fff;padding:5px 9px;box-shadow:2px 2px 0 #050914}.pixel-btn:active{transform:translate(2px,2px);box-shadow:none}.pixel-btn[aria-pressed="true"]{color:var(--gold)}.focus-btn{min-width:38px}.relay-progress{position:relative;height:27px;background:#08132a;border-bottom:3px solid #29447d;overflow:hidden}.relay-progress-track{position:absolute;inset:7px 10px;background:#14264c;border:2px solid #415c94}.relay-progress-fill{display:block;width:100%;height:100%;transform:scaleX(0);transform-origin:left;background:linear-gradient(90deg,#20e2f2,#43d36f,#ffd84a);transition:transform .2s linear}.relay-progress-label{position:absolute;inset:4px 10px auto;text-align:center;color:#fff;font-size:11px;font-weight:900;text-shadow:2px 2px 0 #08132a;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.screen{position:relative;aspect-ratio:16/9;max-height:630px;background:#49bdf2}.screen canvas{display:block;width:100%;height:100%;image-rendering:pixelated}.scanlines{pointer-events:none;position:absolute;inset:0;background:repeating-linear-gradient(0deg,#0000 0 3px,#07112612 4px);mix-blend-mode:multiply}.hud{position:absolute;inset:9px 10px auto;display:flex;justify-content:space-between;gap:8px;color:white;font-weight:900;text-shadow:2px 2px 0 #122559;pointer-events:none}.hud span{display:block}.hud small{font-size:9px;color:#fff7d6}.truth{padding:7px 10px;background:#0b1731;border-top:3px solid #29447d;color:#8fa8d6;font-size:11px}.truth b{color:var(--gold)}
.section-title{display:flex;align-items:center;gap:9px;margin:24px 0 10px;font-size:17px;color:var(--paper);text-shadow:2px 2px 0 #050914}.section-title:before{content:"";width:15px;height:15px;background:var(--gold);box-shadow:inset -4px -4px 0 #e28924,2px 2px 0 #050914}.agent-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.agent-card{display:flex;gap:11px;align-items:center;min-width:0;padding:11px;background:#111f40;border:3px solid #29447d;box-shadow:4px 4px 0 #050914}.agent-card>div{min-width:0}.agent-card b,.agent-card small,.agent-card strong,.agent-card time{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.agent-card small,.agent-card time{color:#91a8d1;font-size:11px}.agent-card strong{color:var(--gold);font-size:12px;margin-top:3px}.mini-face{width:36px;height:42px;flex:0 0 36px;background:#ffcf9f;border:4px solid #071126;box-shadow:inset 0 -9px 0 #db8f62,3px 3px 0 #050914;position:relative}.mini-face:before{content:"";position:absolute;left:-4px;right:-4px;top:-9px;height:12px;background:var(--red);border:4px solid #071126}.mini-face:after{content:"";position:absolute;left:7px;top:10px;width:5px;height:5px;background:#071126;box-shadow:13px 0 #071126}.mini-face[data-agent="Aizong"]:before{background:#2978ef}.mini-face[data-agent="AI2AI"]:before{background:#9b5de5}.agent-card.observed{border-color:#3bbf7b}
.workflow{background:#101e3c;border:3px solid #29447d;margin-bottom:12px;box-shadow:5px 5px 0 #050914}.workflow summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px}.workflow summary::-webkit-details-marker{display:none}.workflow summary span{min-width:0}.workflow summary b,.workflow summary small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.workflow summary small{font-size:11px;color:#8fa8d6}.status{font-style:normal;font-size:11px;padding:5px 7px;border:2px solid #526b9f;white-space:nowrap}.status.complete{color:#6cf39e;border-color:#35835b}.status.active{color:var(--gold);border-color:#a77825}.workflow-body{border-top:3px solid #29447d;padding:12px}.quest-map{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;list-style:none;padding:0;margin:0 0 14px}.quest-step{min-width:0;padding:8px 5px;background:#0a152d;border:2px solid #263b6c;text-align:center;color:#7f94bd}.quest-step>span{display:grid;place-items:center;width:23px;height:23px;margin:0 auto 4px;background:#1d2d52;border:2px solid #3c5385}.quest-step b,.quest-step small{display:block;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.quest-step small{font-size:9px}.quest-step.done{color:#6cf39e;border-color:#35835b}.quest-step.done>span{background:#1b7447;color:#fff}.quest-step.current{color:var(--gold);animation:pulse 1s steps(2,end) infinite}.event-list{display:flex;flex-direction:column;gap:8px}.event-row{display:grid;grid-template-columns:34px 1fr;gap:9px;background:#0b1731;border:2px solid #263b6c;padding:9px}.event-icon{width:28px;height:28px;background:var(--red);border:3px solid #050914;box-shadow:inset -5px -5px 0 #bd3434}.event-row[data-agent="Aizong"] .event-icon{background:#3089f4;box-shadow:inset -5px -5px 0 #1856a9}.event-row[data-agent="AI2AI"] .event-icon{background:#aa6bf5;box-shadow:inset -5px -5px 0 #6331a5}.event-row header{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.event-row header b{color:var(--cyan)}.event-row header span,.event-row time{color:#8fa8d6;font-size:11px}.event-row time{margin-left:auto}.event-row p{margin:5px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.truncated,.warning{display:block;color:var(--gold);font-size:11px;margin-top:5px}.empty{text-align:center;padding:26px;background:#101e3c;border:3px dashed #365085;color:#8fa8d6}.empty b{color:#fff}.notice{margin:18px 0 0;padding:10px;background:#0d1a36;border-left:5px solid var(--cyan);color:#9db2d8;font-size:12px}footer{margin-top:22px;padding-top:12px;border-top:2px solid #263b6c;color:#7188b2;font-size:11px}footer code{color:var(--cyan);overflow-wrap:anywhere}
@keyframes pulse{50%{filter:brightness(1.7);transform:translateY(-2px)}}
.live.waiting{color:var(--gold)}.live.stale{color:var(--red)}
.topbar{background:#07142fee;border-bottom-color:#183665;box-shadow:0 4px 0 #030a1d}.brand b{color:#f7f8ff;font-family:ui-rounded,"Arial Rounded MT Bold",system-ui,sans-serif;letter-spacing:.015em;text-shadow:0 0 12px #14bee144}.brand small{color:#9db6db}svg.brand-mark{display:block;width:34px;height:auto;aspect-ratio:100/132;flex:0 0 34px;background:none;clip-path:none;overflow:visible;filter:drop-shadow(0 0 7px #14bee133)}svg.brand-mark .logo-white{fill:#f7f8ff}svg.brand-mark .logo-cut{fill:#07142f}svg.brand-mark .logo-cyan{fill:#14bee1}.lang-switch{border-color:#14bee1;box-shadow:3px 3px 0 #030a1d}
.quest-step .stage-state{margin-top:3px;color:#657ba8}.quest-step.done .stage-state{color:#6cf39e}.quest-step.current{border-color:#a77825}.quest-step.current .stage-state{color:var(--gold)}.stage-meaning{margin:0 0 12px;padding:8px 10px;background:#0a152d;border-left:4px solid var(--gold);color:#9db2d8;font-size:11px}.event-summary{color:#dce8ff;border-left:3px solid var(--cyan);padding-left:8px}.source-label{display:block;margin-top:8px;color:var(--gold);font-size:10px}.signed-source{color:#aebddd}
body.focus-mode{overflow:hidden;background:#050b18}body.focus-mode .topbar,body.focus-mode main>*:not(.game-shell){display:none}body.focus-mode main{width:100%;height:100dvh;padding:0}body.focus-mode .game-shell{position:fixed;inset:0;z-index:1000;border:0;box-shadow:none;display:flex;flex-direction:column}body.focus-mode .screen{flex:1;min-height:0;max-height:none;aspect-ratio:auto;display:flex;align-items:center;justify-content:center;background:#050b18}body.focus-mode .screen canvas{width:100%;height:100%;object-fit:contain}body.focus-mode .truth{display:none}
@media(max-width:700px){.topbar{position:relative;padding:9px 8px}.brand{gap:7px}.brand-mark{width:27px;height:29px;flex-basis:27px}.brand b{font-size:clamp(15px,4vw,19px)}.top-actions{gap:5px}.lang-switch{min-width:38px;padding:4px}.live{padding:4px 6px}main{padding-left:8px;padding-right:8px}.agent-grid{grid-template-columns:1fr}.quest-map{grid-template-columns:1fr}.quest-step{display:flex;align-items:center;gap:8px;text-align:left}.quest-step>span{margin:0}.quest-step b,.quest-step small{font-size:11px}.event-row header time{width:100%;margin:0}.game-head{align-items:flex-start}.game-title{font-size:12px}.hud{font-size:11px}.hud .hide-mobile{display:none}}
@media(prefers-reduced-motion:reduce){.quest-step.current{animation:none}}
@media(max-width:700px){svg.brand-mark{width:30px;height:auto;flex-basis:30px}}
</style></head><body>
<header class="topbar" data-product="TECHNOCORE // PIXEL QUEST"><div class="brand"><svg class="brand-mark" viewBox="0 0 100 132" role="img" aria-label="Technocore flag logo"><path class="logo-white" d="M0 0 20 17H100V98L80 98H0Z"/><path class="logo-cut" d="M20 35H80V52H60V82H40V52H20ZM0 63H40V66H0ZM80 63H100V66H80Z"/><path class="logo-cyan" d="M80 98 100 82V132Z"/></svg><span class="brand-copy"><b>technocore</b><small id="brand-subtitle">Atlas v3.7 · A2A v5.4 · Agent 接力工作流观察器</small></span></div><div class="top-actions"><button id="language" class="lang-switch" type="button" aria-label="Switch to English">EN</button><div id="observation-status" class="live __STATUS_CLASS__">● __STATUS_LABEL__</div></div></header>
<main><section class="game-shell" id="game-shell" aria-label="动态工作流像素关卡"><div class="game-head"><div class="game-title" id="game-title">WORLD 01 · TECHNOCORE WORKFLOW</div><div class="controls"><button id="replay" class="pixel-btn" type="button" aria-pressed="false">▶ REPLAY</button><button id="sound" class="pixel-btn" type="button" aria-pressed="false" title="声音默认关闭">♪ OFF</button><button id="pause" class="pixel-btn" type="button" aria-pressed="false">Ⅱ</button><button id="focus" class="pixel-btn focus-btn" type="button" aria-pressed="false" title="全屏专注模式">⛶</button></div></div>
<div class="relay-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div class="relay-progress-track"><i class="relay-progress-fill" id="progress-fill"></i></div><span class="relay-progress-label" id="progress-label">等待签名工作流</span></div>
<div class="screen"><canvas id="world" width="960" height="540" role="img" aria-label="三个 Agent 在横版像素关卡中执行工作流"></canvas><div class="scanlines"></div><div class="hud"><span><small>TASK</small><b id="hud-task">WAITING</b></span><span class="hide-mobile"><small>STAGE</small><b id="hud-stage">0 / 5</b></span><span><small>EVENTS</small><b id="hud-events">000</b></span></div></div>
<div class="truth" id="truth"><b id="truth-label">图例：</b><span id="truth-copy">3 位主角按“移动 → 工作 → 签名交接”依次行动；迷你助手与粒子仅为场景特效。只有已验证签名事件才进入回放。</span></div></section>
<p class="notice" id="live-note">每 10 秒读取本机 Atlas 快照；上游采集周期约 30 秒。画面活动不等于 Agent 实时在线。</p>
<h2 class="section-title" id="team-title">主角小队</h2><section class="agent-grid">__AGENTS__</section>
<h2 class="section-title" id="workflow-title">任务关卡与真实交流</h2><section id="workflow-history">__WORKFLOWS__</section>
<footer><span id="footer-counts" data-rooms="__ROOMS__" data-messages="__MESSAGES__" data-workflows="__WORKFLOW_COUNT__">公共房间：__ROOMS__ · 公开消息：__MESSAGES__ · 工作流：__WORKFLOW_COUNT__</span><br><span id="footer-note">最近采集：</span><code id="observed-at">__OBSERVED_AT__</code><span id="footer-safety"> · 内容仅来自固定字段白名单；通过本机 SSH 隧道查看。</span></footer></main>
<script>
(()=>{"use strict";
const canvas=document.getElementById("world"),ctx=canvas.getContext("2d",{alpha:false});
const order=["WORKFLOW_TASK","BUILD_RESULT","CHALLENGE","REVISED_RESULT","COMPLETE"];
const owners={WORKFLOW_TASK:"Love8",BUILD_RESULT:"Aizong",CHALLENGE:"AI2AI",REVISED_RESULT:"Aizong",COMPLETE:"Love8"};
const I18N={
zh:{labels:{WORKFLOW_TASK:"任务分派",BUILD_RESULT:"构建执行",CHALLENGE:"审查挑战",REVISED_RESULT:"修订提交",COMPLETE:"验收升旗"},actions:{WORKFLOW_TASK:"读取目标 · 校验入口 · 分派",BUILD_RESULT:"分析需求 · 兼容构建 · 签名",CHALLENGE:"研究核验 · 提出挑战 · 等待修订",REVISED_RESULT:"吸收反馈 · 安全修订 · 再次提交",COMPLETE:"核对结果 · 最终汇总 · 升起战旗"},descriptions:{Love8:"Scout/Gate · 任务分派、入口校验与汇总",Aizong:"Builder · 兼容构建、修订与安全恢复",AI2AI:"Reviewer · 研究核验、节奏与交付挑战"},subtitle:"Atlas v3.6 · PIXEL QUEST · Agent 接力工作流观察器",world:"WORLD 01 · TECHNOCORE 工作流",truthLabel:"图例：",truth:"3 位主角按“移动 → 工作 → 签名交接”依次行动；迷你助手与粒子仅为场景特效。只有已验证签名事件才进入回放。",team:"主角小队",workflows:"任务关卡与真实交流",initialNote:"每 10 秒读取本机 Atlas 快照；上游采集周期约 30 秒。画面活动不等于 Agent 实时在线。",footerCounts:(r,m,w)=>`公共房间：${r} · 公开消息：${m} · 工作流：${w}`,footerNote:"最近采集：",footerSafety:" · 内容仅来自固定字段白名单；通过本机 SSH 隧道查看。",waiting:"等待签名事件",notOffline:"不代表 Agent 离线",unknownTask:"未知任务",complete:"已通关",waitingEvent:"等待事件",questMap:"工作流关卡",conflicts:n=>`发现 ${n} 个同阶段冲突版本，请人工核对。`,timeline:"Agent 交流时间线",unknownAgent:"未知 Agent",event:"事件",signedOriginal:"签名原文",truncated:"内容已安全截断",emptyTitle:"等待第一条可验证工作流",emptyCopy:"小队会继续巡逻；新签名阶段到达后将自动进入关卡。",waitingMessage:"等待下一条签名消息…",go:owner=>`${owner} 前往任务点`,handoff:(a,b)=>`${a} → ${b} 签名交接`,accepted:"Love8 完成验收",waitingSigned:"等待下一条签名事件",readOk:time=>`动态连接正常 · 最近读取 ${time} · 上游快照约每 30 秒更新`,readFail:"动态读取暂时失败；保留最后一帧并等待自动重试。",observedWaiting:"等待采集",replay:"▶ REPLAY",relaying:"● 接力",switchLabel:"Switch to English",focusEnter:"全屏专注模式",focusExit:"退出专注模式",progressWaiting:"等待签名工作流",progressDone:"工作流已完成",phaseMove:"移动",phaseWork:"工作",phaseHandoff:"签名交接",progress:(i,total,stage,phase)=>`阶段 ${i}/${total} · ${stage} · ${phase}`},
en:{labels:{WORKFLOW_TASK:"Task Dispatch",BUILD_RESULT:"Build",CHALLENGE:"Review",REVISED_RESULT:"Revision",COMPLETE:"Acceptance"},actions:{WORKFLOW_TASK:"Read goal · validate gate · dispatch",BUILD_RESULT:"Analyze · build compatibility · sign",CHALLENGE:"Research · challenge · await revision",REVISED_RESULT:"Apply feedback · revise safely · resubmit",COMPLETE:"Verify · summarize · raise the flag"},descriptions:{Love8:"Scout/Gate · dispatch, gate validation and summary",Aizong:"Builder · compatible builds, revisions and recovery",AI2AI:"Reviewer · research, cadence and delivery challenges"},subtitle:"Atlas v3.6 · PIXEL QUEST · Agent Relay Workflow Observer",world:"WORLD 01 · TECHNOCORE WORKFLOW",truthLabel:"LEGEND: ",truth:"The 3 named agents act in sequence: move → work → signed handoff. Mini helpers and particles are visual effects only. Only verified signed events enter replay.",team:"Agent Squad",workflows:"Quest Stages & Signed Communication",initialNote:"Reads the local Atlas snapshot every 10 seconds; upstream collection runs about every 30 seconds. Animation does not prove agent uptime.",footerCounts:(r,m,w)=>`Public rooms: ${r} · messages: ${m} · workflows: ${w}`,footerNote:"Last collection: ",footerSafety:" · Fixed-field allowlist only; viewed through a local SSH tunnel.",waiting:"Waiting for signed event",notOffline:"Not proof the agent is offline",unknownTask:"Unknown task",complete:"Complete",waitingEvent:"Waiting",questMap:"Workflow quest",conflicts:n=>`${n} conflicting versions found for the same stage; manual review required.`,timeline:"Agent communication timeline",unknownAgent:"Unknown agent",event:"Event",signedOriginal:"Signed original",truncated:"Content safely truncated",emptyTitle:"Waiting for the first verified workflow",emptyCopy:"The squad will keep patrolling; a new signed stage starts the quest automatically.",waitingMessage:"Waiting for the next signed message…",go:owner=>`${owner} is moving to the task`,handoff:(a,b)=>`${a} → ${b} signed handoff`,accepted:"Love8 completed acceptance",waitingSigned:"Waiting for the next signed event",readOk:time=>`Live data connected · read at ${time} · upstream snapshot about every 30 seconds`,readFail:"Live read temporarily failed; keeping the last frame and retrying automatically.",observedWaiting:"Waiting for collection",replay:"▶ REPLAY",relaying:"● RELAY",switchLabel:"切换到中文",focusEnter:"Enter focus mode",focusExit:"Exit focus mode",progressWaiting:"Waiting for a signed workflow",progressDone:"Workflow complete",phaseMove:"Moving",phaseWork:"Working",phaseHandoff:"Signed handoff",progress:(i,total,stage,phase)=>`Stage ${i}/${total} · ${stage} · ${phase}`}}
;
Object.assign(I18N.zh,{subtitle:"Atlas v3.7 · A2A v5.4 · Agent 接力工作流观察器",truth:"3 位 Agent 作为接力小队共同移动；只有当前发光并执行工具动作的角色代表已验证签名者，其余角色为随队与接棒动画。迷你助手与粒子仅为场景特效。",teamMove:owner=>`接力小队前进 · ${owner} 主执行`,statusLabels:{ok:"LIVE",degraded:"DEGRADED",stale:"STALE",waiting:"WAITING"},readDegraded:time=>`保留最近已验证快照 ${time||"未知"} · 上游暂时不可用 · 自动重试中`,readStale:time=>`最近已验证快照 ${time||"未知"} 已过期 · 等待上游恢复`,readWaiting:"等待第一份已验证快照",stageObserved:"已观察签名",stageAwaiting:"等待签名",stageUnobserved:"尚未观察到",stageMeaning:"绿色＝已验证签名；黄色＝等待下一条签名；灰色＝尚未观察到，不代表失败或 Agent 离线。",sourceOriginal:"签名原文（保持原语言，未改写）",verifiedSummary:(agent,stage,action)=>`可验证阶段：${agent} · ${stage} · ${action}`,waitingFor:stage=>`已签名 ${stage}，正在等待下一阶段`,signedCount:(n,next)=>`${n}/5 个签名阶段 · 等待 ${next}`,workflowStatus:(n,next)=>`${n}/5 · 等待${next}`});
Object.assign(I18N.en,{subtitle:"Atlas v3.7 · A2A v5.4 · Agent Relay Observer",truth:"All 3 agents travel as a relay team. Only the highlighted agent using a tool represents the verified signer; the other two are team-travel and handoff animation. Mini helpers and particles are visual effects only.",teamMove:owner=>`Relay team moving · ${owner} leads this signed stage`,statusLabels:{ok:"LIVE",degraded:"DEGRADED",stale:"STALE",waiting:"WAITING"},readDegraded:time=>`Last verified snapshot ${time||"unknown"} · upstream temporarily unavailable · retrying`,readStale:time=>`Last verified snapshot ${time||"unknown"} is stale · awaiting upstream recovery`,readWaiting:"Waiting for the first verified snapshot",stageObserved:"Signed & observed",stageAwaiting:"Awaiting signature",stageUnobserved:"Not observed",stageMeaning:"Green = verified signature; yellow = awaiting the next signature; gray = not observed. Gray does not prove failure or agent downtime.",sourceOriginal:"Signed original (source language, unchanged)",verifiedSummary:(agent,stage,action)=>`Verified stage: ${agent} · ${stage} · ${action}`,waitingFor:stage=>`Signed ${stage}; awaiting the next stage`,signedCount:(n,next)=>`${n}/5 signed stages · awaiting ${next}`,workflowStatus:(n,next)=>`${n}/5 · Await ${next}`});
I18N.zh.truth="3 位 Agent 作为接力小队共同移动；只有当前执行工具动作的角色代表已验证签名者，其余角色为随队与接棒动画。迷你助手与粒子仅为场景特效。";
I18N.en.truth="All 3 agents travel as a relay team. Only the agent performing the tool action represents the verified signer; the other two are team-travel and handoff animation. Mini helpers and particles are visual effects only.";
function preferredLanguage(){try{const saved=localStorage.getItem("atlas-language");if(saved==="zh"||saved==="en")return saved}catch(_){}return navigator.language?.toLowerCase().startsWith("zh")?"zh":"en"}
let lang=preferredLanguage(),labels=I18N[lang].labels,actions=I18N[lang].actions;
const colors={Love8:"#ff5b5b",Aizong:"#2978ef",AI2AI:"#a66cff"};
const homes={Love8:70,Aizong:250,AI2AI:430};
const agentNames=["Love8","Aizong","AI2AI"];
const STEP_MS=7600,MOVE_END=.36,WORK_END=.76,stageXs=[150,320,490,660,820];
const S={paused:false,pausedAt:0,sound:false,data:null,lastEvent:"",historyKey:"",workflowKey:"",journey:null,started:performance.now(),replayStart:0,replayCount:0,agents:{Love8:{x:homes.Love8},Aizong:{x:homes.Aizong},AI2AI:{x:homes.AI2AI}},sparkles:[]};
let audio=null;
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
const ease=n=>n<.5?2*n*n:1-Math.pow(-2*n+2,2)/2;
function px(x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(Math.round(x),Math.round(y),Math.round(w),Math.round(h))}
function text(value,x,y,size=14,color="#fff",align="left"){ctx.font=`900 ${size}px ui-monospace,monospace`;ctx.textAlign=align;ctx.textBaseline="top";ctx.fillStyle="#102255";ctx.fillText(value,x+2,y+2);ctx.fillStyle=color;ctx.fillText(value,x,y)}
function applyLanguage(next,persist=true){lang=next==="en"?"en":"zh";labels=I18N[lang].labels;actions=I18N[lang].actions;const c=I18N[lang],counts=document.getElementById("footer-counts"),language=document.getElementById("language"),focus=document.getElementById("focus");document.documentElement.lang=lang==="zh"?"zh-CN":"en";document.title=`Technocore Atlas v3.7 ${lang==="zh"?"接力任务":"Relay Quest"}`;document.getElementById("brand-subtitle").textContent=c.subtitle;document.getElementById("game-title").textContent=c.world;document.getElementById("truth-label").textContent=c.truthLabel;document.getElementById("truth-copy").textContent=c.truth;document.getElementById("team-title").textContent=c.team;document.getElementById("workflow-title").textContent=c.workflows;document.getElementById("footer-note").textContent=c.footerNote;document.getElementById("footer-safety").textContent=c.footerSafety;counts.textContent=c.footerCounts(counts.dataset.rooms,counts.dataset.messages,counts.dataset.workflows);language.textContent=lang==="zh"?"EN":"中";language.setAttribute("aria-label",c.switchLabel);focus.title=document.body.classList.contains("focus-mode")?c.focusExit:c.focusEnter;focus.setAttribute("aria-label",focus.title);document.getElementById("replay").textContent=S.replayStart?c.relaying:c.replay;document.getElementById("sound").title=lang==="zh"?"声音默认关闭":"Sound is off by default";for(const card of document.querySelectorAll(".agent-card[data-agent]")){const description=card.querySelector("small");if(description)description.textContent=c.descriptions[card.dataset.agent]||"Agent"}S.historyKey="";updateProgress(S.journey);if(S.data){renderHistory(S.data);updateObservation(S.data.observation)}else document.getElementById("live-note").textContent=c.initialNote;if(persist)try{localStorage.setItem("atlas-language",lang)}catch(_){}}
function updateProgress(journey){const c=I18N[lang],all=stages(),present=new Set(all.map(e=>e.kind)),highest=Math.max(-1,...[...present].map(kind=>order.indexOf(kind))),next=order[highest+1],bar=document.querySelector(".relay-progress"),fill=document.getElementById("progress-fill"),label=document.getElementById("progress-label");let value=0,copy=c.progressWaiting;if(journey?.active&&all.length){const canonical=Math.max(0,order.indexOf(journey.current?.kind));value=clamp((canonical+journey.progress)/order.length,0,1);const phase=journey.phase==="move"?c.phaseMove:journey.phase==="work"?c.phaseWork:c.phaseHandoff;copy=c.progress(canonical+1,order.length,labels[journey.current?.kind]||journey.current?.kind||c.waitingEvent,phase)}else if(present.has("COMPLETE")){value=1;copy=c.progressDone}else if(all.length){value=clamp(present.size/order.length,0,1);copy=c.signedCount(present.size,labels[next]||c.waitingEvent)}fill.style.transform=`scaleX(${value})`;label.textContent=copy;bar.setAttribute("aria-valuenow",String(Math.round(value*100)));bar.setAttribute("aria-valuetext",copy)}
function setFocus(active){document.body.classList.toggle("focus-mode",active);const button=document.getElementById("focus"),c=I18N[lang];button.setAttribute("aria-pressed",String(active));button.textContent=active?"✕":"⛶";button.title=active?c.focusExit:c.focusEnter;button.setAttribute("aria-label",button.title)}
async function toggleFocus(){const active=!document.body.classList.contains("focus-mode");setFocus(active);if(active){try{if(!document.fullscreenElement)await document.documentElement.requestFullscreen?.()}catch(_){}try{await screen.orientation?.lock?.("landscape")}catch(_){}}else{try{if(document.fullscreenElement)await document.exitFullscreen()}catch(_){}try{screen.orientation?.unlock?.()}catch(_){}}}
function stage(){const ws=S.data?.snapshot?.workflows||[];return ws[0]||null}
function stages(){return stage()?.stages||[]}
function resetActors(){for(const name of Object.keys(S.agents))S.agents[name].x=homes[name];S.sparkles=[]}
function formationTargets(owner,idx){const stageX=stageXs[idx],nextOwner=owners[order[idx+1]],targets={[owner]:stageX};if(nextOwner&&nextOwner!==owner)targets[nextOwner]=clamp(stageX+78,40,860);let behind=0;for(const name of agentNames)if(targets[name]===undefined){targets[name]=clamp(stageX-78-behind*70,40,860);behind++}return targets}
function beginReplay(){if(!stages().length)return;resetActors();S.replayStart=performance.now();S.replayCount=0;const button=document.getElementById("replay");button.setAttribute("aria-pressed","true");button.textContent=I18N[lang].relaying}
function relay(now){const all=stages();if(!S.replayStart||!all.length)return{events:all,current:null,index:Math.max(0,all.length-1),phase:"idle",progress:1,active:false};const elapsed=now-S.replayStart,index=Math.floor(elapsed/STEP_MS);if(index>=all.length){if(elapsed>all.length*STEP_MS+1400){S.replayStart=0;S.replayCount=0;const button=document.getElementById("replay");button.setAttribute("aria-pressed","false");button.textContent=I18N[lang].replay}return{events:all,current:null,index:Math.max(0,all.length-1),phase:"idle",progress:1,active:false}}const progress=(elapsed-index*STEP_MS)/STEP_MS,phase=progress<MOVE_END?"move":progress<WORK_END?"work":"handoff",committed=index+(phase==="handoff"?1:0);if(committed>S.replayCount){S.replayCount=committed;blip(all[index]?.kind)}return{events:all.slice(0,committed),current:all[index],index,phase,progress,active:true}}
function cloud(x,y,s){px(x,y+8,50*s,16*s,"#dff7ff");px(x+10*s,y,20*s,22*s,"#fff");px(x+29*s,y+3*s,16*s,18*s,"#f5fdff")}
function hill(x,y,w,h,c){ctx.fillStyle=c;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w*.5,y-h);ctx.lineTo(x+w,y);ctx.fill();px(x+w*.47,y-h+18,8,8,"#d9f77c");px(x+w*.63,y-h*.35,7,7,"#d9f77c")}
function block(x,y,kind,done,current){const c=done?"#e9972f":"#bb7130";px(x,y,58,45,c);px(x,y,58,6,done?"#ffd34f":"#dc9349");px(x,y+39,58,6,"#713e27");px(x+26,y,6,45,"#8d4d29");if(current){px(x-4,y-4,66,4,"#fff35e");px(x-4,y+45,66,4,"#fff35e")}text(kind,x+29,y+13,13,done?"#fff6ad":"#412515","center")}
function coin(x,y,t){const squash=Math.abs(Math.sin(t))*6+2;px(x-squash/2,y,squash,18,"#ffd84a");px(x-squash/2+2,y+3,Math.max(2,squash-4),12,"#fff39a")}
function pipe(x,y){px(x,y,52,74,"#168f58");px(x-8,y,68,18,"#38d57b");px(x-4,y+4,60,7,"#77f0a7");px(x+37,y+18,9,56,"#0b633e")}
function flag(x,y,raised,t){px(x,y-132,5,132,"#e8f4ff");px(x+3,y-132,2,132,"#7898c7");px(x-5,y-139,15,15,"#20e2f2");px(x-1,y-135,7,7,"#f7f8ff");const fy=raised?y-123:y-42,wave=Math.round(Math.sin(t*3)*2),navy="#081631",cyan="#20e2f2",white="#f7f8ff";px(x+5,fy+wave,70,44,navy);px(x+5,fy+wave,70,4,cyan);px(x+5,fy+40+wave,62,4,cyan);px(x+67,fy+32+wave,8,8,cyan);px(x+75,fy+36+wave,8,8,cyan);px(x+18,fy+9+wave,35,27,white);px(x+18,fy+9+wave,8,6,navy);px(x+26,fy+15+wave,22,6,navy);px(x+34,fy+20+wave,7,14,navy);px(x+18,fy+28+wave,16,4,navy);px(x+41,fy+28+wave,12,4,navy);px(x+48,fy+31+wave,5,5,cyan)}
function avatar(name,x,y,t,motion={}){const c=colors[name],walking=Boolean(motion.walking),watching=Boolean(motion.watching),walk=walking?Math.sin(t*4.2+x)*3:0,watch=watching?Math.sin(t*3+x)*3:0,bob=walking?Math.abs(Math.sin(t*4.2+x))*2:watching?Math.abs(Math.sin(t*2+x))*.9:0;ctx.save();ctx.translate(Math.round(x),Math.round(y-bob));px(-10,-54,21,13,c);px(-14,-48,30,7,c);px(-10,-41,22,19,"#ffcf9f");px(7,-36,5,5,"#10162c");px(-9,-22,22,21,c);px(-16,-19+watch,8,15,"#ffcf9f");px(13,-19-watch,8,15,"#ffcf9f");px(-9,-1+walk,8,12,"#19213c");px(5,-1-walk,8,12,"#19213c");if(watching){px(-20,-42,5,5,"#20e2f2");px(17,-46,5,5,"#fff35e")}if(motion.action==="WORKFLOW_TASK"){px(18,-38,18,24,"#fff7d6");px(21,-34,12,3,"#20e2f2");px(21,-28,9,3,"#566a94");px(-25,-38,4,4,"#fff35e");px(-31,-44,4,4,"#fff35e")}if(motion.action==="BUILD_RESULT"){const swing=Math.sin(t*5)*4;px(18,-30,5,21,"#754329");px(13+swing,-38,18,8,"#d9e4f2");px(16+swing,-35,12,4,"#6c7891");px(-22,-9,8,8,"#ffd84a")}if(motion.action==="CHALLENGE"){ctx.strokeStyle="#f7f8ff";ctx.lineWidth=5;ctx.beginPath();ctx.arc(21,-29,10,0,Math.PI*2);ctx.stroke();px(27,-21,5,17,"#172142");text("!",-24,-46,20,"#fff35e","center")}if(motion.action==="REVISED_RESULT"){px(17,-38,22,25,"#e8f4ff");px(21,-33,14,4,"#20e2f2");px(21,-25,10,4,"#43d36f");px(21,-18,14,3,"#566a94");px(-22,-12,7,7,"#fff35e")}if(motion.action==="COMPLETE"){px(-23,-45,7,24,"#ffcf9f");px(17,-45,7,24,"#ffcf9f");px(-27,-51,12,8,"#20e2f2");px(16,-51,12,8,"#20e2f2")}ctx.restore();text(name,x,y+14,11,"#fff","center")}
function helper(x,y,c,t,i){const bob=Math.sin(t*.85+i)*2;px(x,y-17+bob,11,11,c);px(x-3,y-5+bob,17,11,"#eff7ff");px(x,y-12+bob,3,3,"#091329");px(x+7,y-12+bob,3,3,"#091329")}
function handoff(fromX,toX,y,p,color){const q=ease(clamp((p-WORK_END)/(1-WORK_END),0,1)),x=fromX+(toX-fromX)*q,arc=Math.sin(q*Math.PI)*42;ctx.strokeStyle="#e8f4ff88";ctx.lineWidth=3;ctx.setLineDash([8,8]);ctx.beginPath();ctx.moveTo(fromX,y);ctx.quadraticCurveTo((fromX+toX)/2,y-70,toX,y);ctx.stroke();ctx.setLineDash([]);px(x-10,y-arc-8,20,14,"#f7f8ff");px(x-7,y-arc-5,14,3,color);px(x-7,y-arc,10,3,"#29447d");px(x+5,y-arc-8,5,5,"#20e2f2")}
function bubble(value,x,y,w){const clean=String(value||"").replace(/\s+/g," ").slice(0,72)||I18N[lang].waitingMessage;px(x,y,w,58,"#fff7d6");px(x+5,y+5,w-10,48,"#fff");px(x+20,y+58,12,8,"#fff7d6");ctx.fillStyle="#172142";ctx.font="900 12px ui-monospace,monospace";ctx.textAlign="left";ctx.textBaseline="top";const chars=[...clean];let line="",lines=[],limit=Math.max(14,Math.floor(w/13));for(const ch of chars){if(line.length>=limit){lines.push(line);line=""}line+=ch}if(line)lines.push(line);lines.slice(0,2).forEach((s,i)=>ctx.fillText(s,x+10,y+10+i*18))}
function addFx(){for(let i=0;i<30;i++)S.sparkles.push({x:760+Math.random()*90,y:250+Math.random()*120,vx:(Math.random()-.5)*80,vy:-Math.random()*110-30,c:["#ffd84a","#fff7a6","#55ef91","#50ddff"][i%4],life:1+Math.random()})}
function drawFx(dt){S.sparkles=S.sparkles.filter(p=>p.life>0);for(const p of S.sparkles){p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=180*dt;p.life-=dt;px(p.x,p.y,6,6,p.c)}}
function draw(now){const t=(now-S.started)/1000,w=960,h=540,workflow=stage(),journey=relay(now),events=journey.events,current=journey.current,last=events[events.length-1],kind=current?.kind||last?.kind||order[0],idx=Math.max(0,order.indexOf(kind)),owner=owners[kind],targets=formationTargets(owner,idx),complete=events.some(e=>e.kind==="COMPLETE"),copy=I18N[lang];S.journey=journey;updateProgress(journey);ctx.imageSmoothingEnabled=false;px(0,0,w,h,"#49bdf2");px(0,315,w,125,"#75d8f7");cloud((70+t*1.5)%1050-90,85,1);cloud((540+t*.85)%1100-100,120,.8);hill(-20,410,260,150,"#62c969");hill(170,410,330,205,"#3fac65");hill(560,410,330,180,"#64c96c");pipe(25,350);flag(875,410,complete,t);for(let i=0;i<5;i++){const done=events.some(e=>e.kind===order[i]);block(stageXs[i]-29,350,`${i+1}`,done,i===idx&&journey.active&&!done);text(labels[order[i]],stageXs[i],322,10,"#fff","center");if(done)coin(stageXs[i],292,t*2+i)}px(0,410,w,40,"#8b5a32");for(let x=0;x<w;x+=32){px(x,410,30,18,"#c3843f");px(x+15,430,30,18,"#a86835")}px(0,450,w,90,"#6d3e27");for(let x=0;x<w;x+=48)px(x,475+(x%96?20:0),25,9,"#855031");if(journey.active)for(const name of agentNames){const speed=journey.phase==="move"?.045:.12;S.agents[name].x+=(targets[name]-S.agents[name].x)*speed}for(const name of agentNames){const distance=Math.abs(targets[name]-S.agents[name].x),motion={walking:journey.active&&journey.phase==="move"&&distance>1,watching:journey.active&&name!==owner&&journey.phase!=="move",action:journey.active&&name===owner&&journey.phase==="work"?kind:""};avatar(name,S.agents[name].x,405,t,motion)}if(journey.active&&journey.phase==="handoff"&&idx<order.length-1){const nextOwner=owners[order[idx+1]];handoff(S.agents[owner].x,S.agents[nextOwner].x,335,journey.progress,colors[owner])}const hc=["#e2f14a","#f57bd7","#73f0d1","#ff9f43"];for(let i=0;i<10;i++)helper(90+i*82,405,hc[i%4],t,i);const bubbleCopy=lang==="en"?actions[kind]:(current||last)?.content;bubble(bubbleCopy,clamp(stageXs[idx]-125,12,698),190,250);if(complete&&S.sparkles.length===0)addFx();drawFx(1/60);const phaseLabel=journey.phase==="move"?copy.teamMove(owner):journey.phase==="work"?actions[kind]:journey.phase==="handoff"?(idx<4?copy.handoff(owner,owners[order[idx+1]]):copy.accepted):complete?"QUEST CLEAR!":workflow?copy.waitingFor(labels[kind]):"WAITING FOR QUEST";text(phaseLabel,480,35,18,complete&&!journey.active?"#fff35e":"#fff","center");if(!S.paused)requestAnimationFrame(draw)}
function blip(kind){if(!S.sound||!audio)return;const osc=audio.createOscillator(),gain=audio.createGain(),freq={WORKFLOW_TASK:330,BUILD_RESULT:392,CHALLENGE:220,REVISED_RESULT:494,COMPLETE:660}[kind]||300;osc.type="square";osc.frequency.value=freq;gain.gain.setValueAtTime(.035,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.16);osc.connect(gain).connect(audio.destination);osc.start();osc.stop(audio.currentTime+.17)}
function make(tag,className,value){const node=document.createElement(tag);if(className)node.className=className;if(value!==undefined)node.textContent=String(value);return node}
function formatTime(value){return String(value||"").replace("T"," ").replace(/Z$/,"")+ (value?" UTC":"")}
function renderAgents(workflows){const c=I18N[lang],latest={};for(const wf of workflows)for(const ev of (wf.stages||[])){const old=latest[ev.agent];if(!old||String(ev.ts)>String(old.ts))latest[ev.agent]=ev}for(const card of document.querySelectorAll(".agent-card[data-agent]")){const ev=latest[card.dataset.agent],activity=card.querySelector("[data-activity]"),when=card.querySelector("[data-time]"),description=card.querySelector("small");card.classList.toggle("observed",Boolean(ev));card.classList.toggle("unknown",!ev);if(description)description.textContent=c.descriptions[card.dataset.agent]||"Agent";activity.textContent=ev?(labels[ev.kind]||ev.kind):c.waiting;when.textContent=ev?formatTime(ev.ts):c.notOffline}}
function renderHistory(data){const c=I18N[lang],root=document.getElementById("workflow-history"),workflows=data?.snapshot?.workflows||[],key=lang+JSON.stringify(workflows.map(w=>[w.task_id,w.updated_at,(w.stages||[]).length,w.conflicts]));if(key===S.historyKey){renderAgents(workflows);return}S.historyKey=key;if(!workflows.length){const box=make("div","empty"),title=make("b","",c.emptyTitle),copy=make("p","",c.emptyCopy);box.append(title,copy);root.replaceChildren(box);renderAgents([]);return}const fragment=document.createDocumentFragment();workflows.forEach((wf,index)=>{const details=make("details","workflow");details.open=index===0;const present=new Set((wf.stages||[]).map(e=>e.kind)),highest=Math.max(-1,...[...present].map(kind=>order.indexOf(kind))),nextKind=order[highest+1],summary=make("summary"),identity=make("span"),task=make("b","",wf.task_id||c.unknownTask),updated=make("small","",formatTime(wf.updated_at)),complete=wf.status==="complete",status=make("em",`status ${complete?"complete":"active"}`,complete?c.complete:c.workflowStatus(present.size,labels[nextKind]||c.waitingEvent));identity.append(task,updated);summary.append(identity,status);const body=make("div","workflow-body"),quest=make("ol","quest-map");quest.setAttribute("aria-label",c.questMap);order.forEach((kind,i)=>{const observed=present.has(kind),awaiting=!observed&&kind===nextKind&&!complete,item=make("li","quest-step"+(observed?" done":"")+(awaiting?" current":"")),number=make("span","",i+1),info=make("div"),name=make("b","",labels[kind]),owner=make("small","",owners[kind]),state=make("small","stage-state",observed?c.stageObserved:awaiting?c.stageAwaiting:c.stageUnobserved);info.append(name,owner,state);item.append(number,info);quest.append(item)});body.append(quest,make("p","stage-meaning",c.stageMeaning));if(Number(wf.conflicts)>0)body.append(make("p","warning",c.conflicts(wf.conflicts)));const list=make("section","event-list");list.setAttribute("aria-label",c.timeline);for(const ev of (wf.stages||[])){const row=make("article","event-row");row.dataset.agent=ev.agent||"";const icon=make("span","event-icon"),content=make("div"),head=make("header"),name=make("b","",ev.agent||c.unknownAgent),meta=make("span","",`${labels[ev.kind]||ev.kind||c.event} · ${c.stageObserved}`),time=make("time","",formatTime(ev.ts)),summaryCopy=make("p","event-summary",c.verifiedSummary(ev.agent||c.unknownAgent,labels[ev.kind]||ev.kind||c.event,actions[ev.kind]||c.event)),sourceLabel=make("span","source-label",c.sourceOriginal),copy=make("p","signed-source",ev.content||"");icon.setAttribute("aria-hidden","true");head.append(name,meta,time);content.append(head,summaryCopy,sourceLabel,copy);if(ev.content_truncated)content.append(make("span","truncated",c.truncated));row.append(icon,content);list.append(row)}body.append(list);details.append(summary,body);fragment.append(details)});root.replaceChildren(fragment);renderAgents(workflows)}
function updateHud(data){const c=I18N[lang],snap=data?.snapshot||{},ws=snap.workflows||[],wf=ws[0],ev=wf?.stages||[],last=ev[ev.length-1];document.getElementById("hud-task").textContent=(wf?.task_id||"WAITING").slice(-14);document.getElementById("hud-stage").textContent=`${ev.length} / 5`;document.getElementById("hud-events").textContent=String(ev.length).padStart(3,"0");document.getElementById("observed-at").textContent=snap.observed_at||c.observedWaiting;const key=last?`${wf.task_id}:${last.kind}:${last.ts}`:"";if(key&&S.lastEvent&&key!==S.lastEvent){addFx();blip(last.kind)}S.lastEvent=key}
function updateObservation(info){const c=I18N[lang],badge=document.getElementById("observation-status"),note=document.getElementById("live-note"),allowed=new Set(["ok","degraded","stale","waiting"]),state=allowed.has(info?.status)?info.status:"waiting",last=info?.last_success?formatTime(info.last_success):"";badge.className=`live ${state}`;badge.textContent=`● ${c.statusLabels[state]}`;if(state==="ok"){note.textContent=c.readOk(new Date().toLocaleTimeString());note.style.borderColor="#43d36f"}else if(state==="degraded"){note.textContent=c.readDegraded(last);note.style.borderColor="#ffd84a"}else if(state==="stale"){note.textContent=c.readStale(last);note.style.borderColor="#ff5b5b"}else{note.textContent=c.readWaiting;note.style.borderColor="#ffd84a"}}
async function refresh(){const c=I18N[lang];try{const res=await fetch("/atlas.json",{cache:"no-store",headers:{Accept:"application/json"}});if(!res.ok)throw new Error("HTTP "+res.status);const data=await res.json(),wf=data?.snapshot?.workflows?.[0],workflowKey=wf?`${wf.task_id}:${wf.updated_at}:${(wf.stages||[]).length}`:"";S.data=data;updateHud(data);renderHistory(data);updateObservation(data.observation);if(workflowKey&&workflowKey!==S.workflowKey){S.workflowKey=workflowKey;beginReplay()}}catch(_){const badge=document.getElementById("observation-status"),note=document.getElementById("live-note");badge.className="live degraded";badge.textContent=`● ${c.statusLabels.degraded}`;note.textContent=c.readFail;note.style.borderColor="#ffd84a"}}
document.getElementById("replay").addEventListener("click",beginReplay);
document.getElementById("language").addEventListener("click",()=>applyLanguage(lang==="zh"?"en":"zh"));
document.getElementById("focus").addEventListener("click",toggleFocus);
document.addEventListener("fullscreenchange",()=>{if(!document.fullscreenElement&&document.body.classList.contains("focus-mode")){setFocus(false);try{screen.orientation?.unlock?.()}catch(_){}}});
document.getElementById("pause").addEventListener("click",e=>{S.paused=!S.paused;e.currentTarget.setAttribute("aria-pressed",String(S.paused));e.currentTarget.textContent=S.paused?"▶":"Ⅱ";if(S.paused){S.pausedAt=performance.now()}else{const resumed=performance.now(),held=resumed-S.pausedAt;S.started+=held;if(S.replayStart)S.replayStart+=held;requestAnimationFrame(draw)}});
document.getElementById("sound").addEventListener("click",e=>{S.sound=!S.sound;if(S.sound){const Audio=window.AudioContext||window.webkitAudioContext;audio=audio||(Audio?new Audio():null);blip(stages().at(-1)?.kind)}e.currentTarget.setAttribute("aria-pressed",String(S.sound));e.currentTarget.textContent=S.sound?"♪ ON":"♪ OFF"});
applyLanguage(lang,false);refresh();setInterval(refresh,10000);requestAnimationFrame(draw);
})();
</script></body></html>"""
    replacements = {
        "__STATUS_CLASS__": _h(status_name),
        "__STATUS_LABEL__": _h(status_label),
        "__AGENTS__": agents,
        "__WORKFLOWS__": workflows,
        "__ROOMS__": _h(room_names),
        "__MESSAGES__": str(int(summary.get("messages_observed", 0))),
        "__WORKFLOW_COUNT__": str(int(summary.get("workflows_observed", 0))),
        "__OBSERVED_AT__": _h(observed_at),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template.encode("utf-8")
