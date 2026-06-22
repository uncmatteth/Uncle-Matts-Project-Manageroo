---
name: query
description: Use when answering from GBrain knowledge. Search/query the brain, read relevant pages, and answer with source-grounded context.
---

# Query

Use this for brain-backed answers. Do not answer from vibes when a brain page
can answer.

## Flow

1. `gbrain search "keywords" --limit 10`
2. `gbrain query "question"`
3. `gbrain get <slug>` for the useful page.
4. Answer plainly and cite what you used.

Current repo truth still beats older memory.
