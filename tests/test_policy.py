import unittest

from manageroo.errors import SafetyError
from manageroo.policy import CommandPolicy, ScopePolicy, validate_allowed_scope_patterns


class PolicyTests(unittest.TestCase):
    def test_scope_accepts_allowed(self):
        self.assertEqual(
            ScopePolicy(("src/app.py",)).validate_paths(["src/app.py"]),
            ["src/app.py"],
        )

    def test_scope_blocks_outside(self):
        with self.assertRaises(SafetyError):
            ScopePolicy(("src/app.py",)).validate_paths(["docs/secret.md"])

    def test_scope_blocks_controller_files(self):
        with self.assertRaises(SafetyError):
            ScopePolicy((".manageroo/**",)).validate_paths([".manageroo/config.toml"])

    def test_command_allowlist(self):
        CommandPolicy(("python",)).validate(["python", "-m", "unittest"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["bash", "-c", "true"])

    def test_broad_allowed_scope_patterns_are_rejected(self):
        for pattern in ("**", "*", "src/**", "**/*", "*.py", "src/*.py", "", "/", "."):
            with self.subTest(pattern=pattern):
                with self.assertRaises(SafetyError):
                    validate_allowed_scope_patterns([pattern])

    def test_exact_allowed_scope_patterns_still_pass(self):
        self.assertEqual(
            validate_allowed_scope_patterns(["src/app.py", "tests/test_app.py"]),
            ["src/app.py", "tests/test_app.py"],
        )


if __name__ == "__main__":
    unittest.main()
