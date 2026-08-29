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
    "WORKFLOW_TASK": "任务出现",
    "BUILD_RESULT": "开始建造",
    "CHALLENGE": "交叉挑战",
    "REVISED_RESULT": "修订升级",
    "COMPLETE": "完成升旗",
}
AGENT_DESCRIPTIONS = {
    "Love8": "Scout · 侦察与汇总",
    "Aizong": "Builder · 建造与修订",
    "AI2AI": "Reviewer · 挑战与核验",
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
    items: list[str] = []
    for number, kind in enumerate(WORKFLOW_STAGE_ORDER, 1):
        agent, _ = WORKFLOW_AGENTS[kind]
        classes = ["quest-step"]
        if kind in present:
            classes.append("done")
        if kind == workflow.current_stage and workflow.status != "complete":
            classes.append("current")
        items.append(
            f'<li class="{" ".join(classes)}"><span>{number}</span><div>'
            f"<b>{_h(STAGE_LABELS[kind])}</b><small>{_h(agent)}</small></div></li>"
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
<title>Technocore Atlas v3 Pixel Quest</title>
<style>
:root{--ink:#11172d;--paper:#fff7d6;--sky:#49bdf2;--blue:#2155a4;--cyan:#20e2f2;--green:#43d36f;--gold:#ffd84a;--red:#ff5b5b;--purple:#a66cff;--line:#15244c;--shadow:#091329}
*{box-sizing:border-box}html{background:#091329}body{margin:0;color:var(--paper);font:15px/1.45 ui-monospace,"SFMono-Regular",Consolas,"Noto Sans SC",monospace;background:linear-gradient(#10295a,#091329 60%);min-height:100vh}
button,select{font:inherit}.topbar{position:sticky;top:0;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px max(12px,env(safe-area-inset-left));background:#091329ee;border-bottom:3px solid #253a70;box-shadow:0 4px 0 #050a17}.brand{min-width:0}.brand b{display:block;color:var(--cyan);font-size:clamp(16px,4vw,23px);letter-spacing:.04em;text-shadow:2px 2px 0 #133376}.brand small{display:block;color:#9bb2df;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.live{flex:0 0 auto;border:2px solid #344d84;padding:5px 8px;background:#101f42;box-shadow:3px 3px 0 #050a17;font-size:12px}.live.ok{color:#62f59c}.live.degraded,.live.stale{color:var(--gold)}
main{width:min(1120px,100%);margin:auto;padding:14px 12px 56px}.game-shell{position:relative;background:#050b18;border:4px solid #29447d;box-shadow:0 0 0 3px #071126,8px 8px 0 #050914;overflow:hidden}.game-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;border-bottom:3px solid #29447d;background:#0e1c3b}.game-title{color:var(--gold);font-weight:900;text-shadow:2px 2px 0 #8e4d1f}.controls{display:flex;gap:6px}.pixel-btn{border:2px solid #5e78ad;background:#182b54;color:#fff;padding:5px 9px;box-shadow:2px 2px 0 #050914}.pixel-btn:active{transform:translate(2px,2px);box-shadow:none}.pixel-btn[aria-pressed="true"]{color:var(--gold)}
.screen{position:relative;aspect-ratio:16/9;max-height:630px;background:#49bdf2}.screen canvas{display:block;width:100%;height:100%;image-rendering:pixelated}.scanlines{pointer-events:none;position:absolute;inset:0;background:repeating-linear-gradient(0deg,#0000 0 3px,#07112612 4px);mix-blend-mode:multiply}.hud{position:absolute;inset:9px 10px auto;display:flex;justify-content:space-between;gap:8px;color:white;font-weight:900;text-shadow:2px 2px 0 #122559;pointer-events:none}.hud span{display:block}.hud small{font-size:9px;color:#fff7d6}.truth{padding:7px 10px;background:#0b1731;border-top:3px solid #29447d;color:#8fa8d6;font-size:11px}.truth b{color:var(--gold)}
.section-title{display:flex;align-items:center;gap:9px;margin:24px 0 10px;font-size:17px;color:var(--paper);text-shadow:2px 2px 0 #050914}.section-title:before{content:"";width:15px;height:15px;background:var(--gold);box-shadow:inset -4px -4px 0 #e28924,2px 2px 0 #050914}.agent-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.agent-card{display:flex;gap:11px;align-items:center;min-width:0;padding:11px;background:#111f40;border:3px solid #29447d;box-shadow:4px 4px 0 #050914}.agent-card>div{min-width:0}.agent-card b,.agent-card small,.agent-card strong,.agent-card time{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.agent-card small,.agent-card time{color:#91a8d1;font-size:11px}.agent-card strong{color:var(--gold);font-size:12px;margin-top:3px}.mini-face{width:36px;height:42px;flex:0 0 36px;background:#ffcf9f;border:4px solid #071126;box-shadow:inset 0 -9px 0 #db8f62,3px 3px 0 #050914;position:relative}.mini-face:before{content:"";position:absolute;left:-4px;right:-4px;top:-9px;height:12px;background:var(--red);border:4px solid #071126}.mini-face:after{content:"";position:absolute;left:7px;top:10px;width:5px;height:5px;background:#071126;box-shadow:13px 0 #071126}.mini-face[data-agent="Aizong"]:before{background:#2978ef}.mini-face[data-agent="AI2AI"]:before{background:#9b5de5}.agent-card.observed{border-color:#3bbf7b}
.workflow{background:#101e3c;border:3px solid #29447d;margin-bottom:12px;box-shadow:5px 5px 0 #050914}.workflow summary{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px}.workflow summary::-webkit-details-marker{display:none}.workflow summary span{min-width:0}.workflow summary b,.workflow summary small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.workflow summary small{font-size:11px;color:#8fa8d6}.status{font-style:normal;font-size:11px;padding:5px 7px;border:2px solid #526b9f;white-space:nowrap}.status.complete{color:#6cf39e;border-color:#35835b}.status.active{color:var(--gold);border-color:#a77825}.workflow-body{border-top:3px solid #29447d;padding:12px}.quest-map{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;list-style:none;padding:0;margin:0 0 14px}.quest-step{min-width:0;padding:8px 5px;background:#0a152d;border:2px solid #263b6c;text-align:center;color:#7f94bd}.quest-step>span{display:grid;place-items:center;width:23px;height:23px;margin:0 auto 4px;background:#1d2d52;border:2px solid #3c5385}.quest-step b,.quest-step small{display:block;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.quest-step small{font-size:9px}.quest-step.done{color:#6cf39e;border-color:#35835b}.quest-step.done>span{background:#1b7447;color:#fff}.quest-step.current{color:var(--gold);animation:pulse 1s steps(2,end) infinite}.event-list{display:flex;flex-direction:column;gap:8px}.event-row{display:grid;grid-template-columns:34px 1fr;gap:9px;background:#0b1731;border:2px solid #263b6c;padding:9px}.event-icon{width:28px;height:28px;background:var(--red);border:3px solid #050914;box-shadow:inset -5px -5px 0 #bd3434}.event-row[data-agent="Aizong"] .event-icon{background:#3089f4;box-shadow:inset -5px -5px 0 #1856a9}.event-row[data-agent="AI2AI"] .event-icon{background:#aa6bf5;box-shadow:inset -5px -5px 0 #6331a5}.event-row header{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.event-row header b{color:var(--cyan)}.event-row header span,.event-row time{color:#8fa8d6;font-size:11px}.event-row time{margin-left:auto}.event-row p{margin:5px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.truncated,.warning{display:block;color:var(--gold);font-size:11px;margin-top:5px}.empty{text-align:center;padding:26px;background:#101e3c;border:3px dashed #365085;color:#8fa8d6}.empty b{color:#fff}.notice{margin:18px 0 0;padding:10px;background:#0d1a36;border-left:5px solid var(--cyan);color:#9db2d8;font-size:12px}footer{margin-top:22px;padding-top:12px;border-top:2px solid #263b6c;color:#7188b2;font-size:11px}footer code{color:var(--cyan);overflow-wrap:anywhere}
@keyframes pulse{50%{filter:brightness(1.7);transform:translateY(-2px)}}
@media(max-width:700px){main{padding-left:8px;padding-right:8px}.agent-grid{grid-template-columns:1fr}.quest-map{grid-template-columns:1fr}.quest-step{display:flex;align-items:center;gap:8px;text-align:left}.quest-step>span{margin:0}.quest-step b,.quest-step small{font-size:11px}.event-row header time{width:100%;margin:0}.game-head{align-items:flex-start}.game-title{font-size:12px}.hud{font-size:11px}.hud .hide-mobile{display:none}}
@media(prefers-reduced-motion:reduce){.quest-step.current{animation:none}}
</style></head><body>
<header class="topbar"><div class="brand"><b>TECHNOCORE // PIXEL QUEST</b><small>Atlas v3 · 真实签名事件驱动的 Agent 世界</small></div><div class="live __STATUS_CLASS__">● __STATUS_LABEL__</div></header>
<main><section class="game-shell" aria-label="动态工作流像素关卡"><div class="game-head"><div class="game-title">WORLD 01 · TECHNOCORE WORKFLOW</div><div class="controls"><button id="replay" class="pixel-btn" type="button" aria-pressed="false">▶ REPLAY</button><button id="sound" class="pixel-btn" type="button" aria-pressed="false" title="声音默认关闭">♪ OFF</button><button id="pause" class="pixel-btn" type="button" aria-pressed="false">Ⅱ</button></div></div>
<div class="screen"><canvas id="world" width="960" height="540" role="img" aria-label="三个 Agent 在横版像素关卡中执行工作流"></canvas><div class="scanlines"></div><div class="hud"><span><small>TASK</small><b id="hud-task">WAITING</b></span><span class="hide-mobile"><small>STAGE</small><b id="hud-stage">0 / 5</b></span><span><small>EVENTS</small><b id="hud-events">000</b></span></div></div>
<div class="truth"><b>图例：</b>有名字的 3 个角色代表已配置 Agent；迷你助手与粒子属于场景特效，不代表额外 Agent。只有已验证签名事件才推动关卡。</div></section>
<p class="notice" id="live-note">每 10 秒读取本机 Atlas 快照；上游采集周期约 30 秒。画面活动不等于 Agent 实时在线。</p>
<h2 class="section-title">主角小队</h2><section class="agent-grid">__AGENTS__</section>
<h2 class="section-title">任务关卡与真实交流</h2><section id="workflow-history">__WORKFLOWS__</section>
<footer>公共房间：__ROOMS__ · 公开消息：__MESSAGES__ · 工作流：__WORKFLOW_COUNT__<br>最近采集：<code id="observed-at">__OBSERVED_AT__</code> · 内容仅来自固定字段白名单；通过本机 SSH 隧道查看。</footer></main>
<script>
(()=>{"use strict";
const canvas=document.getElementById("world"),ctx=canvas.getContext("2d",{alpha:false});
const order=["WORKFLOW_TASK","BUILD_RESULT","CHALLENGE","REVISED_RESULT","COMPLETE"];
const labels={WORKFLOW_TASK:"任务出现",BUILD_RESULT:"开始建造",CHALLENGE:"交叉挑战",REVISED_RESULT:"修订升级",COMPLETE:"完成升旗"};
const owners={WORKFLOW_TASK:"Love8",BUILD_RESULT:"Aizong",CHALLENGE:"AI2AI",REVISED_RESULT:"Aizong",COMPLETE:"Love8"};
const colors={Love8:"#ff5b5b",Aizong:"#2978ef",AI2AI:"#a66cff"};
const S={paused:false,sound:false,data:null,lastEvent:"",historyKey:"",started:performance.now(),replayStart:0,replayCount:0,agents:{Love8:{x:110},Aizong:{x:170},AI2AI:{x:230}},sparkles:[]};
let audio=null;
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
function px(x,y,w,h,c){ctx.fillStyle=c;ctx.fillRect(Math.round(x),Math.round(y),Math.round(w),Math.round(h))}
function text(value,x,y,size=14,color="#fff",align="left"){ctx.font=`900 ${size}px ui-monospace,monospace`;ctx.textAlign=align;ctx.textBaseline="top";ctx.fillStyle="#102255";ctx.fillText(value,x+2,y+2);ctx.fillStyle=color;ctx.fillText(value,x,y)}
function stage(){const ws=S.data?.snapshot?.workflows||[];return ws[0]||null}
function stages(){return stage()?.stages||[]}
function displayedStages(now){const all=stages();if(!S.replayStart||!all.length)return all;const elapsed=now-S.replayStart,count=Math.min(all.length,Math.floor(elapsed/1800)+1);if(count!==S.replayCount){S.replayCount=count;blip(all[count-1]?.kind)}if(elapsed>all.length*1800+900){S.replayStart=0;S.replayCount=0;const button=document.getElementById("replay");button.setAttribute("aria-pressed","false");button.textContent="▶ REPLAY";return all}return all.slice(0,count)}
function cloud(x,y,s){px(x,y+8,50*s,16*s,"#dff7ff");px(x+10*s,y,20*s,22*s,"#fff");px(x+29*s,y+3*s,16*s,18*s,"#f5fdff")}
function hill(x,y,w,h,c){ctx.fillStyle=c;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+w*.5,y-h);ctx.lineTo(x+w,y);ctx.fill();px(x+w*.47,y-h+18,8,8,"#d9f77c");px(x+w*.63,y-h*.35,7,7,"#d9f77c")}
function block(x,y,kind,done,current){const c=done?"#e9972f":"#bb7130";px(x,y,58,45,c);px(x,y,58,6,done?"#ffd34f":"#dc9349");px(x,y+39,58,6,"#713e27");px(x+26,y,6,45,"#8d4d29");if(current){px(x-4,y-4,66,4,"#fff35e");px(x-4,y+45,66,4,"#fff35e")}text(kind,x+29,y+13,13,done?"#fff6ad":"#412515","center")}
function coin(x,y,t){const squash=Math.abs(Math.sin(t))*6+2;px(x-squash/2,y,squash,18,"#ffd84a");px(x-squash/2+2,y+3,Math.max(2,squash-4),12,"#fff39a")}
function pipe(x,y){px(x,y,52,74,"#168f58");px(x-8,y,68,18,"#38d57b");px(x-4,y+4,60,7,"#77f0a7");px(x+37,y+18,9,56,"#0b633e")}
function flag(x,y,raised){px(x,y-128,5,128,"#f7eee1");px(x-4,y-133,13,13,"#ffd84a");const fy=raised?y-118:y-35;px(x+5,fy,58,34,"#ff5b5b");px(x+10,fy+7,12,12,"#fff");px(x+14,fy+10,4,5,"#ff5b5b")}
function avatar(name,x,y,t,active){const c=colors[name],walk=Math.sin(t*7+x)*3,jump=active?Math.abs(Math.sin(t*3))*11:0,yy=y-jump;ctx.save();ctx.translate(Math.round(x),Math.round(yy));px(-10,-54,21,13,c);px(-14,-48,30,7,c);px(-10,-41,22,19,"#ffcf9f");px(7,-36,5,5,"#10162c");px(-9,-22,22,21,c);px(-16,-19,8,15,"#ffcf9f");px(13,-19,8,15,"#ffcf9f");px(-9,-1+walk,8,12,"#19213c");px(5,-1-walk,8,12,"#19213c");ctx.restore();text(name,x,y+14,11,"#fff","center")}
function helper(x,y,c,t,i){const bob=Math.sin(t*2+i)*3;px(x,y-17+bob,11,11,c);px(x-3,y-5+bob,17,11,"#eff7ff");px(x,y-12+bob,3,3,"#091329");px(x+7,y-12+bob,3,3,"#091329")}
function bubble(value,x,y,w){const clean=String(value||"").replace(/\s+/g," ").slice(0,72)||"等待下一条签名消息…";px(x,y,w,58,"#fff7d6");px(x+5,y+5,w-10,48,"#fff");px(x+20,y+58,12,8,"#fff7d6");ctx.fillStyle="#172142";ctx.font="900 12px ui-monospace,monospace";ctx.textAlign="left";ctx.textBaseline="top";const chars=[...clean];let line="",lines=[],limit=Math.max(14,Math.floor(w/13));for(const ch of chars){if(line.length>=limit){lines.push(line);line=""}line+=ch}if(line)lines.push(line);lines.slice(0,2).forEach((s,i)=>ctx.fillText(s,x+10,y+10+i*18))}
function addFx(){for(let i=0;i<30;i++)S.sparkles.push({x:760+Math.random()*90,y:250+Math.random()*120,vx:(Math.random()-.5)*80,vy:-Math.random()*110-30,c:["#ffd84a","#fff7a6","#55ef91","#50ddff"][i%4],life:1+Math.random()})}
function drawFx(dt){S.sparkles=S.sparkles.filter(p=>p.life>0);for(const p of S.sparkles){p.x+=p.vx*dt;p.y+=p.vy*dt;p.vy+=180*dt;p.life-=dt;px(p.x,p.y,6,6,p.c)}}
function draw(now){const t=(now-S.started)/1000,w=960,h=540,workflow=stage(),events=displayedStages(now),last=events[events.length-1],idx=last?Math.max(0,order.indexOf(last.kind)):0,complete=last?.kind==="COMPLETE";ctx.imageSmoothingEnabled=false;px(0,0,w,h,"#49bdf2");px(0,315,w,125,"#75d8f7");cloud((70+t*3)%1050-90,85,1);cloud((540+t*1.7)%1100-100,120,.8);hill(-20,410,260,150,"#62c969");hill(170,410,330,205,"#3fac65");hill(560,410,330,180,"#64c96c");pipe(25,350);flag(895,410,complete);const xs=[150,320,490,660,820];for(let i=0;i<5;i++){block(xs[i]-29,350,`${i+1}`,events.some(e=>e.kind===order[i]),i===idx&&!complete);text(labels[order[i]],xs[i],322,10,"#fff","center");if(events.some(e=>e.kind===order[i]))coin(xs[i],292,t*4+i)}px(0,410,w,40,"#8b5a32");for(let x=0;x<w;x+=32){px(x,410,30,18,"#c3843f");px(x+15,430,30,18,"#a86835")}px(0,450,w,90,"#6d3e27");for(let x=0;x<w;x+=48)px(x,475+(x%96?20:0),25,9,"#855031");const target={Love8:xs[complete?4:Math.min(idx,4)]-38,Aizong:xs[Math.max(1,Math.min(idx,3))],AI2AI:xs[Math.max(2,Math.min(idx,4))]+35};for(const name of Object.keys(S.agents)){const a=S.agents[name];if(!S.paused)a.x+=(target[name]-a.x)*.025;avatar(name,a.x,405,t,owners[order[idx]]===name&&!complete)}const hc=["#e2f14a","#f57bd7","#73f0d1","#ff9f43"];for(let i=0;i<10;i++)helper(90+i*82,405,hc[i%4],t,i);bubble(last?.content,clamp(xs[idx]-125,12,698),190,250);if(complete&&S.sparkles.length===0)addFx();drawFx(1/60);text(complete?"QUEST CLEAR!":workflow?"SIGNED WORKFLOW":"WAITING FOR QUEST",480,35,20,complete?"#fff35e":"#fff","center");if(!S.paused)requestAnimationFrame(draw)}
function blip(kind){if(!S.sound||!audio)return;const osc=audio.createOscillator(),gain=audio.createGain(),freq={WORKFLOW_TASK:330,BUILD_RESULT:392,CHALLENGE:220,REVISED_RESULT:494,COMPLETE:660}[kind]||300;osc.type="square";osc.frequency.value=freq;gain.gain.setValueAtTime(.035,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.001,audio.currentTime+.16);osc.connect(gain).connect(audio.destination);osc.start();osc.stop(audio.currentTime+.17)}
function make(tag,className,value){const node=document.createElement(tag);if(className)node.className=className;if(value!==undefined)node.textContent=String(value);return node}
function formatTime(value){return String(value||"").replace("T"," ").replace(/Z$/,"")+ (value?" UTC":"")}
function renderAgents(workflows){const latest={};for(const wf of workflows)for(const ev of (wf.stages||[])){const old=latest[ev.agent];if(!old||String(ev.ts)>String(old.ts))latest[ev.agent]=ev}for(const card of document.querySelectorAll(".agent-card[data-agent]")){const ev=latest[card.dataset.agent],activity=card.querySelector("[data-activity]"),when=card.querySelector("[data-time]");card.classList.toggle("observed",Boolean(ev));card.classList.toggle("unknown",!ev);activity.textContent=ev?(labels[ev.kind]||ev.kind):"等待签名事件";when.textContent=ev?formatTime(ev.ts):"不代表 Agent 离线"}}
function renderHistory(data){const root=document.getElementById("workflow-history"),workflows=data?.snapshot?.workflows||[],key=JSON.stringify(workflows.map(w=>[w.task_id,w.updated_at,(w.stages||[]).length,w.conflicts]));if(key===S.historyKey){renderAgents(workflows);return}S.historyKey=key;if(!workflows.length){const box=make("div","empty"),title=make("b","","等待第一条可验证工作流"),copy=make("p","","小队会继续巡逻；新签名阶段到达后将自动进入关卡。");box.append(title,copy);root.replaceChildren(box);renderAgents([]);return}const fragment=document.createDocumentFragment();workflows.forEach((wf,index)=>{const details=make("details","workflow");details.open=index===0;const summary=make("summary"),identity=make("span"),task=make("b","",wf.task_id||"未知任务"),updated=make("small","",formatTime(wf.updated_at)),complete=wf.status==="complete",status=make("em",`status ${complete?"complete":"active"}`,complete?"已通关":labels[wf.current_stage]||"等待事件");identity.append(task,updated);summary.append(identity,status);const body=make("div","workflow-body"),quest=make("ol","quest-map"),present=new Set((wf.stages||[]).map(e=>e.kind));quest.setAttribute("aria-label","工作流关卡");order.forEach((kind,i)=>{const item=make("li","quest-step"+(present.has(kind)?" done":"")+(kind===wf.current_stage&&!complete?" current":"")),number=make("span","",i+1),info=make("div"),name=make("b","",labels[kind]),owner=make("small","",owners[kind]);info.append(name,owner);item.append(number,info);quest.append(item)});body.append(quest);if(Number(wf.conflicts)>0)body.append(make("p","warning",`发现 ${wf.conflicts} 个同阶段冲突版本，请人工核对。`));const list=make("section","event-list");list.setAttribute("aria-label","Agent 交流时间线");for(const ev of (wf.stages||[])){const row=make("article","event-row");row.dataset.agent=ev.agent||"";const icon=make("span","event-icon"),content=make("div"),head=make("header"),name=make("b","",ev.agent||"未知 Agent"),meta=make("span","",`${ev.role||"Agent"} · ${labels[ev.kind]||ev.kind||"事件"}`),time=make("time","",formatTime(ev.ts)),copy=make("p","",ev.content||"");icon.setAttribute("aria-hidden","true");head.append(name,meta,time);content.append(head,copy);if(ev.content_truncated)content.append(make("span","truncated","内容已安全截断"));row.append(icon,content);list.append(row)}body.append(list);details.append(summary,body);fragment.append(details)});root.replaceChildren(fragment);renderAgents(workflows)}
function updateHud(data){const snap=data?.snapshot||{},ws=snap.workflows||[],wf=ws[0],ev=wf?.stages||[],last=ev[ev.length-1];document.getElementById("hud-task").textContent=(wf?.task_id||"WAITING").slice(-14);document.getElementById("hud-stage").textContent=`${ev.length} / 5`;document.getElementById("hud-events").textContent=String(ev.length).padStart(3,"0");document.getElementById("observed-at").textContent=snap.observed_at||"等待采集";const key=last?`${wf.task_id}:${last.kind}:${last.ts}`:"";if(key&&S.lastEvent&&key!==S.lastEvent){addFx();blip(last.kind)}S.lastEvent=key}
async function refresh(){try{const res=await fetch("/atlas.json",{cache:"no-store",headers:{Accept:"application/json"}});if(!res.ok)throw new Error("HTTP "+res.status);const data=await res.json();S.data=data;updateHud(data);renderHistory(data);document.getElementById("live-note").textContent=`动态连接正常 · 最近读取 ${new Date().toLocaleTimeString()} · 上游快照约每 30 秒更新`;document.getElementById("live-note").style.borderColor="#43d36f"}catch(_){document.getElementById("live-note").textContent="动态读取暂时失败；保留最后一帧并等待自动重试。";document.getElementById("live-note").style.borderColor="#ffd84a"}}
document.getElementById("replay").addEventListener("click",e=>{if(!stages().length)return;S.replayStart=performance.now();S.replayCount=0;S.sparkles=[];S.agents.Love8.x=90;S.agents.Aizong.x=150;S.agents.AI2AI.x=210;e.currentTarget.setAttribute("aria-pressed","true");e.currentTarget.textContent="● PLAYING"});
document.getElementById("pause").addEventListener("click",e=>{S.paused=!S.paused;e.currentTarget.setAttribute("aria-pressed",String(S.paused));e.currentTarget.textContent=S.paused?"▶":"Ⅱ";if(!S.paused){S.started=performance.now();requestAnimationFrame(draw)}});
document.getElementById("sound").addEventListener("click",e=>{S.sound=!S.sound;if(S.sound){const Audio=window.AudioContext||window.webkitAudioContext;audio=audio||(Audio?new Audio():null);blip(stages().at(-1)?.kind)}e.currentTarget.setAttribute("aria-pressed",String(S.sound));e.currentTarget.textContent=S.sound?"♪ ON":"♪ OFF"});
refresh();setInterval(refresh,10000);requestAnimationFrame(draw);
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
