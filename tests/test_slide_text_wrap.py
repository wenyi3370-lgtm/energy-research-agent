from __future__ import annotations

import unittest

from scripts.wrap_slide_text import token_width, tokenize, wrap_text


class SlideTextWrapTests(unittest.TestCase):
    def test_latin_words_and_kpi_units_are_atomic_tokens(self) -> None:
        tokens = tokenize("M&V口径 33% 3亿平方米/年")
        self.assertIn("M&V", tokens)
        self.assertIn("33%", tokens)
        self.assertIn("3亿平方米/年", tokens)

    def test_wrap_does_not_split_numeric_unit_token(self) -> None:
        lines = wrap_text("市场份额33%仍需核验", token_width("市场份额", 20) + 1, 20)
        self.assertTrue(any("33%" in line for line in lines))
        self.assertFalse(any(line == "33" for line in lines))


if __name__ == "__main__":
    unittest.main()
