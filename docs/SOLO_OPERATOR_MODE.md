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

Starting with a small useful shape:

```bash
umsmfburasbofe solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build a simple product homepage"
```

Starter choices:

- `blank`: only `README.md` and `.gitignore`.
- `static-site`: `index.html`, `styles.css`, and a no-dependency smoke test.
- `python-cli`: `app.py` and a no-dependency smoke test.
- `docs-project`: project docs, release checklist, and a no-dependency smoke test.

## What It Does Now

`solo` is the guided front door:

1. Pick the project repository.
2. Pick the AI agent preset.
3. Ask what should be built or fixed in normal language.
4. If `--create` is passed, create a missing or empty Git repo first.
5. If `--starter` is selected, add a small starter scaffold and smoke check.
6. Turn the ask into `.umsmfburasbofe/PRODUCT-BRIEF.md`.
7. Install or refresh the recommended skill pack.
8. Optionally wire GBrain and GitNexus command templates.
9. Report the status of selected extras like Obsidian and Loop Library.
10. Run readiness checks.
11. Print exactly one next command.
12. If `--run` is passed and readiness is green, start the build or repair run.
13. At release time, `release-ready` writes a plain-English production handoff.
14. When the release gate is ready, `release-ready` also updates
    `.umsmfburasbofe/PROJECT-MEMORY.md` with what shipped and what proof passed.

It reuses the same controller, brief builder, readiness checker, integration
config, and run engine as the lower-level commands. It is not a second product.

If the only blocker is missing checks, the next action is a command like:

```bash
umsmfburasbofe checks suggest --apply-first
```

That suggests one or more real verification commands without making the user
hand-edit `.umsmfburasbofe/config.toml`. With `--apply-first`, it writes the
first detected check into config, then tells the user to run `umsmfburasbofe
ready` again. Use plain `umsmfburasbofe checks suggest` when you only want to
inspect the options.

If the operator gets lost between steps, use:

```bash
umsmfburasbofe next
```

That command prints the current stage, why that stage was chosen, and exactly
one command to run next. It is the low-noise version of `ready`.

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
  -> release-ready gate
  -> Production handoff
```

Time length does not matter as much as avoiding wasted loops. The controller
should make the work shorter by default because it keeps scope, context, checks,
and proof explicit from the start.

## Project Memory

Every initialized project gets:

```text
.umsmfburasbofe/PROJECT-MEMORY.md
```

That file is meant to stay short. It says what the project is, what has shipped,
what must not break, what proof matters, and any operator notes. Future agents
should read it before broad product work.

Useful commands:

```bash
umsmfburasbofe memory show
umsmfburasbofe memory add --shipped "First release shipped" --must-not "Do not break checkout"
```

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

Create a static homepage starter with a smoke test:

```bash
umsmfburasbofe solo /absolute/path/to/new-site \
  --create \
  --starter static-site \
  --want "Build the first useful product homepage"
```

Combine intake and execution only when readiness is already green:

```bash
umsmfburasbofe solo --want "Make checkout less confusing" --run --apply --force
```

Use repair mode for already-broken code:

```bash
umsmfburasbofe solo --mode repair
```

Before a real release, run the final operator gate:

```bash
umsmfburasbofe release-ready \
  --target "Production deploy path" \
  --rollback "Rollback steps" \
  --approved-by "Your name"
```

When it runs, it writes:

```text
.umsmfburasbofe/cache/production-handoff.md
```

That file says whether to ship or not, what commit is being released, which
proof commands passed, which blockers remain, the release target, the rollback
plan, and the next operator action. On a ready release, `release-ready` also
updates `.umsmfburasbofe/PROJECT-MEMORY.md` with the shipped target, passing
proof, handoff path, rollback plan, and approver. Commit that memory update if
you want future agents to see it from Git.

Wire optional local context tools if they are installed:

```bash
umsmfburasbofe solo --use-gbrain --use-gitnexus
```
