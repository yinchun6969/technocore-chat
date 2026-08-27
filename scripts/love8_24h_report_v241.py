#!/usr/bin/env python3
"""Read-only 24h activity report for Love8 Persistent Agent v2.4.1."""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path('/opt/love8-agent')
STATE = ROOT / 'state'
MEMORY = ROOT / 'memory'
SOCIAL_STATE = STATE / 'social-v2.json'
BRAIN_STATE = STATE / 'brain-v22.json'
PERSIST_STATE = STATE / 'persistent-v24.json'
SIGNED_WRITES = STATE / 'signed-writes-v241.jsonl'
EVENT_SCOUT = STATE / 'event-scout-v241.json'
UPSTREAM_SCOUT = STATE / 'upstream-scout-v241.json'
MEMORY_STATE = MEMORY / 'state.json'
EVENTS = MEMORY / 'events'
CONTACTS = MEMORY / 'contacts'

NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(hours=24)
CUTOFF_EPOCH = CUTOFF.timestamp()


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open('r', encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                x = json.loads(line)
                if isinstance(x, dict):
                    yield x
            except Exception:
                continue


def iso_epoch(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value or '').strip()
    if not s:
        return 0.0
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0.0


def short(s: Any, n: int = 96) -> str:
    text = ' '.join(str(s or '').split())
    return text if len(text) <= n else text[:n-1] + '…'


def in24_epoch(v: Any) -> bool:
    try:
        return float(v or 0) >= CUTOFF_EPOCH
    except Exception:
        return False


def print_header(title: str):
    print('\n' + '=' * 68)
    print(title)
    print('=' * 68)


def memory_events_24h():
    rows = []
    months = {CUTOFF.strftime('%Y-%m'), NOW.strftime('%Y-%m')}
    for month in sorted(months):
        p = EVENTS / f'{month}.jsonl'
        for rec in read_jsonl(p) or []:
            if iso_epoch(rec.get('ts')) >= CUTOFF_EPOCH:
                rows.append(rec)
    rows.sort(key=lambda x: iso_epoch(x.get('ts')))
    return rows


def main() -> int:
    social = load_json(SOCIAL_STATE, {})
    brain = load_json(BRAIN_STATE, {})
    persist = load_json(PERSIST_STATE, {})
    mem_state = load_json(MEMORY_STATE, {})
    event_state = load_json(EVENT_SCOUT, {})
    upstream = load_json(UPSTREAM_SCOUT, {})
    mem_events = memory_events_24h()

    print('===== LOVE8 v2.4.1 — LAST 24 HOURS =====')
    print('window_utc:', CUTOFF.isoformat(), '->', NOW.isoformat())
    print('local_source_of_truth:', MEMORY)

    # Brain decisions
    decisions = []
    for d in brain.get('decisions', []) if isinstance(brain, dict) and isinstance(brain.get('decisions'), list) else []:
        if isinstance(d, dict) and in24_epoch(d.get('ts')):
            decisions.append(d)
    actions = Counter(str(d.get('action', 'unknown')) for d in decisions)
    sent_decisions = [d for d in decisions if d.get('sent')]
    bots = [int(d.get('bot_probability', 0) or 0) for d in decisions]
    risks = [int(d.get('scam_risk', 0) or 0) for d in decisions]
    qualities = [int(d.get('conversation_quality', 0) or 0) for d in decisions]

    print_header('1. DEEP BRAIN')
    print('decisions_24h:', len(decisions))
    print('actions:', dict(actions))
    print('decisions_marked_sent:', len(sent_decisions))
    if decisions:
        print('avg_bot_probability:', round(sum(bots)/len(bots), 1))
        print('avg_scam_risk:', round(sum(risks)/len(risks), 1))
        print('avg_conversation_quality:', round(sum(qualities)/len(qualities), 1))
    for d in decisions[-8:]:
        ts = datetime.fromtimestamp(float(d.get('ts', 0) or 0), tz=timezone.utc).strftime('%m-%d %H:%M') if d.get('ts') else '-'
        print(f"  {ts} action={d.get('action')} sent={bool(d.get('sent'))} bot={d.get('bot_probability','-')} human={d.get('human_likelihood','-')} risk={d.get('scam_risk','-')} q={d.get('conversation_quality','-')} room={d.get('room','-')} reason={short(d.get('reason'),110)}")

    # Signed writes are strongest record of actual public writes.
    writes = []
    for rec in read_jsonl(SIGNED_WRITES) or []:
        if iso_epoch(rec.get('observed_at')) >= CUTOFF_EPOCH:
            writes.append(rec)
    room_counts = Counter(str(x.get('room', '-')) for x in writes)
    print_header('2. ACTUAL SIGNED TECHNOCORE WRITES')
    print('signed_writes_24h:', len(writes))
    print('rooms:', dict(room_counts.most_common(12)))
    for x in writes[-12:]:
        print(f"  {x.get('observed_at','-')} seq={x.get('observed_seq','-')} room={x.get('room','-')} text={short(x.get('text'),140)}")

    # Social state write budget timestamps can include successful public writes before proof capture existed.
    social_writes = [x for x in social.get('writes', []) if in24_epoch(x)] if isinstance(social, dict) and isinstance(social.get('writes'), list) else []
    print('social_write_budget_entries_24h:', len(social_writes))

    # Relationships current + contact memory changes in last 24h.
    contacts = social.get('contacts', {}) if isinstance(social, dict) and isinstance(social.get('contacts'), dict) else {}
    stages = Counter(str(c.get('relationship_stage', c.get('stage', 'candidate'))) for c in contacts.values() if isinstance(c, dict))
    contact_events = [e for e in mem_events if e.get('kind') == 'contact_memory']
    touched_contacts = {str(e.get('subject')) for e in contact_events}
    stage_changes = Counter()
    for e in contact_events:
        data = e.get('data', {}) if isinstance(e.get('data'), dict) else {}
        stage_changes[str(data.get('stage', 'unknown'))] += 1
    print_header('3. RELATIONSHIPS & PERMANENT MEMORY')
    print('current_relationship_stages:', dict(stages))
    print('contacts_touched_24h:', len(touched_contacts))
    print('contact_memory_events_24h:', len(contact_events))
    print('contact_event_stage_snapshots:', dict(stage_changes))
    print('permanent_contacts_total:', len(list(CONTACTS.glob('*.json'))) if CONTACTS.exists() else 0)
    print('memory_events_24h:', len(mem_events))
    print('memory_event_kinds_24h:', dict(Counter(str(e.get('kind','unknown')) for e in mem_events).most_common()))
    print('memory_head:', load_json(MEMORY / 'index.json', {}).get('head', '-'))

    # Topics observed during the window.
    topic_events = [e for e in mem_events if e.get('kind') == 'topic_observation']
    topic_scores: dict[str, float] = defaultdict(float)
    topic_peers: dict[str, int] = defaultdict(int)
    for e in topic_events:
        topic = str(e.get('subject', '') or '')
        data = e.get('data', {}) if isinstance(e.get('data'), dict) else {}
        topic_scores[topic] = max(topic_scores[topic], float(data.get('momentum', 0) or 0))
        topic_peers[topic] = max(topic_peers[topic], int(data.get('peer_count', 0) or 0))
    print_header('4. TOPICS')
    print('topic_observations_24h:', len(topic_events))
    for topic, score in sorted(topic_scores.items(), key=lambda kv: kv[1], reverse=True)[:12]:
        print(f'  momentum={score:6.2f} peers={topic_peers[topic]:3d} topic={topic}')

    # Contribution records created by persistent core.
    contributions = []
    for c in persist.get('contributions', []) if isinstance(persist, dict) and isinstance(persist.get('contributions'), list) else []:
        if isinstance(c, dict) and in24_epoch(c.get('ts')):
            contributions.append(c)
    print_header('5. USEFUL CONTRIBUTIONS')
    print('contributions_24h:', len(contributions))
    if contributions:
        print('avg_contribution_score:', round(sum(int(c.get('score',0) or 0) for c in contributions)/len(contributions), 1))
    for c in contributions[-12:]:
        print(f"  score={c.get('score','-')} action={c.get('action','-')} room={c.get('room','-')} target={c.get('target','-')} reason={short(c.get('reason'),120)}")

    # Event Scout: rooms first observed within the last 24h.
    rooms_24 = []
    for x in event_state.get('rooms', []) if isinstance(event_state, dict) and isinstance(event_state.get('rooms'), list) else []:
        if isinstance(x, dict) and in24_epoch(x.get('seen_at')):
            rooms_24.append(x)
    print_header('6. /r/events DISCOVERY')
    print('event_cursor:', event_state.get('cursor', '-'))
    print('new_public_rooms_seen_24h:', len(rooms_24))
    for x in rooms_24[-12:]:
        print(f"  event_seq={x.get('event_seq','-')} room={x.get('room','-')} seen_at={x.get('seen_at','-')}")

    # GitHub upstream scout current queue, plus memory events observed in the window.
    gh_candidates = [e for e in mem_events if e.get('kind') == 'github_contribution_candidate']
    upstream_heads = [e for e in mem_events if e.get('kind') == 'upstream_head_observed']
    print_header('7. OFFICIAL GITHUB SCOUT')
    print('latest_commit_sha:', upstream.get('latest_commit_sha', '-'))
    print('upstream_head_observations_24h:', len(upstream_heads))
    print('new_candidate_memory_events_24h:', len(gh_candidates))
    for c in upstream.get('candidates', [])[:8] if isinstance(upstream, dict) and isinstance(upstream.get('candidates'), list) else []:
        print(f"  score={c.get('score','-')} issue=#{c.get('number','-')} {short(c.get('title'),90)}")

    # Provenance / anchor.
    print_header('8. PROVENANCE / ANCHOR')
    print('canonical_ledger:', mem_state.get('last_canonical_ledger', '-'))
    print('last_sync:', mem_state.get('last_sync_at', '-'))
    print('last_anchor_date:', mem_state.get('last_anchor_date', '-'))
    print('last_anchor_room:', mem_state.get('last_anchor_room', '-'))
    print('last_anchor_seq:', mem_state.get('last_anchor_seq', '-'))
    print('last_anchor_error:', mem_state.get('last_anchor_error', '-'))

    print_header('9. QUICK VERDICT')
    print(f"Brain thought {len(decisions)} times; actual signed public writes={len(writes)}; useful contributions={len(contributions)}; new rooms discovered={len(rooms_24)}; contacts touched={len(touched_contacts)}.")
    if writes:
        print('Most active write rooms:', ', '.join(f'{r}({n})' for r,n in room_counts.most_common(5)))
    if contributions:
        top = max(contributions, key=lambda c: int(c.get('score',0) or 0))
        print(f"Best contribution: score={top.get('score')} room={top.get('room','-')} reason={short(top.get('reason'),140)}")
    print('This report is read-only; it does not post, modify memory, or call the model.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
