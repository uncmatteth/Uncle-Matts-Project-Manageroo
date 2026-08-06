import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.trufflehog import (
    TRUFFLEHOG_ASSET_SHA256,
    TRUFFLEHOG_RELEASE_BASE,
    TRUFFLEHOG_VERSION,
    install_trufflehog_binary,
    trufflehog_asset,
)


class TruffleHogTests(unittest.TestCase):
    def test_release_assets_cover_supported_desktop_platforms(self):
        reviewed_assets = {
            ("Darwin", "x86_64"): (
                "trufflehog_3.96.0_darwin_amd64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_darwin_amd64.tar.gz",
                "a30d8f1095e031a81a668e1582f2ed479c3b50476cef86317e0fb74210c33617",
            ),
            ("Darwin", "arm64"): (
                "trufflehog_3.96.0_darwin_arm64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_darwin_arm64.tar.gz",
                "87478306b95ca2420cfb844b7582383ac60b922e262350a0088e797f328d2e62",
            ),
            ("Linux", "x86_64"): (
                "trufflehog_3.96.0_linux_amd64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_linux_amd64.tar.gz",
                "7105f1cd6577f058a9e39d0578f1a99c8a1e481e4d3512cd8a09acfe22a0fdc0",
            ),
            ("Linux", "arm64"): (
                "trufflehog_3.96.0_linux_arm64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_linux_arm64.tar.gz",
                "50acd4c7a3b8ebfe5083d8350956057030c44be3515dedd55b45263495c490b2",
            ),
            ("Windows", "AMD64"): (
                "trufflehog_3.96.0_windows_amd64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_windows_amd64.tar.gz",
                "fbf918c52a1f29be96344e1c4696fe019cfc34fb1184fab31cf3e8347917b43a",
            ),
            ("Windows", "arm64"): (
                "trufflehog_3.96.0_windows_arm64.tar.gz",
                "https://github.com/trufflesecurity/trufflehog/releases/download/v3.96.0/"
                "trufflehog_3.96.0_windows_arm64.tar.gz",
                "e8a8a2db3e479c420b6c12b0740e4ff013ebc672b35a730637937b56eb55562e",
            ),
        }
        self.assertEqual(TRUFFLEHOG_VERSION, "3.96.0")
        for platform, (expected_asset, expected_url, expected_sha256) in reviewed_assets.items():
            with self.subTest(platform=platform):
                asset, sha256 = trufflehog_asset(*platform)
                self.assertEqual(asset, expected_asset)
                self.assertEqual(f"{TRUFFLEHOG_RELEASE_BASE}/{asset}", expected_url)
                self.assertEqual(sha256, expected_sha256)
        with self.assertRaisesRegex(RuntimeError, "Unsupported TruffleHog platform"):
            trufflehog_asset("Plan9", "mips")

    def test_checksum_mismatch_leaves_existing_binary_untouched(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            payload = b"new binary"
            member = tarfile.TarInfo("trufflehog")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
        data = archive.getvalue()
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "trufflehog"
            destination.write_bytes(b"old binary")
            with (
                patch.dict(
                    TRUFFLEHOG_ASSET_SHA256,
                    {"linux_amd64": hashlib.sha256(data).hexdigest()},
                ),
                self.assertRaisesRegex(RuntimeError, "checksum"),
            ):
                install_trufflehog_binary(
                    destination,
                    system="Linux",
                    machine="x86_64",
                    downloader=lambda _url: data + b"altered",
                )
            self.assertEqual(destination.read_bytes(), b"old binary")

    def test_verified_archive_installs_only_the_exact_binary_member(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            payload = b"verified binary"
            member = tarfile.TarInfo("trufflehog")
            member.mode = 0o755
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
            hostile = tarfile.TarInfo("../escape")
            hostile.size = 4
            bundle.addfile(hostile, io.BytesIO(b"nope"))
        data = archive.getvalue()
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "bin" / "trufflehog"
            with patch.dict(
                TRUFFLEHOG_ASSET_SHA256,
                {"linux_amd64": hashlib.sha256(data).hexdigest()},
            ):
                report = install_trufflehog_binary(
                    destination,
                    system="Linux",
                    machine="x86_64",
                    downloader=lambda _url: data,
                )
            self.assertEqual(destination.read_bytes(), b"verified binary")
            self.assertFalse((Path(temp) / "escape").exists())
            self.assertEqual(report["version"], TRUFFLEHOG_VERSION)


if __name__ == "__main__":
    unittest.main()
