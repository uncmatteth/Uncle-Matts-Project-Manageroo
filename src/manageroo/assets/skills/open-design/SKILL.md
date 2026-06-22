---
name: open-design
description: Use when designing, redesigning, reviewing, or polishing frontend UI so it looks specific to the product instead of generic AI output.
triggers:
  - "open design"
  - "design review"
  - "make this UI better"
  - "not generic"
---

# Open Design

Use this skill when the job is visual quality, product-specific UI direction, or
removing generic AI-looking layout and copy.

## Rules

1. Inspect the actual page, screenshot, or source files before judging.
2. Identify the product, audience, primary workflow, and proof surface.
3. Prefer concrete UI fixes over decorative filler.
4. Use real product/state/media signals when available.
5. Keep visual style consistent with the existing app unless the task asks for a
   redesign.
6. Verify rendered output when a browser or screenshot tool is available.

## What To Look For

- one-note palettes;
- generic cards, vague dashboards, or marketing filler;
- text that explains features instead of supporting the workflow;
- spacing, alignment, overflow, or mobile issues;
- missing empty/error/loading states;
- unclear primary actions;
- visuals that do not show the actual product, object, data, state, or game.

## Output

Give a short design diagnosis, then the specific changes made or recommended.
If code was changed, cite the files and verification performed.
