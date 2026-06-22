---
name: brain-ops
description: Use when reading from or writing to GBrain. Search brain first, cite sources, preserve user statements as highest authority, and write useful durable context back only when appropriate.
---

# Brain Ops

Use this when a task needs past context, project memory, people/company facts,
or durable notes.

## Rules

1. Search GBrain before external research when the topic may already exist.
2. Use current repo files and command output over memory when they disagree.
3. Treat direct user statements as highest-authority context.
4. Cite the brain page or command evidence used.
5. Do not silently write noisy or speculative pages.
6. After useful brain writes, sync so the page is searchable.

## Good default commands

```bash
gbrain search "topic" --limit 10
gbrain query "plain-language question"
gbrain get path/to/page
gbrain status --json --section sync
```

## UMSMFBURASBOFE fit

GBrain is the memory lane. It can inform planning and capture reports, but the
controller still owns scope, gates, review, and final proof.
