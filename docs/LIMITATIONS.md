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
11. The default controller runs implementation tasks sequentially for correctness. It does not promise maximum parallel throughput.
12. GBrain, GitNexus, Clawpatch, AUTOREVIEW, and Obsidian integrations require local configuration and are not silently installed.
13. UMSMFBURASBOFE does not replace CI, production monitoring, backups, security review, or legal review.
14. High-risk migrations, billing, authentication, authorization, destructive data operations, and regulated workflows should still require human approval before production deployment.
15. The package is a source implementation. It is not installed in any product repository until the included installer and project initialization are run there.
