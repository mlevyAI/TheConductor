# API Rules

**Stack:** {{STACK}}
**Auth model:** {{AUTH_MODEL}}

## Endpoint Naming

- Use lowercase kebab-case paths: `/api/user-profiles`, not `/api/userProfiles`.
- Prefer REST resource conventions: `GET /resource`, `POST /resource`, `PATCH /resource/:id`, `DELETE /resource/:id`.
- Version the API if breaking changes are anticipated: `/api/v1/...`.

## Request & Response Shape

- Always return JSON. Set `Content-Type: application/json` explicitly.
- Wrap list responses: `{ "data": [...], "meta": { "total": n } }`.
- Wrap error responses: `{ "error": { "code": "...", "message": "..." } }`.
- Use standard HTTP status codes — do not return `200 OK` with an error body.

## Auth Middleware

- Auth model for this project: `{{AUTH_MODEL}}`.
- Apply the designated auth middleware to every non-public route. Never rely on the caller to pass auth checks client-side.
- Token validation (expiry, signature, scopes) must happen server-side on every request.
- Do not log tokens, passwords, or PII to application logs.

## Error Handling

- Catch errors at the controller/handler boundary — do not let raw exceptions propagate to the client.
- Return `400` for validation failures, `401` for unauthenticated, `403` for unauthorized, `404` for missing resources, `500` for unexpected server errors.
- Include a machine-readable `code` in every error response alongside the human `message`.

## Do Not

- Do not put business logic in route handlers — extract to service/use-case layer.
- Do not skip input validation before touching the database.
- Do not expose stack traces or internal paths in production error responses.
