import sys
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

    def test_scope_blocks_traversal_and_absolute_paths(self):
        for path in ("src/../docs/secret.md", "../outside.txt", "/tmp/outside.txt"):
            with self.subTest(path=path), self.assertRaises(SafetyError):
                ScopePolicy(("src/app.py",)).validate_paths([path])

    def test_empty_scope_fails_closed(self):
        with self.assertRaises(SafetyError):
            ScopePolicy(()).validate_paths(["README.md"])

    def test_scope_blocks_controller_files(self):
        with self.assertRaises(SafetyError):
            ScopePolicy((".manageroo/**",)).validate_paths([".manageroo/config.toml"])

    def test_command_allowlist(self):
        CommandPolicy(("python",)).validate(["python", "-m", "unittest"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["bash", "-c", "true"])

    def test_bare_allowlist_does_not_trust_arbitrary_path_qualified_executable(self):
        with self.assertRaises(SafetyError):
            CommandPolicy(("python",)).validate(["/tmp/python", "-m", "unittest"])
        with self.assertRaises(SafetyError):
            CommandPolicy(("git",)).validate(["./git", "status"])

    def test_running_python_interpreter_is_a_trusted_resolved_path(self):
        CommandPolicy(("python",)).validate([sys.executable, "-m", "unittest"])

    def test_explicit_path_qualified_executable_can_be_allowlisted(self):
        CommandPolicy(("/opt/manageroo-tools/python",)).validate(
            ["/opt/manageroo-tools/python", "-m", "unittest"]
        )

    def test_python_family_convenience_rejects_untrusted_path_and_prefix_spoof(self):
        CommandPolicy(("python",)).validate(["python3", "-m", "unittest"])
        CommandPolicy(("python",)).validate(["python3.11", "-m", "unittest"])
        for executable in ("/tmp/python3", "/tmp/python-backdoor", "python-backdoor"):
            with self.subTest(executable=executable), self.assertRaises(SafetyError):
                CommandPolicy(("python",)).validate([executable, "-m", "unittest"])

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
