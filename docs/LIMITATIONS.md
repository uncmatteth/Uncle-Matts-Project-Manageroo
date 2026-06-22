# Limitations and truthful boundaries

1. No coding system can guarantee that a natural-language product idea is complete or internally consistent.
2. “One shot” can remove operator-managed engineering iteration; it cannot safely infer every irreversible product decision.
3. Model-generated architecture and code remain probabilistic.
4. Passing tests only proves what the tests and runtime demonstrations cover.
5. The built-in context token estimator is conservative character-based estimation, not a provider tokenizer.
6. The selected agent adapter must be installed, authenticated when needed, and able to emit the required JSON artifacts.
7. The Codex adapter requires a compatible installed CLI and authentication only when the project selects Codex.
8. The generic adapter cannot promise provider-level sandboxing.
9. The isolated mirror excludes Git-ignored files. Applications that require ignored generated assets or local secrets must provide them through a controlled environment.
10. Symlinks are excluded from the mirror in the current implementation to prevent path escape.
11. Independent map and review chunks can run in parallel. Implementation tasks remain dependency ordered for correctness.
12. Media support is bounded support. MANAGEROO records images, PDFs, and design/media assets in inventory and can use local OCR/PDF text extractors when installed, but it does not perform real vision interpretation or design understanding.
13. Long prose support includes line counts, summaries, document manifests, optional `document_analysis_command` output, explicit summary context, and task decomposition. Exact edits still require bounded line ranges or an external document-specific command that owns the evidence.
14. GBrain, GitNexus, Clawpatch, AUTOREVIEW, and Obsidian integrations require local configuration and are not silently installed.
15. Configured AUTOREVIEW and Clawpatch commands are deterministic command-owned lanes. MANAGEROO captures their output and can accept their scoped edits, but it does not ask the AI repairer to freehand fixes from their findings.
16. `solo --create` creates only missing or empty top-level project folders. Starters are small local scaffolds, not production frameworks. The command refuses non-empty non-Git folders and missing paths inside another Git repo so it does not accidentally commit personal files, secrets, archives, or nested repositories.
17. MANAGEROO does not replace CI, production monitoring, backups, security review, or legal review.
18. `release-ready` is a final operator gate, not a deployment tool. It checks readiness, gates, clean Git state, target, rollback notes, and approval, then writes `.manageroo/cache/production-handoff.md`. On a ready release it also updates `.manageroo/PROJECT-MEMORY.md` with the shipped target and proof; the operator can commit that memory update if desired. It does not push, deploy, monitor, or roll back production.
19. MANAGEROO does not run cloud schedules or timer loops by itself. Loop and routine patterns are adapted into bounded local goal-style runs unless the operator supplies a separate scheduler.
20. The learning lane records suggestions and can approval-apply low-risk project-memory notes. It does not silently edit skills, docs, config, installer behavior, checks, prompts, or code.
21. High-risk migrations, billing, authentication, authorization, destructive data operations, and regulated workflows should still require human approval before production deployment.
22. `run --continue <run-id>` continues Manageroo's saved worker job queue from disk. It replays the controller from saved artifacts and job records; it is not a terminal keepalive feature and does not promise that a killed OS process kept running.
23. Stateless worker orchestration reduces dependence on chat memory and compaction. It does not make probabilistic model output deterministic; it records packets, attempts, artifacts, checks, and failures so bad attempts can be thrown away.
24. The package is a source implementation. It is not installed in any product repository until the included installer and project initialization are run there.
