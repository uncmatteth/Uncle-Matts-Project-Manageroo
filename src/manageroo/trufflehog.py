from __future__ import annotations

import hashlib
import io
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable


TRUFFLEHOG_VERSION = "3.96.0"
TRUFFLEHOG_REFERENCE = "https://github.com/trufflesecurity/trufflehog"
TRUFFLEHOG_RELEASE_BASE = (
    f"https://github.com/trufflesecurity/trufflehog/releases/download/v{TRUFFLEHOG_VERSION}"
)
TRUFFLEHOG_ASSET_SHA256 = {
    "darwin_amd64": "a30d8f1095e031a81a668e1582f2ed479c3b50476cef86317e0fb74210c33617",
    "darwin_arm64": "87478306b95ca2420cfb844b7582383ac60b922e262350a0088e797f328d2e62",
    "linux_amd64": "7105f1cd6577f058a9e39d0578f1a99c8a1e481e4d3512cd8a09acfe22a0fdc0",
    "linux_arm64": "50acd4c7a3b8ebfe5083d8350956057030c44be3515dedd55b45263495c490b2",
    "windows_amd64": "fbf918c52a1f29be96344e1c4696fe019cfc34fb1184fab31cf3e8347917b43a",
    "windows_arm64": "e8a8a2db3e479c420b6c12b0740e4ff013ebc672b35a730637937b56eb55562e",
}


def trufflehog_asset(system: str | None = None, machine: str | None = None) -> tuple[str, str]:
    system_name = (system or platform.system()).strip().lower()
    machine_name = (machine or platform.machine()).strip().lower()
    os_name = {"darwin": "darwin", "linux": "linux", "windows": "windows"}.get(system_name)
    architecture = {
        "amd64": "amd64",
        "x86_64": "amd64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }.get(machine_name)
    key = f"{os_name}_{architecture}" if os_name and architecture else ""
    checksum = TRUFFLEHOG_ASSET_SHA256.get(key)
    if not checksum:
        raise RuntimeError(f"Unsupported TruffleHog platform: {system_name}/{machine_name}")
    return f"trufflehog_{TRUFFLEHOG_VERSION}_{key}.tar.gz", checksum


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "manageroo-installer"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def install_trufflehog_binary(
    destination: Path,
    *,
    system: str | None = None,
    machine: str | None = None,
    downloader: Callable[[str], bytes] = _download,
    expected_sha256: str | None = None,
) -> dict[str, str]:
    """Install one pinned TruffleHog binary without extracting any other archive member."""
    asset, pinned_sha256 = trufflehog_asset(system, machine)
    expected = expected_sha256 or pinned_sha256
    url = f"{TRUFFLEHOG_RELEASE_BASE}/{asset}"
    payload = downloader(url)
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise RuntimeError(
            f"TruffleHog release checksum mismatch for {asset}: expected {expected}, received {actual}"
        )
    executable_name = "trufflehog.exe" if asset.find("_windows_") >= 0 else "trufflehog"
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = [member for member in archive.getmembers() if member.name == executable_name]
        if len(members) != 1 or not members[0].isfile():
            raise RuntimeError(f"Pinned TruffleHog archive does not contain one regular {executable_name} file")
        source = archive.extractfile(members[0])
        if source is None:
            raise RuntimeError(f"Pinned TruffleHog archive member {executable_name} could not be read")
        binary = source.read()
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, stage_name = tempfile.mkstemp(
        prefix=f".{destination.name}.manageroo-stage-", dir=str(destination.parent)
    )
    stage = Path(stage_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(binary)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            stage.chmod(0o755)
        stage.replace(destination)
    finally:
        if stage.exists():
            stage.unlink()
    return {
        "version": TRUFFLEHOG_VERSION,
        "path": str(destination),
        "asset": asset,
        "url": url,
        "sha256": actual,
    }
