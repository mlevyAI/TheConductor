#!/usr/bin/env python3
"""
Agent Monitor — Reporter
Called by the Stop hook. Reads activity.jsonl, generates a markdown report
with auto-detected anti-pattern observations, and outputs a systemMessage
JSON so Claude Code shows the report path in the UI.

NEW IN v4: auto-pattern detection. The reporter analyzes each session for
known anti-patterns (probe sprawl, busy-wait, no-forward-progress, repeat-bash,
scope-shrink signals) and pre-fills the "Issues & Patterns to Improve" table.
Empty table only if zero detections.

Privacy: all data stays local. The share-footer is opt-in — it provides a
URL template for users who choose to file an issue, with explicit
"redact paths and secrets first" guidance.
"""

import json
import sys
import os
import re
import datetime
from collections import defaultdict, Counter

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "activity.jsonl")
HOOK_ERRORS_FILE = os.path.join(LOG_DIR, "hook-errors.log")
REPORTS_DIR = os.path.join(LOG_DIR, "reports")

# Configuration — adjust these thresholds if your workload differs
PROBE_FILE_PATTERNS = (
    r"probe[_\d]*\.py$",
    r"scratch[_\d]*\.py$",
    r".+_scratch\.py$",
    r"test_[a-z_]+\.py$",  # ad-hoc test scripts (heuristic)
    r"smoke_[a-z_]+\.py$",
)
PROBE_SPRAWL_THRESHOLD = 3
BUSY_WAIT_PATTERN = re.compile(r"until\s+.+;\s*do\s+sleep\s+\d+|while\s+.+;\s*do\s+sleep\s+\d+")
BUSY_WAIT_THRESHOLD = 2
NO_PROGRESS_CLUSTER_SIZE = 10  # tool calls with 0 Write/Edit
REPEAT_BASH_THRESHOLD = 3
SCOPE_SHRINK_KEYWORDS = (
    "wrap up", "wrap-up", "deliver what", "deliver partial",
    "stop here", "give up on", "scope down", "scope-down",
    "settle for", "good enough", "we'll skip",
)


def load_events():
    if not os.path.exists(LOG_FILE):
        return []
    events = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
    return events


def load_hook_errors():
    """Read hook-errors.log written by logger/heartbeat/usage_limit hooks.
    Surfacing these in the report is the only signal the user gets that a
    hook has been silently failing — without it, a broken logger could run
    for weeks producing empty events."""
    if not os.path.exists(HOOK_ERRORS_FILE):
        return []
    errors = []
    with open(HOOK_ERRORS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    errors.append(json.loads(line))
                except Exception:
                    pass
    return errors


def format_hook_errors_section(errors):
    if not errors:
        return []
    counts = Counter(e.get("hook", "?") for e in errors)
    lines = [
        "## ⚠️ Hook Errors Detected",
        f"_{len(errors)} hook failure(s) since last report._ "
        "These were swallowed at runtime — your monitoring/heartbeat/recovery "
        "hooks were partially or fully broken during the session covered by "
        "this report.",
        "",
        "| Hook | Failure Count |",
        "|------|---------------|",
    ]
    for hook, count in counts.most_common():
        lines.append(f"| `{hook}` | {count} |")
    lines.append("")
    lines.append("**Most recent failures (up to 5):**")
    lines.append("")
    for e in errors[-5:]:
        lines.append(f"- `{e.get('hook', '?')}` at {e.get('ts', '?')} — {str(e.get('error', ''))[:200]}")
    lines.append("")
    return lines


def split_sessions(events):
    """Split flat event list into sessions by session_start markers."""
    sessions = []
    current = []
    for e in events:
        if e.get("event") == "session_start":
            if current:
                sessions.append(current)
            current = [e]
        else:
            current.append(e)
    if current:
        sessions.append(current)
    return sessions


def detect_patterns(session):
    """Return a list of detected anti-patterns: each as
    {observation, impact, suggested_fix}."""
    findings = []
    pre_events = [e for e in session if e.get("event") == "pre_tool"]

    # 1. Probe sprawl — many throwaway research scripts written, never edited
    write_files = [e.get("file", "") for e in pre_events if e.get("tool") == "Write"]
    edit_files = set(e.get("file", "") for e in pre_events if e.get("tool") == "Edit")
    probe_writes = []
    for path in write_files:
        basename = os.path.basename(path or "")
        if any(re.match(pat, basename) for pat in PROBE_FILE_PATTERNS):
            probe_writes.append(path)
    # Filter to only those never re-edited
    probes_never_edited = [p for p in probe_writes if p not in edit_files]
    if len(probes_never_edited) >= PROBE_SPRAWL_THRESHOLD:
        findings.append({
            "observation": f"Probe sprawl detected — {len(probes_never_edited)} throwaway research files written without later edits ({', '.join(os.path.basename(p) for p in probes_never_edited[:5])}{'...' if len(probes_never_edited) > 5 else ''})",
            "impact": "Agent spent budget on research instead of committing to a draft implementation. Likely indicates 'research mode' loop.",
            "suggested_fix": "Apply v4 Investigation Budget rule: after 3 throwaway artifacts, MUST commit to a draft implementation. Iterate against real failures, not in the abstract.",
        })

    # 2. Busy-wait — until/sleep loops
    bash_cmds = [e.get("cmd", "") for e in pre_events if e.get("tool") == "Bash"]
    busy_waits = [c for c in bash_cmds if BUSY_WAIT_PATTERN.search(c)]
    if len(busy_waits) >= BUSY_WAIT_THRESHOLD:
        findings.append({
            "observation": f"Busy-wait loops detected — {len(busy_waits)} bash commands using `until ...; do sleep N; done` or similar",
            "impact": "Agent burned turns/tokens blocking on conditions that could have been polled with ScheduleWakeup or file-mtime checks. Zero forward progress during waits.",
            "suggested_fix": "v4 Forbidden Bash Patterns rule bans busy-wait loops. Use ScheduleWakeup for time-based polling, mtime checks for event-based polling, or a heartbeat file for backgrounded tasks.",
        })

    # 3. No-forward-progress cluster — long stretch of tool calls with 0 Write/Edit
    cluster_size = 0
    max_cluster = 0
    for e in pre_events:
        if e.get("tool") in ("Write", "Edit", "NotebookEdit"):
            max_cluster = max(max_cluster, cluster_size)
            cluster_size = 0
        else:
            cluster_size += 1
    max_cluster = max(max_cluster, cluster_size)
    if max_cluster >= NO_PROGRESS_CLUSTER_SIZE:
        findings.append({
            "observation": f"No-forward-progress cluster — {max_cluster} consecutive tool calls without any Write/Edit",
            "impact": "Agent was reading/researching/diagnosing without producing output. Could indicate stuck-in-discovery, status-polling loop, or analysis paralysis.",
            "suggested_fix": "Force a draft commit after N read-only operations. If genuinely diagnosing, capture findings to a file (which IS a Write) so progress is observable.",
        })

    # 4. Repeat-bash — identical command run multiple times
    bash_counter = Counter(bash_cmds)
    repeats = [(cmd, count) for cmd, count in bash_counter.items() if count >= REPEAT_BASH_THRESHOLD]
    if repeats:
        # Show top offender
        top_cmd, top_count = max(repeats, key=lambda x: x[1])
        preview = top_cmd[:120].replace("\n", " ")
        findings.append({
            "observation": f"Repeat-bash detected — `{preview}...` ran {top_count} times" + (f" (and {len(repeats)-1} other repeated command(s))" if len(repeats) > 1 else ""),
            "impact": "Identical commands run repeatedly often indicate a stuck-check loop or polling that should be event-driven.",
            "suggested_fix": "Pause when you notice yourself running the same command 3+ times. Ask: am I stuck? Is there a different angle? If polling state, switch to ScheduleWakeup or file-mtime check.",
        })

    # 5. Scope-shrink signals — keywords in agent prompts indicating reducing scope
    agent_prompts = [
        e.get("prompt_preview", "") for e in pre_events if e.get("tool") == "Agent"
    ]
    shrink_hits = []
    for p in agent_prompts:
        p_lower = p.lower()
        for kw in SCOPE_SHRINK_KEYWORDS:
            if kw in p_lower:
                shrink_hits.append((kw, p[:120]))
                break
    if shrink_hits:
        findings.append({
            "observation": f"Scope-shrink signals detected — {len(shrink_hits)} agent dispatches using language like {sorted(set(kw for kw, _ in shrink_hits))}",
            "impact": "Agent likely auto-shrunk scope to fit perceived time/budget pressure rather than delivering partial output and continuing.",
            "suggested_fix": "v4 anti-shrinkage clause: deliver partial output (rolling save / partial Excel / partial DB write) and CONTINUE. The user gets more value from 200 partial than 55 complete.",
        })

    return findings


def format_findings_table(findings):
    if not findings:
        return [
            "## Issues & Patterns to Improve",
            "_No anti-patterns auto-detected in this session._",
            "_(Manually add observations below if you noticed something the auto-detector missed.)_",
            "",
            "| # | Observation | Impact | Suggested Fix |",
            "|---|-------------|--------|---------------|",
            "| 1 | | | |",
            "",
        ]
    lines = [
        "## Issues & Patterns to Improve",
        f"_{len(findings)} anti-pattern(s) auto-detected in this session._",
        "",
        "| # | Observation | Impact | Suggested Fix |",
        "|---|-------------|--------|---------------|",
    ]
    for i, f in enumerate(findings, 1):
        # Markdown table cells: replace pipe and newline to keep table valid
        obs = f["observation"].replace("|", "\\|").replace("\n", " ")
        imp = f["impact"].replace("|", "\\|").replace("\n", " ")
        fix = f["suggested_fix"].replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i} | {obs} | {imp} | {fix} |")
    lines.append("")
    return lines


def format_session(session: list, idx: int) -> str:
    lines = []
    start_ts = session[0].get("ts", "?")
    end_ts = session[-1].get("ts", "?")

    tool_events = [e for e in session if e.get("event") in ("pre_tool", "post_tool")]
    pre_events = [e for e in tool_events if e.get("event") == "pre_tool"]

    tool_counts = Counter(e.get("tool", "?") for e in pre_events)
    bash_cmds = [e.get("cmd", "") for e in pre_events if e.get("tool") == "Bash"]
    files_written = [e.get("file", "") for e in pre_events if e.get("tool") == "Write"]
    files_edited = [e.get("file", "") for e in pre_events if e.get("tool") == "Edit"]
    files_read = [e.get("file", "") for e in pre_events if e.get("tool") == "Read"]
    agents_spawned = [e for e in pre_events if e.get("tool") == "Agent"]
    skills_used = [e.get("skill", "") for e in pre_events if e.get("tool") == "Skill"]
    web_searches = [e.get("query", "") for e in pre_events if e.get("tool") == "WebSearch"]
    failures = [e for e in tool_events if e.get("event") == "post_tool" and e.get("success") is False]

    lines.append(f"## Session {idx + 1}")
    lines.append(f"- **Start:** {start_ts}")
    lines.append(f"- **End:** {end_ts}")
    lines.append(f"- **Total tool calls:** {len(pre_events)}")
    lines.append("")

    if tool_counts:
        lines.append("### Tool Usage")
        lines.append("| Tool | Count |")
        lines.append("|------|-------|")
        for tool, count in tool_counts.most_common():
            lines.append(f"| {tool} | {count} |")
        lines.append("")

    if agents_spawned:
        lines.append("### Agents Spawned")
        for a in agents_spawned:
            bg = " *(background)*" if a.get("background") else ""
            lines.append(f"- **{a.get('subagent_type', 'general-purpose')}**{bg}: {a.get('description', '')}")
            if a.get("prompt_preview"):
                lines.append(f"  > {a['prompt_preview'][:200]}...")
        lines.append("")

    if bash_cmds:
        lines.append("### Bash Commands Executed")
        for cmd in bash_cmds:
            lines.append(f"```\n{cmd}\n```")
        lines.append("")

    if files_written:
        lines.append("### Files Written")
        for f in files_written:
            lines.append(f"- `{f}`")
        lines.append("")

    if files_edited:
        lines.append("### Files Edited")
        for f in sorted(set(files_edited)):
            lines.append(f"- `{f}`")
        lines.append("")

    if files_read:
        lines.append("### Files Read")
        for f in sorted(set(files_read)):
            lines.append(f"- `{f}`")
        lines.append("")

    if skills_used:
        lines.append("### Skills Invoked")
        for s in skills_used:
            lines.append(f"- `{s}`")
        lines.append("")

    if web_searches:
        lines.append("### Web Searches")
        for q in web_searches:
            lines.append(f"- {q}")
        lines.append("")

    if failures:
        lines.append("### ⚠️ Failures")
        for e in failures:
            lines.append(f"- **{e.get('tool')}**: {e.get('error', 'unknown error')[:200]}")
        lines.append("")

    return "\n".join(lines)


def share_footer():
    """Opt-in share footer (v4.0.1: structured contribution template).

    Maintainers cannot judge whether an auto-detected pattern was bad-in-context
    without knowing what the user was trying to do. So the footer prompts the
    user to fill 5 short fields BEFORE pasting the raw report — shifting
    contributions from 'tool-call dumps' to 'structured incident reports'
    that are actually actionable.
    """
    return [
        "---",
        "## 📤 Share this report with project-conductor maintainers",
        "",
        "Found a useful pattern, a regression, or a new failure mode worth documenting?",
        "**Copy the template below, fill the 5 fields, then open an issue:**",
        "",
        "```",
        "https://github.com/<your-fork>/project-conductor/issues/new?title=Agent+session+report",
        "```",
        "",
        "### Contribution template (paste into the issue body, fill the brackets)",
        "",
        "````markdown",
        "## What I was trying to do",
        "[1-2 sentences. The agent's task / the spec / what success would look like.]",
        "",
        "## Did the agent succeed?",
        "- [ ] Yes, fully",
        "- [ ] Partially (explain: ...)",
        "- [ ] No (explain: ...)",
        "",
        "## Which auto-detected patterns were bad-in-context vs neutral?",
        "For each row in the report's 'Issues & Patterns to Improve' table, mark BAD / NEUTRAL / FALSE-POSITIVE and add 1 line of why.",
        "",
        "Example:",
        "- Probe sprawl (3 files): BAD — agent never committed to a draft, kept researching.",
        "- Repeat-bash (`tail -f log` × 8): NEUTRAL — I was waiting on a long scrape, no clean alternative.",
        "- No-progress cluster (12 reads): FALSE-POSITIVE — I was reviewing code, not stuck.",
        "",
        "## What should the agent have done instead?",
        "[Optional but high value. If you know, write it. If you don't, leave blank — the maintainers will analyze.]",
        "",
        "## Anything else (new pattern the auto-detector missed, environment quirks, etc.)",
        "[Optional.]",
        "",
        "## Raw session report (redact before pasting!)",
        "[Paste the rest of this report below.]",
        "````",
        "",
        "### Before pasting, redact:",
        "- Absolute file paths (`/Users/.../`, `/home/.../`)",
        "- Environment-specific URLs, internal hostnames, API endpoints with credentials",
        "- Any tokens, keys, passwords accidentally captured in bash output",
        "- Project-identifying names if confidential",
        "",
        "**Why this template:** without 'what you were trying to do' and 'was this bad-in-context', maintainers can't judge whether a flagged pattern is actually a problem or just an observation. Filling the 5 fields takes ~2 minutes and makes the difference between an actionable report and a tool-call dump.",
        "",
    ]


def generate_report(events: list) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    sessions = split_sessions(events)

    lines = [
        "# Project-Conductor Agent Monitoring Report",
        f"Generated: {now}",
        f"Total sessions in log: {len(sessions)}",
        f"Total events: {len(events)}",
        "",
        "---",
        "",
    ]

    all_pre = [e for e in events if e.get("event") == "pre_tool"]
    all_tool_counts = Counter(e.get("tool", "?") for e in all_pre)
    all_failures = [e for e in events if e.get("event") == "post_tool" and e.get("success") is False]

    lines.append("## Overall Summary")
    lines.append(f"- **Total tool calls:** {len(all_pre)}")
    lines.append(f"- **Total failures:** {len(all_failures)}")
    if all_tool_counts:
        top = ", ".join(f"{t}({c})" for t, c in all_tool_counts.most_common(5))
        lines.append(f"- **Top tools:** {top}")
    lines.append("")

    # Surface hook failures BEFORE anti-pattern analysis: if the logger
    # itself was broken, the anti-pattern findings below are based on
    # incomplete data and the user needs to know.
    hook_errors = load_hook_errors()
    lines.extend(format_hook_errors_section(hook_errors))

    # Aggregate auto-detection across all sessions
    all_findings = []
    for session in sessions:
        all_findings.extend(detect_patterns(session))
    lines.extend(format_findings_table(all_findings))

    lines.append("---")
    lines.append("")

    for i, session in enumerate(sessions):
        lines.append(format_session(session, i))
        lines.append("---")
        lines.append("")

    lines.extend(share_footer())

    return "\n".join(lines)


def main():
    # Read (and discard) Stop hook stdin
    try:
        sys.stdin.read()
    except Exception:
        pass

    events = load_events()
    if not events:
        print(json.dumps({"systemMessage": "[Agent Monitor] No activity logged yet."}))
        return

    report = generate_report(events)

    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_path = os.path.join(REPORTS_DIR, f"report_{ts}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    # Truncate the raw log after archiving to keep it clean for next session
    open(LOG_FILE, "w").close()
    # Same for hook-errors: once surfaced in the report, drop them so a
    # one-off failure doesn't keep showing up in every future report.
    if os.path.exists(HOOK_ERRORS_FILE):
        open(HOOK_ERRORS_FILE, "w").close()

    print(json.dumps({
        "systemMessage": f"[Agent Monitor] Report saved → {report_path}"
    }))


if __name__ == "__main__":
    main()
