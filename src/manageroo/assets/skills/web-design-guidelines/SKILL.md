---
name: web-design-guidelines
description: Use when designing, implementing, reviewing, or improving web pages, landing pages, app screens, dashboards, visual UI polish, responsive layout, accessibility, or frontend design quality. Apply this when the user asks for better design, UI review, UX review, design audit, modernization, redesign, landing-page polish, mobile cleanup, or "make it not look like AI slop".
triggers:
  - "web design guidelines"
  - "UI polish"
  - "design audit"
---

# Web Design Guidelines

Use this skill to make web interfaces intentional, usable, responsive, accessible, and visually specific. Do not fetch external guideline files at runtime. Work from the repo, the user's stated goal, and the rules below.

## Operating Rule

Preserve the existing product/design system when it is real. If the repo already has tokens, components, brand rules, spacing, typography, or page patterns, extend them instead of inventing a second visual language.

If no strong system exists, choose one clear direction before editing:

- Define the product job, audience, primary action, visual mood, layout structure, typography direction, color palette, and motion behavior.
- Avoid defaulting to generic SaaS layout, purple/blue gradients, centered hero plus cards, glassmorphism, stock-looking blobs, or system-font blandness.
- Make one viewport idea strong before adding sections, badges, metrics, cards, icons, or decorative effects.

## Build Workflow

1. Inspect the actual page/app structure, styling approach, component conventions, asset paths, and scripts before editing.
2. Identify the primary user task and the most important first-screen message or action.
3. Establish a concrete visual direction: editorial, industrial, luxury, playful, utility, brutalist, cinematic, product-console, restaurant, storefront, etc.
4. Implement through the repo's existing framework and design primitives unless there is a clear reason not to.
5. Verify desktop and mobile rendering. A build that compiles but overflows, hides controls, or collapses badly on mobile is not complete.
6. Check interactive states: hover, focus, active, loading, empty, error, disabled, success, and keyboard navigation where applicable.
7. Remove temporary screenshots, scratch files, and QA-only artifacts unless the user asked to keep them.

## Review Workflow

When reviewing UI, prioritize findings over praise. Report concrete problems with file/line references when available.

Check these areas:

- Purpose: the screen makes the core job obvious in the first few seconds.
- Hierarchy: headline, supporting copy, primary action, proof, and secondary content are ordered by importance.
- Layout: grid, alignment, spacing, section rhythm, and viewport balance are deliberate.
- Typography: fonts, sizes, line lengths, weights, and contrast support reading instead of decoration.
- Color: palette has roles, sufficient contrast, and no random accents or default purple bias.
- Components: buttons, cards, forms, nav, tables, modals, and panels feel like one system.
- Responsiveness: mobile keeps the same intent without clipping, cramped taps, horizontal scroll, or hidden primary actions.
- Accessibility: semantic HTML, labels, visible focus, target size, contrast, reduced motion, and screen-reader basics are respected.
- Interaction: controls are not fake, dead, or visually ambiguous.
- Content: copy is specific, truthful, concise, and not filler.

## Quality Bar

Good web UI should feel designed, not assembled.

- Use whitespace as structure, not leftover space.
- Use type as a design material: pick readable, purposeful type treatment and a clear scale.
- Use color sparingly and assign roles: background, surface, text, muted text, border, primary action, warning/error/success.
- Use motion only when it clarifies hierarchy, state, spatial movement, or product feel.
- Use imagery or illustration only when it explains the product, brand, mood, or workflow.
- Make sample data believable if the product surface needs data.
- Keep the first screen focused: one main message, one main action, one strong supporting visual or proof point.

## Anti-Patterns

Flag or fix these unless the user explicitly requested them:

- Generic AI/SaaS hero with vague headline, floating cards, gradient blobs, and no product specificity.
- Purple/blue gradient defaults with no brand reason.
- Fake metrics, fake testimonials, fake logos, or unverifiable authority claims.
- Overcrowded hero sections with badges, stats, feature cards, dashboards, and multiple CTAs fighting each other.
- Decorative motion that delays reading or causes layout shift.
- Low-contrast text, tiny all-caps labels, long line lengths, or cramped mobile type.
- Hidden overflow used to mask broken responsive layout.
- Static mock controls that look clickable but do nothing.
- Placeholder copy, lorem ipsum, generic "seamless solutions" language, or vague product claims.
- Adding new UI libraries when existing components can solve the problem cleanly.

## Implementation Rules

- Prefer CSS variables or existing design tokens for color, spacing, radii, shadows, and type scale.
- Keep styles coherent across sections; do not let each component invent its own spacing and border language.
- Make responsive behavior explicit with real breakpoints or fluid layout rules.
- Respect `prefers-reduced-motion` when adding animation.
- Keep keyboard focus visible and logical.
- Use semantic elements before div-heavy markup.
- Do not hard-code content that should come from existing data/config unless the task is a static mockup.
- Do not claim visual correctness without running or inspecting the rendered page when that is feasible.

## Pairing

- Use `plain-web-copy` when the issue is marketing/product copy, labels, public explanation, or jargon cleanup.
- Use browser/Playwright verification when layout, interaction, or responsive behavior must be proven.
- Use image generation only when the task calls for a new visual concept or missing visual assets; do not turn every small UI fix into a concept-art task.

## Final Reporting

For implementation work, report the outcome, the files changed, and what was verified. If rendering or browser verification was not run, say that plainly.

For review work, list findings first, ordered by severity. If no material findings were found, say so and name any residual risks or unverified surfaces.
