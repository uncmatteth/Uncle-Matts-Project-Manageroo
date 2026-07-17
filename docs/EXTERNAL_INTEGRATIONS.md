# External integrations

External tools are explicit argv templates in `.manageroo/config.toml`. They are optional. A failed optional command is recorded in the run artifacts and does not secretly alter the core controller flow.

## GBrain

Example:

```toml
[integrations]
gbrain_search_command = ["gbrain", "search", "{query}", "--json"]
gbrain_capture_command = ["gbrain", "capture", "{report_file}", "--json"]
```

Available placeholders include:

- `{query}`
- `{repo}`
- `{workspace}`
- `{run_root}`
- `{brief_file}`
- `{inventory_file}`
- `{report_file}`
- `{result_file}`
- `{patch_file}`
- `{status}`
- `{summary}`
- `{files_changed}`

The installer can guide a local GBrain setup using Bun and PGLite, or print the
official GBrain agent-supervised protocol. Existing GBrain installs are probed
without forced reinitialization. Manageroo still does not invent API keys,
search modes, source mappings, or recurring jobs.

## GitNexus

Example:

```toml
[integrations]
gitnexus_analyze_command = ["gitnexus", "analyze", "{repo}", "--json"]
gitnexus_query_command = ["gitnexus", "query", "{query}", "--json"]
```

Use `manageroo integrations configure` to detect locally installed commands and
write supported templates.

## Obsidian

Obsidian is used through plain Markdown files. The integration reads relevant
notes from the configured vault and may export final reports into the configured
folder. Obsidian itself does not need to be running.

```toml
[integrations]
obsidian_vault = "/absolute/path/to/vault"
obsidian_export_folder = "MANAGEROO"
```

## Document and prose lane

Example:

```toml
[integrations]
document_analysis_command = ["your-document-tool", "--manifest", "{document_manifest_file}", "--output", "{document_intelligence_file}"]
```

Available placeholders include:

- `{repo}`
- `{workspace}`
- `{run_root}`
- `{brief_file}`
- `{inventory_file}`
- `{document_manifest_file}`
- `{document_intelligence_file}`
- `{document_state_dir}`

Manageroo writes a document manifest before the command runs. The command owns
its output and must write deterministic evidence when the brief requires exact
PDF, transcript, screenshot, image, long-prose, or exact-text understanding.
File metadata alone is never treated as real document or visual comprehension.

## AUTOREVIEW and Clawpatch

Example:

```toml
[integrations]
autoreview_command = ["/absolute/path/to/autoreview", "--mode", "local"]
clawpatch_command = ["clawpatch", "review", "--limit", "3", "--jobs", "3"]
```

These are command-owned review/repair lanes. Manageroo:

1. runs the configured command;
2. captures exact output and exit status;
3. records changed files;
4. blocks unauthorized scope or Git commits;
5. checkpoints authorized command-owned edits;
6. reruns all configured gates;
7. performs the normal independent review afterward.

The AI repairer must not freehand fixes from AUTOREVIEW or Clawpatch findings.
If the configured command fails or cannot repair its own finding, Manageroo
blocks with captured evidence.

## Safety model

- Commands are argv arrays, not shell strings.
- `shell=True` is not used.
- External output is captured and bounded.
- Optional context tools cannot directly mark a run complete.
- Command-owned repair tools remain scope checked.
- Repo-local rules, product intent, deterministic gates, independent review, and
  the final controller state remain authoritative.
