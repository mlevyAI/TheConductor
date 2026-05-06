---
name: conductor-classification
description: Classify an emergent issue surfaced during execution as Hard Stop, Critical, In-Scope, Out-of-Scope, or Scope Expansion. Hard Stops always override; Anti-Premature-Failure rule prevents declaring impossibility after fewer than 3 distinct attempts.
allowed-tools: Read
---

## When to invoke

The conductor invokes this skill whenever an emergent issue surfaces during task execution — a failure mode discovered mid-implementation, an unexpected API behavior, a missing capability, etc. The skill returns a classification and a recommended next action.

## Inputs

- A description of the emergent issue (what was tried, what happened, what's blocking)
- The current task's enriched spec block (for in-scope determination)
- `.conductor/findings.md` — prior emergent issues this session (for "same type 3+ times" detection)
- `.conductor/decisions.md` — prior architectural choices

## Outputs

- A classification: one of `hard_stop`, `critical`, `in_scope`, `out_of_scope`, `scope_expansion`
- A recommended next action: `iterate`, `fix_and_log`, `log_only`, `pause_and_surface`, `interrupt`
- A row appended to `.conductor/findings.md`
- For Hard Stops: a row appended to `.conductor/decisions.md` and a user-facing message

## Procedure

1. **Hard Stop precedence check (in order).** Hard Stops ALWAYS override emergent classification. If any of the following apply, return `hard_stop`:

   1. Missing credentials/secrets/API keys (blocked, can't proceed)
   2. Production data or environment changes (irreversible)
   3. New runtime dependency not in spec **AND** not a peer-replacement for an in-spec dependency (e.g., adding Postgres when spec said SQLite = Hard Stop; switching from `requests` to `playwright_stealth` to handle Cloudflare = NOT a Hard Stop, that's implementation iteration)
   4. Architectural decisions not in spec — *clarification:* an architectural decision affects MULTIPLE components OR introduces a NEW SYSTEM-LEVEL dependency (database, message queue, deployment target, auth provider). Adjusting one component's transport, parsing technique, retry strategy, or stealth layer is implementation-level iteration — NOT architectural.
   5. Security-sensitive decisions
   6. Irreversible operations
   7. 3 failed attempts on same task (after Phase 3 retry policy exhausted; surface, don't auto-escalate)
   8. Critical emergent issues (specifically: data loss risk, security breach risk, billing risk)
   9. Lock violation in parallel execution (any file written outside declared set)
   10. Spec enrichments not yet approved by user (cannot enter Phase 2)
   11. Canary model check failed (suspected model parameter ignored)
   12. Permissions sanity test failed (settings.json syntax did not apply)

2. **Decision framework (only reached if no Hard Stop applies):**
   1. Blocks goal? → `critical`
   2. In spec's area? → `in_scope`
   3. Hurts goal's user? → `scope_expansion`
   4. Otherwise → `out_of_scope`

3. **Anti-Premature-Failure rule.** Before declaring a capability impossible, unsearchable, unscrapable, unreachable, or otherwise unworkable, you MUST attempt at least 3 distinct approaches. "I tried twice" is not sufficient.

   **Three distinct approaches (concrete examples):**
   - Alternative URL/endpoint shapes (`/search/?q=X`, `/api/v1/X`, mobile subdomain, sitemap.xml, robots.txt)
   - Network-inspection patterns (XHR/fetch calls the page makes, GraphQL endpoints, etc.)
   - Alternative client signals (mobile UA, RSS/atom, JSON-LD microdata, OpenGraph)

   **Documentation rules:**
   - Failures get logged to `.conductor/findings.md` as `unverified — N approaches tried: [list]` — never as `impossible` or `known limitation`.
   - The phrase **"KNOWN LIMITATION"** is BANNED in production code comments shipped by the conductor. Document approaches tried; leave the door open.
   - If a 3rd approach succeeds, log to `.conductor/decisions.md`: `Found [approach] for [resource] after [N] failed attempts`.

4. **Interrupt despite classification if any of these apply:**
   - Fix is >3x estimated time
   - Requires new dependency (Hard Stop, see #1.3 above)
   - Affects production (Hard Stop)
   - Requires architectural decision (Hard Stop)
   - Same type of issue 3+ times this session (read findings.md for repeat patterns)

5. **Learning loop.** After fixing an in-scope issue: ask "Systematic spec gap?". If yes, enrich similar future tasks, document, include in final report.

6. **Append findings.md row** in this format:
   ```
   [timestamp] classification=<class> action=<next_action>
   issue: <one-line summary>
   approaches_tried: [list, if Anti-Premature-Failure applies]
   ```

## Examples

```xml
<examples>
  <example>
    <issue>Site lego.com/de-de blocks plain `requests.get` with Cloudflare. Tried twice with different headers; both blocked.</issue>
    <classification>
      class: in_scope
      action: iterate
      reason: implementation iteration (different HTTP technique). NOT a Hard Stop — adjusting transport is not architectural.
      anti-premature-failure: only 2 attempts so far; switch to Playwright as approach #3 before declaring failure.
    </classification>
  </example>
  <example>
    <issue>Spec calls for SQLite. Migration script fails because the schema needs PostgreSQL window functions.</issue>
    <classification>
      class: hard_stop
      action: pause_and_surface
      reason: switching DB engine = new system-level dependency. NOT implementation iteration.
      hard_stop_reason: #3 (new runtime dependency not in spec)
    </classification>
  </example>
  <example>
    <issue>Task succeeds but produces an output CSV where one column is 100% empty.</issue>
    <classification>
      class: critical
      action: pause_and_surface
      reason: broken-component pattern detected by output-quality skill. Output exists but data is missing — completion report must NOT mark task done until investigated.
    </classification>
  </example>
</examples>
```

## Failure modes

- **Issue cannot be unambiguously classified** (multiple categories apply with equal weight) → default to the more cautious side (Hard Stop > Critical > In-Scope > Scope Expansion > Out-of-Scope). Surface the ambiguity in findings.md.
- **Findings.md unreadable** when checking for repeat patterns → log the read failure; classify based on the current issue alone; flag as known-limitation in this session's final report.
- **A "Hard Stop" is returned but the issue does NOT match any of the 12 enumerated reasons** → re-classify; spurious Hard Stops violate the user's autonomy. The 12 reasons are exhaustive.
- **Anti-Premature-Failure rule is violated** (you're about to write `# KNOWN LIMITATION` after <3 attempts) → STOP, regenerate the classification with the additional attempt(s) executed first.
