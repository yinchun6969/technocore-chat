#!/usr/bin/env python3
"""Love8 v2.4.1 read-only upstream contribution scout.

Observes flop-labs/technocore-chat issues and commits, ranks reproducible/focused
contribution candidates, and writes only local state. It never comments, opens an
issue, pushes a branch, or creates a PR.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

VERSION = "2.4.1"
REPO = "flop-labs/technocore-chat"
STATE = Path("/opt/love8-agent/state/upstream-scout-v241.json")
API = "https://api.github.com/repos/" + REPO


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": f"love8-upstream-scout/{VERSION}"})
    with urllib.request.urlopen(req, timeout=35) as r:
        return json.loads(r.read().decode("utf-8"))


def save(data: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True); STATE.parent.chmod(0o700)
    tmp = STATE.with_suffix(".tmp"); tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); tmp.chmod(0o600); os.replace(tmp, STATE)


def load() -> dict[str, Any]:
    try:
        d = json.loads(STATE.read_text(encoding="utf-8")); return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def score_issue(issue: dict[str, Any]) -> tuple[int, list[str]]:
    title = str(issue.get("title", "") or "")
    body = str(issue.get("body", "") or "")
    text = (title + "\n" + body).lower()
    score = 15; reasons: list[str] = []
    signals = [
        (r"\b(repro|reproduce|reproduction|fails?|failure|regression|flake|race|bug)\b", 18, "repro/bug signal"),
        (r"\b(test|pytest|assert|coverage|mutation)\b", 12, "test evidence"),
        (r"\b(benchmark|ms\b|%|performance|perf|latency|throughput)\b", 12, "measured performance"),
        (r"\b(security|replay|signature|did:key|nonce|base58|auth)\b", 10, "protocol/security surface"),
        (r"```", 8, "code/reproduction block"),
        (r"\b(suggested fix|root cause|impact)\b", 8, "analysis present"),
    ]
    for pattern, points, why in signals:
        if re.search(pattern, text, re.I): score += points; reasons.append(why)
    comments = int(issue.get("comments", 0) or 0)
    if comments <= 3: score += 4; reasons.append("low coordination load")
    if len(body) >= 600: score += 5; reasons.append("detailed report")
    if len(body) < 80: score -= 15; reasons.append("thin report")
    labels = [str(x.get("name", "")).lower() for x in issue.get("labels", []) if isinstance(x, dict)]
    if any("good first" in x or "help wanted" in x for x in labels): score += 10; reasons.append("maintainer invitation")
    return max(0, min(score, 100)), reasons[:8]


def run() -> int:
    issues_raw = get_json(API + "/issues?state=open&sort=updated&direction=desc&per_page=40")
    commits_raw = get_json(API + "/commits?per_page=12")
    issues = []
    for item in issues_raw if isinstance(issues_raw, list) else []:
        if not isinstance(item, dict) or item.get("pull_request"): continue
        score, reasons = score_issue(item)
        issues.append({
            "number": int(item.get("number", 0) or 0), "title": str(item.get("title", ""))[:240],
            "html_url": str(item.get("html_url", ""))[:500], "updated_at": item.get("updated_at"),
            "created_at": item.get("created_at"), "comments": int(item.get("comments", 0) or 0),
            "score": score, "reasons": reasons,
        })
    issues.sort(key=lambda x: (x["score"], x.get("updated_at") or ""), reverse=True)
    commits = commits_raw if isinstance(commits_raw, list) else []
    latest = commits[0] if commits and isinstance(commits[0], dict) else {}
    sha = str(latest.get("sha", "") or "")
    url = str(latest.get("html_url", "") or "")
    previous = load()
    data = {
        "version": VERSION, "repo": REPO, "updated_at": int(time.time()),
        "latest_commit_sha": sha, "latest_commit_url": url,
        "latest_commit_message": str(((latest.get("commit") or {}).get("message", "") if isinstance(latest.get("commit"), dict) else ""))[:500],
        "candidates": issues[:15],
        "previous_latest_commit_sha": previous.get("latest_commit_sha"),
        "policy": "read-only research; never auto-open issue/PR; reproduce+test locally before operator review",
    }
    save(data)
    print(f"upstream_scout head={sha[:12]} candidates={len(data['candidates'])}")
    for x in data["candidates"][:8]: print(f"score={x['score']:3d} issue=#{x['number']} {x['title']}")
    return 0


def status() -> int:
    d = load(); print("===== LOVE8 UPSTREAM SCOUT v2.4.1 =====")
    print("repo:", d.get("repo", REPO)); print("latest_commit:", d.get("latest_commit_sha", "-")); print("updated_at:", d.get("updated_at", "-"))
    for x in d.get("candidates", [])[:15] if isinstance(d.get("candidates"), list) else []:
        if isinstance(x, dict): print(f"score={int(x.get('score',0)):3d} issue=#{x.get('number')} {x.get('title')} reasons={','.join(x.get('reasons',[])[:4])}")
    return 0


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--once",action="store_true"); p.add_argument("--status",action="store_true"); p.add_argument("--version",action="version",version=f"%(prog)s {VERSION}")
    a=p.parse_args(); return status() if a.status else run()


if __name__ == "__main__": raise SystemExit(main())
