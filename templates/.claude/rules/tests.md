# Testing Rules

**Primary language:** {{LANG_PRIMARY}}

## Mandate

Follow red-green-refactor TDD for all new features and bug fixes:
1. Write a failing test that describes the desired behavior.
2. Write the minimum production code to make it pass.
3. Refactor — clean up duplication and improve clarity — without breaking the test.

Never write production code for a path that has no test coverage.

## Test Naming

Use descriptive, sentence-style names that state the scenario and expected outcome:

```
given_<context>_when_<action>_then_<expected_result>
```

Or plain English equivalents:

```
returns 404 when the resource does not exist
throws ValidationError when email is missing
```

Avoid names like `test1`, `testFoo`, or `happyPath`.

## What to Mock

**Mock:**
- External HTTP services and third-party APIs
- Email/SMS/push notification senders
- Payment providers
- The system clock (use a seam, not `Date.now()` directly)
- File system operations in unit tests

**Do not mock:**
- Your own domain logic — test it directly
- The database in integration tests — use a test database or in-memory equivalent
- Framework internals

## Test Layers

- **Unit tests:** pure functions, domain logic, transformations. No I/O.
- **Integration tests:** service + database, service + external HTTP (mocked at network boundary).
- **End-to-end tests:** full request/response cycle through the running application.

All three layers must pass before a branch is considered ready to merge.

## {{LANG_PRIMARY}}-Specific

- Follow the idiomatic test runner for `{{LANG_PRIMARY}}` (e.g., Jest for JS/TS, pytest for Python, RSpec for Ruby).
- Use the runner's built-in assertion library — do not add a second assertion library.
- Keep test files alongside source files or in a mirrored `tests/` directory — be consistent with the existing project structure.
