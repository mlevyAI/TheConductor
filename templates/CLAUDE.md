# {{PROJECT_NAME}}

Project-level AI coding configuration. This file governs how AI assistants work within this codebase.

## Project Context

- **Stack:** {{STACK}}
- **Primary language:** {{LANG_PRIMARY}}
- **Text direction:** {{TEXT_DIRECTION}}
- **Auth model:** {{AUTH_MODEL}}

## Sprint Scope

Current sprint/phase is defined in `.claude/current-phase.md`. Read it before starting any task to understand what is in scope and what is explicitly out of scope.

## Style

- Write all code in `{{LANG_PRIMARY}}`.
- Text direction is `{{TEXT_DIRECTION}}`. Layout, flex/grid direction, and RTL/LTR utility classes must respect this throughout.
- Prefer explicit over clever. Optimize for readability first, performance second.

## Auth

Auth model: `{{AUTH_MODEL}}`. All protected routes and API endpoints must enforce this model. Never roll custom auth primitives — use the project's designated auth library/middleware.

## Compact Instructions

**Preserve:** architecture decisions in `.claude/architecture.md` (if present), security constraints, current sprint scope (`.claude/current-phase.md`), acceptance criteria for in-flight work, deploy commands, environment-specific paths, this section.

**Discard:** file contents already written to disk, completed debugging sessions, tool output that has been acted on, long agent transcripts that produced summarized results, read-only exploration that informed a decision already recorded.

## General Rules

- Check `.claude/rules/` for domain-specific rules (frontend, api, tests) before starting work.
- Do not modify production environment config files without explicit user approval.
- Run the project's lint/test command after any non-trivial edit.
- When uncertain about scope, re-read `.claude/current-phase.md` before asking.
