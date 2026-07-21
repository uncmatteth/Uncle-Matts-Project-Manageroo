import math
import unittest

from manageroo.errors import ValidationError
from manageroo.schema import extract_json, validate


class SchemaTests(unittest.TestCase):
    def test_extracts_fenced_json(self):
        self.assertEqual(extract_json("```json\n{\"a\": 1}\n```"), {"a": 1})

    def test_required_property(self):
        with self.assertRaises(ValidationError):
            validate({}, {"type": "object", "required": ["a"]})

    def test_nested_type(self):
        with self.assertRaises(ValidationError):
            validate(
                {"items": ["ok", 3]},
                {
                    "type": "object",
                    "properties": {
                        "items": {"type": "array", "items": {"type": "string"}}
                    },
                },
            )

    def test_extract_json_rejects_non_finite_constants_everywhere(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant, shape="whole"):
                with self.assertRaises(ValidationError):
                    extract_json(f'{{"score": {constant}}}')
            with self.subTest(constant=constant, shape="embedded"):
                with self.assertRaises(ValidationError):
                    extract_json(f'prefix text {{"score": {constant}}} trailing text')

    def test_number_validation_rejects_non_finite_python_values(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    validate(value, {"type": "number"})


if __name__ == "__main__":
    unittest.main()
