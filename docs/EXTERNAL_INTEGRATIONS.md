# Stack integrations

UMSMFBURASBOFE was built for a local agent stack. The controller remains the authority, but these systems are not random extras; they are the intended surrounding tools.

## AI IDEs and CLI agents

Any AI IDE or agent that can read the repository and run shell commands can use UMSMFBURASBOFE through the same installed `umsmfburasbofe` CLI and repo-local skill. There should not be a special UMSMFBURASBOFE build per AI vendor.

## Codex

One execution adapter. UMSMFBURASBOFE can start a fresh `codex exec` process per role, supply a repository directory, sandbox mode, JSON schema, and output-last-message path. `umsmfburasbofe doctor` checks that the installed CLI exposes the required flags when the project selects the Codex adapter.

Official reference: https://developers.openai.com/codex/noninteractive

## OpenClaw

OpenClaw may invoke the `umsmfburasbofe` CLI, host the same Agent Skill, or act as an execution surface. OpenClaw is not the state authority; UMSMFBURASBOFE remains the controller.

Official reference: https://docs.openclaw.ai/

## GBrain

Durable memory and retrieval lane. Retrieved memories become bounded context evidence with explicit provenance; they do not override current code or locked contracts.

Project reference: https://github.com/garrytan/gbrain

## GitNexus

Code graph and impact lane. UMSMFBURASBOFE includes deterministic inventory and map/reduce, while GitNexus provides deeper graph context when configured.

Project reference: https://github.com/abhigyanpatwari/GitNexus

Review GitNexus licensing before commercial embedding.

## Obsidian

Human-readable operator notes. UMSMFBURASBOFE can read and write the vault as ordinary Markdown. No Obsidian plugin is required. Set `integrations.obsidian_vault` in project configuration after installation.

Official reference: https://obsidian.md/help/data-storage

## AUTOREVIEW and Clawpatch

Review and patch lanes. AUTOREVIEW and Clawpatch can be configured as argv-only external commands. External findings must still pass UMSMFBURASBOFE's evidence and scope validation.

AUTOREVIEW reference: https://github.com/openclaw/agent-skills
Clawpatch reference: https://github.com/openclaw/clawpatch
