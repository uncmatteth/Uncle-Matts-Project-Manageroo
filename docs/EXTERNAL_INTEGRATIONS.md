# Stack integrations

This was built for your local stack, not for one blessed AI vendor. These tools
are not random extras; they are the point of the setup.

## AI IDEs and CLI agents

Any AI IDE or agent that can read the repo and run shell commands can use the
same installed `umsmfburasbofe` command and repo-local skill. There should not
be a special build for every AI logo.

## Codex

Codex is one adapter. When selected, this tool can start fresh `codex exec`
processes and pass the repo path, sandbox mode, schema, and output path.
`umsmfburasbofe doctor` checks the installed CLI before a run.

Official reference: https://developers.openai.com/codex/noninteractive

## OpenClaw

OpenClaw can call `umsmfburasbofe`, host the same skill, or act as the surface
where the work happens.

Official reference: https://docs.openclaw.ai/

## GBrain

Memory lane. GBrain can provide useful past context, but current repo files
still win.

Project reference: https://github.com/garrytan/gbrain

## GitNexus

Code graph lane. GitNexus can help explain what code touches what.

Project reference: https://github.com/abhigyanpatwari/GitNexus

Review GitNexus licensing before commercial embedding.

## Obsidian

Human notes lane. The tool can use an Obsidian vault as Markdown. No Obsidian
plugin is required.

Official reference: https://obsidian.md/help/data-storage

## AUTOREVIEW and Clawpatch

Review and patch lanes. AUTOREVIEW and Clawpatch can be configured as external
commands. Their findings still have to point at real files and real evidence.

AUTOREVIEW reference: https://github.com/openclaw/agent-skills
Clawpatch reference: https://github.com/openclaw/clawpatch
