import json
import shlex
import tempfile
from pathlib import Path


def text_command(name: str, text: str, *, exit_code: int = 0) -> list[str]:
    root = Path(tempfile.mkdtemp(prefix="manageroo-test-command-"))
    command = root / name
    command.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' {shlex.quote(text)}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    command.chmod(0o755)
    return [str(command)]


def json_command(name: str, payload: dict) -> list[str]:
    return text_command(name, json.dumps(payload))


def gbrain_search_command(source_id: str = "fixture", text: str = "GBRAIN OK") -> list[str]:
    return json_command("gbrain-search", {"results": [{"source_id": source_id, "text": text}]})


def gbrain_capture_command(text: str = "GBRAIN CAPTURE OK") -> list[str]:
    return text_command("gbrain-capture", text)


def gitnexus_analyze_command(text: str = "GITNEXUS ANALYZE OK") -> list[str]:
    return text_command("gitnexus-analyze", text)


def gitnexus_status_command(text: str = "GITNEXUS STATUS OK") -> list[str]:
    return text_command("gitnexus-status", text)
