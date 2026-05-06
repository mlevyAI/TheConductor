# Frontend Rules

**Stack:** {{STACK}}
**Text direction:** {{TEXT_DIRECTION}}

## Component Structure

- One component per file. File name matches the exported component name.
- Keep components focused: if a component needs more than ~150 lines, extract sub-components.
- Co-locate styles with components unless a project-wide design token system is in use.
- Props must be typed (TypeScript interfaces or equivalent for `{{STACK}}`).

## Styling

- Use the project's designated styling system (see `CLAUDE.md` stack notes).
- Do not mix styling approaches (e.g., no inline styles alongside utility classes).
- All spacing, color, and typography values must come from design tokens or the utility scale — no magic numbers.

## Text Direction ({{TEXT_DIRECTION}})

- All layout primitives (flex, grid, margins, paddings, absolute positioning) must be direction-aware.
- Use logical CSS properties (`margin-inline-start`, `padding-inline-end`) instead of `left`/`right` where supported.
- If `{{TEXT_DIRECTION}}` is `rtl`, verify every new layout with an RTL smoke-check before marking work done.
- Icon directionality: icons that imply direction (arrows, chevrons) must be flipped in RTL.

## Accessibility

- Every interactive element must be keyboard-reachable and have a visible focus ring.
- Images require descriptive `alt` text; decorative images use `alt=""`.
- Color alone must not convey meaning — pair with text or iconography.
- Target minimum WCAG 2.1 AA contrast ratios.

## Do Not

- Do not fetch data directly inside presentational components — use a data-layer hook or store.
- Do not hardcode strings visible to users — route them through the i18n layer if one exists.
- Do not commit commented-out code blocks.
