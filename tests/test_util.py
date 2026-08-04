import json
import unittest

from manageroo.util import redact_argv, redact_text


class RedactTextTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
