# External integrations

The core harness does not require any optional integration.

## Codex

Default execution adapter. UMSMFBURASBOFE starts a fresh `codex exec` process per role, supplies a repository directory, sandbox mode, JSON schema, and output-last-message path. `umsmfburasbofe doctor` checks that the installed CLI exposes the required flags before a live run.

Official reference: https://developers.openai.com/codex/noninteractive

## OpenClaw

OpenClaw may invoke the `umsmfburasbofe` CLI or host the same Agent Skill. OpenClaw is not the state authority; UMSMFBURASBOFE remains the controller.

Official reference: https://docs.openclaw.ai/

## GBrain

Use as optional long-term memory. Configure explicit argv templates only after the core workflow is operational. Retrieved memories are bounded context evidence; they do not override current code or locked contracts.

Project reference: https://github.com/garrytan/gbrain

## GitNexus

Use as optional supplemental impact and graph analysis. UMSMFBURASBOFE already includes deterministic repository inventory and map/reduce, so GitNexus is an accelerator rather than a boot dependency.

Project reference: https://github.com/abhigyanpatwari/GitNexus

Review GitNexus licensing before commercial embedding.

## Obsidian

UMSMFBURASBOFE can read and write the vault as ordinary Markdown. No Obsidian plugin is required. Set `integrations.obsidian_vault` in project configuration after installation.

Official reference: https://obsidian.md/help/data-storage

## AUTOREVIEW and Clawpatch

Optional supplementary reviewers can be configured as argv-only external commands. Built-in isolated Codex review remains the default. External findings must still pass UMSMFBURASBOFE's evidence and scope validation.

AUTOREVIEW reference: https://github.com/openclaw/agent-skills
Clawpatch reference: https://github.com/openclaw/clawpatch
