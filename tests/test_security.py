import unittest

from cli_collab.security import redact_for_state


class StateRedactionTests(unittest.TestCase):
    def test_masks_recognizable_token(self) -> None:
        value = redact_for_state("token sk-1234567890abcdefghijk")
        self.assertNotIn("1234567890abcdefghijk", value)
        self.assertIn("[REDACTED]", value)

    def test_bounds_saved_text(self) -> None:
        self.assertEqual(len(redact_for_state("x" * 20, limit=8)), 8)
