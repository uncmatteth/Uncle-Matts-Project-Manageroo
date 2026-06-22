# Solo Operator Mode

Solo Operator Mode is the main product path.

It is for a technically minded person who does not want to hire or manage a
software team. The user can explain the product, make decisions, approve proof,
and ship when the evidence is good enough. They should not need to know the
codebase internals, agent wiring, skill hygiene, or release checklist up front.

Run it with:

```bash
umsmfburasbofe solo
```

Starting from an empty or missing folder:

```bash
umsmfburasbofe solo /absolute/path/to/new-product --create --want "Build the first useful version"
```

## What It Does Now

`solo` is the guided front door:

1. Pick the project repository.
2. Pick the AI agent preset.
3. Ask what should be built or fixed in normal language.
4. If `--create` is passed, create a missing or empty Git repo first.
5. Turn the ask into `.umsmfburasbofe/PRODUCT-BRIEF.md`.
6. Install or refresh the bundled helper skills.
7. Optionally wire GBrain and GitNexus command templates.
8. Report the status of selected extras like Obsidian and Loop Library.
9. Run readiness checks.
10. Print exactly one next command.
11. If `--run` is passed and readiness is green, start the build or repair run.

It reuses the same controller, brief builder, readiness checker, integration
config, and run engine as the lower-level commands. It is not a second product.

If the only blocker is missing checks, the next action is a command like:

```bash
umsmfburasbofe checks add smoke -- npm test
```

That adds one real verification command without making the user hand-edit
`.umsmfburasbofe/config.toml`.

## The Full Product Path

This is the intended solo-to-production lifecycle:

```text
Idea
  -> Plain-language intake
  -> Product brief
  -> Repo setup
  -> Tool/skill setup
  -> Build or repair run
  -> Checks
  -> Independent review
  -> Repair loop
  -> Final report
  -> Release readiness
  -> Production handoff
```

Time length does not matter as much as avoiding wasted loops. The controller
should make the work shorter by default because it keeps scope, context, checks,
and proof explicit from the start.

## What Still Needs To Become Better

These are product gaps, not optional polish:

- A release-readiness command that checks production build, environment, secrets,
  deployment target, rollback notes, and final human approval.
- Starter templates beyond the minimal README/.gitignore scaffold.
- Skill-library import scanning, so a copied folder like `/home/Tommy/Downloads/SKILLS`
  can be deduped and turned into a curated local toolbox instead of copied whole.
- Better guided verification suggestions for repos that do not already have tests.
- A project memory lane that explains what this project is, what has shipped,
  and what should never be broken.
- Clear production handoff output for a non-coder: what changed, what proof
  passed, what remains risky, and what button/command ships it.

## Useful Flags

Prepare a project from a single command:

```bash
umsmfburasbofe solo \
  --want "Make checkout less confusing" \
  --outcome "One clear payment path" \
  --must-not "Do not change admin exports" \
  --proof "Run checkout tests" \
  --agent codex \
  --force
```

Create a new empty Git project and prepare the first brief:

```bash
umsmfburasbofe solo /absolute/path/to/new-product \
  --create \
  --want "Build the first useful version"
```

Combine intake and execution only when readiness is already green:

```bash
umsmfburasbofe solo --want "Make checkout less confusing" --run --apply --force
```

Use repair mode for already-broken code:

```bash
umsmfburasbofe solo --mode repair
```

Wire optional local context tools if they are installed:

```bash
umsmfburasbofe solo --use-gbrain --use-gitnexus
```
