import unittest

from umsmfburasbofe.errors import ValidationError
from umsmfburasbofe.schema import extract_json, validate


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


if __name__ == "__main__":
    unittest.main()
