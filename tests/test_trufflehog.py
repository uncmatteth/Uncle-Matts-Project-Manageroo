import hashlib
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from manageroo.trufflehog import (
    TRUFFLEHOG_VERSION,
    install_trufflehog_binary,
    trufflehog_asset,
)


class TruffleHogTests(unittest.TestCase):
    def test_release_assets_cover_supported_desktop_platforms(self):
        self.assertEqual(trufflehog_asset("Linux", "x86_64")[0], f"trufflehog_{TRUFFLEHOG_VERSION}_linux_amd64.tar.gz")
        self.assertEqual(trufflehog_asset("Darwin", "arm64")[0], f"trufflehog_{TRUFFLEHOG_VERSION}_darwin_arm64.tar.gz")
        self.assertEqual(trufflehog_asset("Windows", "AMD64")[0], f"trufflehog_{TRUFFLEHOG_VERSION}_windows_amd64.tar.gz")
        with self.assertRaisesRegex(RuntimeError, "Unsupported TruffleHog platform"):
            trufflehog_asset("Plan9", "mips")

    def test_checksum_mismatch_leaves_existing_binary_untouched(self):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as bundle:
            payload = b"new binary"
            member = tarfile.TarInfo("trufflehog")
            member.size = len(payload)
            bundle.addfile(member, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "trufflehog"
            destination.write_bytes(b"old binary")
            with self.assertRaisesRegex(RuntimeError, "checksum"):
                install_trufflehog_binary(
                    destination,
                    system="Linux",
                    machine="x86_64",
                    downloader=lambda _url: archive.getvalue(),
                    expected_sha256="0" * 64,
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
            report = install_trufflehog_binary(
                destination,
                system="Linux",
                machine="x86_64",
                downloader=lambda _url: data,
                expected_sha256=hashlib.sha256(data).hexdigest(),
            )
            self.assertEqual(destination.read_bytes(), b"verified binary")
            self.assertFalse((Path(temp) / "escape").exists())
            self.assertEqual(report["version"], TRUFFLEHOG_VERSION)


if __name__ == "__main__":
    unittest.main()
