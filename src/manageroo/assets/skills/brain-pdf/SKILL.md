---
name: brain-pdf
description: Use when exporting a brain page to PDF. The brain page remains the source of truth; the PDF is only a rendering.
---

# Brain PDF

Use this when the user wants a clean PDF copy of a brain page, report, book
mirror, strategic reading, or long-form note.

## Rules

1. Confirm the brain page exists before rendering.
2. Treat the brain page as source of truth.
3. Strip YAML frontmatter before rendering.
4. Do not add cover pages or tables of contents unless asked.
5. If the renderer is missing, report the missing renderer and keep the brain
   page as the deliverable.

## Expected renderer

```bash
$HOME/.claude/skills/gstack/make-pdf/dist/pdf
```

If that binary is unavailable, MANAGEROO should say PDF export is optional
and currently unavailable, not block the build lane.
