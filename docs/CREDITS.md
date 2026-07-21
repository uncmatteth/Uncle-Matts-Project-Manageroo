# Credits

MANAGEROO is a local remix of several useful agent-work ideas. It does not pretend those ideas appeared from nowhere.

## Special Thanks: The MANAGEROO Super Team

- **Peter Yang / [@petergyang](https://x.com/petergyang) as The Skill Smith**
  - Stats: STR 8 | DEX 12 | CON 14 | INT 18 | WIS 17 | CHA 16
  - Power: turns messy repeated agent behavior into tight reusable skills, then keeps those skills short with edit passes.
  - Credit: skill hygiene, self-improving skill loops, and the `edit-skill` idea.

- **Matthew Berman / [@MatthewBerman](https://x.com/MatthewBerman) and Forward Future / [@ForwardFuture](https://x.com/ForwardFuture) as Captain Looplight**
  - Stats: STR 10 | DEX 13 | CON 15 | INT 17 | WIS 18 | CHA 17
  - Power: makes agent loops easy to understand: bounded task, verifier, stop rule, and evidence.
  - Credit: plain-language framing of bounded action, independent verification, budgets, stop rules, and evidence. This is conceptual influence; Manageroo has no Loop Library runtime dependency.
  - Link: https://signals.forwardfuture.com/loop-library/

- **Garry Tan / [@garrytan](https://x.com/garrytan) / GBrain as The Memory Architect**
  - Stats: STR 11 | DEX 11 | CON 18 | INT 18 | WIS 18 | CHA 14
  - Power: gives agents durable memory without dumping the whole universe into the prompt.
  - Credit: GBrain local memory and retrieval.
  - Link: https://github.com/garrytan/gbrain

- **Abhigyan Patwari / GitNexus as The Graph Cartographer**
  - Stats: STR 9 | DEX 16 | CON 14 | INT 18 | WIS 16 | CHA 13
  - Power: turns codebases into navigable graphs so agents can reason about impact.
  - Credit: GitNexus code graph and impact-analysis direction.
  - Note: no X handle is listed because one has not been confidently verified.
  - Link: https://github.com/abhigyanpatwari/GitNexus

- **OpenClaw / [@OpenClaw](https://x.com/OpenClaw) — Agent Skills, AUTOREVIEW, and Clawpatch as The Patch Council**
  - Stats: STR 15 | DEX 15 | CON 16 | INT 17 | WIS 17 | CHA 12
  - Power: maps work into bounded slices, reviews with evidence, and keeps patching explicit.
  - Credit: agent skill packaging, structured review, and Clawpatch-style fix loops.
  - Links: https://github.com/openclaw/agent-skills and https://github.com/openclaw/clawpatch

- **OpenAI / [@OpenAI](https://x.com/OpenAI) — Codex skill ecosystem as The Skill Forge**
  - Stats: STR 10 | DEX 14 | CON 15 | INT 18 | WIS 16 | CHA 15
  - Power: routes relevant skills and supporting resources into coding-agent work when needed.
  - Credit: Codex-oriented skill routing, skill-creator guidance, and agent-readable skill packaging. This is not a claim that OpenAI invented the general concept of skills.
  - Link: https://developers.openai.com/codex/

- **Obsidian / [@obsdmd](https://x.com/obsdmd) as The Vault Keeper**
  - Stats: STR 8 | DEX 13 | CON 17 | INT 16 | WIS 17 | CHA 15
  - Power: keeps human notes in plain Markdown that the user can read and own.
  - Credit: Markdown-vault notes as a human-readable context lane.
  - Link: https://obsidian.md/

Together they are the local-agent super team: skills shape the ask, loops define the mission, memory remembers the map, graphs show the blast radius, review catches the bad stuff, and notes keep a human-readable trail.

Manageroo's contribution is the controller above those pieces: the layer that owns the mission, durable run state, decisions, boundaries, verification, evidence, and definition of done.

## OpenClaw License Note

The public OpenClaw core repository and official docs identify OpenClaw as MIT licensed. MIT means the public code can be used, copied, changed, and shared under the license terms.

That license fact does not prove private compensation facts. A person can get paid through hiring, acquisition, sponsorship, consulting, or another private deal while related code is still MIT licensed. Do not claim a specific Microsoft or OpenAI payment story unless there is a primary source for the deal terms.
