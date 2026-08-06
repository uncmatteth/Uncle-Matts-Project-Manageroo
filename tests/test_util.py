import json
import unittest

from manageroo.errors import SafetyError
from manageroo.util import redact_argv, redact_text, safe_repo_relative


class SafeRepoRelativeTests(unittest.TestCase):
    def test_backslashes_are_rejected_instead_of_normalized(self):
        self.assertEqual(safe_repo_relative("nested/file.txt"), "nested/file.txt")
        with self.assertRaisesRegex(SafetyError, "Unsafe repository-relative path"):
            safe_repo_relative("nested\\file.txt")


class RedactTextTests(unittest.TestCase):
    def test_missing_and_byte_output_are_safe_to_sanitize(self):
        self.assertEqual(redact_text(None), "")
        self.assertEqual(redact_text(b"before\x8fafter"), "before\ufffdafter")

    def test_nested_json_strings_use_the_full_redaction_pipeline(self):
        payload = {
            "message": "request failed: Bearer abc123",
            "details": [{"note": "password=hunter2 token='nested-secret'"}],
            "safe": "visible",
        }

        redacted = json.loads(redact_text(json.dumps(payload)))

        self.assertEqual(redacted["message"], "request failed: Bearer <REDACTED>")
        self.assertEqual(
            redacted["details"][0]["note"],
            "password=<REDACTED> token=<REDACTED>",
        )
        self.assertEqual(redacted["safe"], "visible")

    def test_plain_text_still_uses_the_full_redaction_pipeline(self):
        self.assertEqual(
            redact_text("request failed: Bearer abc123 password=hunter2"),
            "request failed: Bearer <REDACTED> password=<REDACTED>",
        )

    def test_authorization_schemes_redact_the_complete_credentials(self):
        for scheme, credential in (
            ("Basic", "dXNlcjpwYXNz"),
            ("ApiKey", "client-id client-secret"),
        ):
            with self.subTest(scheme=scheme):
                self.assertEqual(
                    redact_text(f"request failed: Authorization: {scheme} {credential}"),
                    f"request failed: Authorization: {scheme} <REDACTED>",
                )

    def test_authorization_header_argument_redacts_the_complete_credentials(self):
        self.assertEqual(
            redact_argv(["curl", "-H", "Authorization: Basic dXNlcjpwYXNz"]),
            ["curl", "-H", "Authorization: Basic <REDACTED>"],
        )

    def test_comma_delimited_authorization_credentials_are_fully_redacted(self):
        for scheme, credentials in (
            (
                "AWS4-HMAC-SHA256",
                "Credential=AKIA/example, SignedHeaders=host, Signature=deadbeef",
            ),
            (
                "Digest",
                'username="Mufasa", realm="test", nonce="abc", response="deadbeef"',
            ),
        ):
            with self.subTest(scheme=scheme):
                header = f"Authorization: {scheme} {credentials}"
                self.assertEqual(
                    redact_text(f"request failed: {header}\nstatus: 401"),
                    f"request failed: Authorization: {scheme} <REDACTED>\nstatus: 401",
                )
                self.assertEqual(
                    redact_argv(["curl", "-H", header]),
                    ["curl", "-H", f"Authorization: {scheme} <REDACTED>"],
                )


if __name__ == "__main__":
    unittest.main()
