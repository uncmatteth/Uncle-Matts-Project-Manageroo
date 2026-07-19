# Host integration

Manageroo is a portable project controller. A user's host environment may contain additional skills and tools that are not part of Manageroo itself.

The boundary is:

```text
Manageroo portable core
    -> owns and installs only its small core skill pack
    -> controls Manageroo runs, evidence, review, repair, and completion

Host environment
    -> may expose extra installed skills, memory systems, review tools, and utilities
    -> remains independently owned and maintained
    -> can be used by Manageroo workers when relevant
```

Manageroo must not copy an entire host skill environment into its public package. It must not delete, replace, or upgrade host-owned skills merely because they are installed.

Inspect the current host without modifying it:

```bash
manageroo host-skills
manageroo host-skills --json
```

The report separates:

- Manageroo core skills currently present;
- missing Manageroo core skills;
- known optional skills that Manageroo ships as library assets but does not install by default;
- host-owned or external skills that belong to the user's agent environment.

`use-installed-skills-first` is the bridge. Workers may use a relevant installed host skill when its trigger matches and its required tools are available. An installed external orchestrator does not replace Manageroo's controller during a Manageroo run.

This lets advanced users keep richer local environments without making any one user's machine, private toolchain, or personal skill collection part of the public Manageroo product definition.
