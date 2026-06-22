# Proactive learning lane

MANAGEROO watches each run for useful lessons, but it does not silently
rewrite itself.

The learning lane creates small improvement cards after a run. A card is a
plain artifact with:

- what happened;
- why it matters;
- where the lesson belongs;
- risk level and priority;
- evidence from the run;
- whether it can be applied automatically after approval.

Cards are saved in two places:

```text
.manageroo/runs/<run-id>/artifacts/learning/improvement-cards.json
.manageroo/cache/learning/pending/*.json
```

The run artifact is the full evidence bundle for that run. The pending cache is
the operator's review queue.

## Approval-gated by default

This is approval-gated on purpose. MANAGEROO may save pending cards
automatically. It must not silently change behavior, skills, config, docs,
installer behavior, or project memory.

Applying a card requires an explicit command:

```bash
manageroo learning apply CARD_ID --approve
```

If `--approve` is missing, the command reports what it would do and exits
without changing the repo.

## Supported apply target

The first supported automatic apply is low-risk project memory capture.

That means a completed run can create a card that says:

```text
Record this completed run in .manageroo/PROJECT-MEMORY.md.
```

With approval, MANAGEROO appends a short note and proof line to project
memory.

## Manual-only cards

Higher-risk cards are manual-only. They are saved and shown, but there is no
automatic apply path yet.

Examples:

- an AUTOREVIEW or Clawpatch command lane failed;
- GBrain or GitNexus optional context failed;
- media-heavy work needs a real visual evidence lane;
- long prose work needs a document/prose workflow;
- blocked runs need a scoped repair plan.

Manual-only means the operator or agent should inspect the evidence and turn it
into a separate approved task. It does not mean the AI should guess a fix.

## Commands

List pending cards:

```bash
manageroo learning list
```

Show one card:

```bash
manageroo learning show CARD_ID
```

Apply a supported card after explicit approval:

```bash
manageroo learning apply CARD_ID --approve
```

Show JSON for scripting:

```bash
manageroo learning list --json
manageroo learning show CARD_ID --json
manageroo learning apply CARD_ID --approve --json
```

## What this is not

This is not a hidden self-modifying agent. It is not a cloud training loop. It
does not edit skills, docs, prompts, config, installer behavior, or checks
without approval.

The design is intentionally boring where it matters: record the lesson, cite the
evidence, rank it, store it, and wait for the operator to approve the change.
