import tempfile
import unittest
from pathlib import Path

from umsmfburasbofe.errors import StateTransitionError
from umsmfburasbofe.state import Phase, RunState


class StateTests(unittest.TestCase):
    def test_valid_path_and_persistence(self):
        state = RunState.create("run")
        state.transition(Phase.INTAKE, "intake")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            state.save(path)
            loaded = RunState.load(path)
            self.assertEqual(loaded.phase, Phase.INTAKE.value)
            self.assertEqual(loaded.run_id, "run")

    def test_skip_is_rejected(self):
        state = RunState.create("run")
        with self.assertRaises(StateTransitionError):
            state.transition(Phase.IMPLEMENTING, "skip")


if __name__ == "__main__":
    unittest.main()
