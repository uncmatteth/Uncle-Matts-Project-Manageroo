import unittest

from umsmfburasbofe.errors import SafetyError
from umsmfburasbofe.policy import CommandPolicy, ScopePolicy


class PolicyTests(unittest.TestCase):
    def test_scope_accepts_allowed(self):
        self.assertEqual(
            ScopePolicy(("src/**",)).validate_paths(["src/app.py"]),
            ["src/app.py"],
        )

    def test_scope_blocks_outside(self):
        with self.assertRaises(SafetyError):
            ScopePolicy(("src/**",)).validate_paths(["docs/secret.md"])

    def test_scope_blocks_controller_files(self):
        with self.assertRaises(SafetyError):
            ScopePolicy((".umsmfburasbofe/**",)).validate_paths([".umsmfburasbofe/config.toml"])

    def test_command_allowlist(self):
        CommandPolicy(("python",)).validate(["python", "-m", "unittest"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["bash", "-c", "true"])


if __name__ == "__main__":
    unittest.main()
