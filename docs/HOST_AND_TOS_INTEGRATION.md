# Host and tOS integration

Manageroo is a portable project controller. Tommy's tOS is a host environment that may contain many additional skills and tools.

The boundary is:

```text
Manageroo portable core
    -> owns and installs only its small core skill pack
    -> controls Manageroo runs, evidence, review, repair, and completion
    -> is hardware-agnostic and does not require Tommy's workstation specs
    -> does not auto-tune worker concurrency from CPU/RAM/GPU detection

Host environment / tOS
    -> may expose extra installed skills, memory systems, review tools, and utilities
    -> remains independently owned and maintained
    -> can be used by Manageroo workers when relevant
    -> may have more or less CPU, RAM, GPU, or VRAM than Tommy's machine
```

Manageroo must not copy the whole host skill environment into its public package. It must not delete or upgrade host-owned skills merely because they are installed.

Inspect the current host without modifying it:

```bash
manageroo host-skills
manageroo host-skills --json
manageroo capacity
manageroo capacity --json
```

`host-skills` separates:

- Manageroo core skills currently present;
- missing Manageroo core skills;
- known optional skills that Manageroo ships as library assets but does not install by default;
- host-owned or external skills that belong to tOS, Codex, OpenClaw, or the user.

`capacity` records host hardware as informational context only. Manageroo itself does not require a particular GPU, CPU tier, RAM class, or VRAM amount. A target project or explicitly selected local AI tool can still have its own hardware requirements.

`use-installed-skills-first` is the bridge. Workers may use a relevant installed host skill when its trigger matches and its required tools are available. An installed external orchestrator does not replace Manageroo's controller during a Manageroo run.

This lets a development workstation gradually become tOS without making the temporary state or hardware specifications of that workstation the public Manageroo product definition.
