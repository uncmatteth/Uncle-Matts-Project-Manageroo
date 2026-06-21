from __future__ import annotations


SUPER_TEAM = [
    {
        "name": "Peter Yang / @petergyang",
        "hero": "The Skill Smith",
        "stats": "STR 8 | DEX 12 | CON 14 | INT 18 | WIS 17 | CHA 16",
        "power": (
            "Turns messy repeated agent behavior into tight reusable skills, "
            "then keeps those skills short with edit passes."
        ),
        "credit": "Skill hygiene, self-improving skill loops, and the edit-skill idea.",
        "url": "https://x.com/petergyang",
    },
    {
        "name": "Matthew Berman / Forward Future",
        "hero": "Captain Looplight",
        "stats": "STR 10 | DEX 13 | CON 15 | INT 17 | WIS 18 | CHA 17",
        "power": (
            "Makes agent loops easy to understand: bounded task, verifier, "
            "stop rule, and evidence."
        ),
        "credit": "Loop Library and plain-language loop framing.",
        "url": "https://signals.forwardfuture.ai/loop-library/",
    },
    {
        "name": "Garry Tan / GBrain",
        "hero": "The Memory Architect",
        "stats": "STR 11 | DEX 11 | CON 18 | INT 18 | WIS 18 | CHA 14",
        "power": (
            "Gives agents durable memory so useful context can come back later "
            "without dumping the whole universe into the prompt."
        ),
        "credit": "GBrain local memory and retrieval layer.",
        "url": "https://github.com/garrytan/gbrain",
    },
    {
        "name": "Abhigyan Patwari / GitNexus",
        "hero": "The Graph Cartographer",
        "stats": "STR 9 | DEX 16 | CON 14 | INT 18 | WIS 16 | CHA 13",
        "power": (
            "Turns codebases into navigable graphs so agents can reason about "
            "impact instead of guessing from a flat file list."
        ),
        "credit": "GitNexus code graph and impact-analysis direction.",
        "url": "https://github.com/abhigyanpatwari/GitNexus",
    },
    {
        "name": "OpenClaw Agent Skills, AUTOREVIEW, and Clawpatch",
        "hero": "The Patch Council",
        "stats": "STR 15 | DEX 15 | CON 16 | INT 17 | WIS 17 | CHA 12",
        "power": (
            "Maps work into bounded slices, reviews with evidence, and keeps "
            "patching explicit instead of vibes-based."
        ),
        "credit": "Agent skill packaging, structured review, and Clawpatch-style fix loops.",
        "url": "https://github.com/openclaw/agent-skills",
    },
    {
        "name": "OpenAI Codex skill system",
        "hero": "The Skill Forge",
        "stats": "STR 10 | DEX 14 | CON 15 | INT 18 | WIS 16 | CHA 15",
        "power": (
            "Gives local agents a simple skill format: clear trigger text first, "
            "then instructions and bundled resources only when needed."
        ),
        "credit": "Codex skill routing, skill-creator guidance, and agent-readable skill packaging.",
        "url": "https://developers.openai.com/codex/",
    },
    {
        "name": "Obsidian",
        "hero": "The Vault Keeper",
        "stats": "STR 8 | DEX 13 | CON 17 | INT 16 | WIS 17 | CHA 15",
        "power": (
            "Keeps human notes in plain Markdown so the user can read and own "
            "the context instead of trusting a mystery database."
        ),
        "credit": "Markdown-vault notes as a human-readable context lane.",
        "url": "https://obsidian.md/",
    },
]


def format_special_thanks(*, indent: str = "") -> str:
    lines = [
        f"{indent}Special thanks: the UMSMFBURASBOFE Super Team",
        f"{indent}These are the real-world powers this project remixes:",
    ]
    for member in SUPER_TEAM:
        lines.extend(
            [
                f"{indent}- {member['name']} as {member['hero']}",
                f"{indent}  Stats: {member['stats']}",
                f"{indent}  Power: {member['power']}",
                f"{indent}  Credit: {member['credit']}",
                f"{indent}  Link: {member['url']}",
            ]
        )
    lines.append(
        f"{indent}Together they are the local-agent super team: skills shape the ask, "
        "loops define the mission, memory remembers the map, graphs show the blast "
        "radius, review catches the bad stuff, and notes keep a human-readable trail."
    )
    return "\n".join(lines)
