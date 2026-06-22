# Document and Prose Lane

This lane is for books, articles, transcripts, PDFs, notes, long Markdown files,
and exact wording. Normal code context rules are not enough for that stuff.

## What It Does

Every run builds a document manifest:

```text
.umsmfburasbofe/runs/<run-id>/artifacts/discovery/document-manifest.json
```

That manifest lists document-like files with paths, hashes, byte counts, line
counts, token estimates, content kind, language, and whether each file is a long
document.

If `.umsmfburasbofe/config.toml` has `document_analysis_command`, the controller
runs that argv and records the output here:

```text
.umsmfburasbofe/runs/<run-id>/artifacts/discovery/document-intelligence.json
```

Passing output can inform planning. Failure is optional context. It is not a
reason for the AI to freehand an entire manuscript, rewrite exact wording, or
pretend it understood images.

## Config

```toml
[integrations]
document_analysis_command = [
  "python3",
  "scripts/document_intel.py",
  "{document_manifest_file}",
  "{document_state_dir}"
]
```

Supported placeholders:

```text
{repo}
{workspace}
{run_root}
{query}
{brief_file}
{inventory_file}
{external_context_file}
{document_manifest_file}
{document_intelligence_file}
{document_state_dir}
```

The command runs from the run root. Use `{repo}` when the command needs the
source repository path.

## Readiness

`umsmfburasbofe ready` checks whether the brief actually needs this lane.

- If the brief asks for PDFs, transcripts, screenshots, images, long prose,
  books, chapters, exact wording, or byte-for-byte replacement, readiness blocks
  until `document_analysis_command` is configured.
- If the repo contains document/media files but the brief does not ask to use
  them, readiness prints `WARN document/prose lane` and still allows the run.
- If the command is configured, readiness reports the lane as ready for explicit
  document/prose work.

## Rules

- Current repo files and direct user wording beat memory.
- Brain pages are source material; PDFs are often just renderings.
- Long prose should move one chapter, section, or small batch at a time.
- Exact user text must not be paraphrased, normalized, spellchecked, or polished
  unless the user asks.
- Media metadata is not vision. Use a real media/OCR lane when visual evidence
  matters.
- Failed document commands are recorded. They do not become AI repair prompts.

## Bundled Skills

The recommended skill pack includes helper lanes for this:

- `brain-ops` and `query` for GBrain-backed context.
- `ingest`, `idea-ingest`, `media-ingest`, and `voice-note-ingest` for getting
  source material into local context.
- `article-enrichment`, `book-mirror`, and `strategic-reading` for long prose.
- `pdf` and `brain-pdf` for PDF checks and brain-page PDF rendering.
- `citation-fixer` and `reports` for citation cleanup and durable report output.
- `exact-text-replacement` for byte-for-byte wording changes.

## AGENTS.md and CONTEXT.md

Project initialization writes managed guidance blocks to `AGENTS.md` and
`CONTEXT.md` when needed. Existing human content is preserved. The context
compiler prioritizes those files, `.umsmfburasbofe/PROJECT-MEMORY.md`, and the
current product brief so the user does not have to figure out agent-context file
rituals by hand.
