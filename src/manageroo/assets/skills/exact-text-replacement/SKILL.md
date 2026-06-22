---
name: exact-text-replacement
description: Use when the user provides exact replacement text or wording that must be preserved byte-for-byte.
---

# Exact Text Replacement

Use this when wording drift matters.

## Rules

1. Treat the user's literal text as source of truth.
2. Do not paraphrase, improve, normalize, or fix spelling unless asked.
3. Replace the smallest target block possible.
4. Verify the final block with a byte-for-byte diff.
5. Do not change unrelated lines.
