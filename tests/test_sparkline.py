"""Boundary tests for the sparkline helper.

Authored by agy (Gemini 3.5 Flash) as the test role in the orchestration;
integrated by Claude. Run with:
    "./.venv/bin/python" -m tests.test_sparkline
"""

from macssd.sparkline import spark

# 1. empty list gives all spaces
assert spark([], 5) == " " * 5, "Empty list should return all spaces"

# 2. a list shorter than width is right padded: ends with bars, starts with spaces
res_short = spark([1, 2], 5)
assert res_short.startswith(" ") and not res_short.endswith(" ") and len(res_short) == 5, (
    "List shorter than width should start with spaces and end with bars"
)

# 3. all equal positive numbers give identical repeated characters
res_equal = spark([5, 5, 5], 3)
assert len(set(res_equal.strip())) == 1, (
    "All equal positive numbers should give identical repeated characters"
)

# 4. negative numbers are treated as zero and do not crash
try:
    res_neg = spark([-1, -2, 0], 3)
    assert len(res_neg) == 3, "Negative numbers should be treated as zero and not crash"
except Exception as e:  # noqa: BLE001
    assert False, f"Negative numbers caused a crash: {e}"

# 5. a custom width changes output length to that width
assert len(spark([1, 2, 3], 10)) == 10, "Custom width should change output length"

# 6. a normal list returns a non-empty string
assert len(spark([1, 2, 3], 3).strip()) > 0, "Normal list should return a non-empty string"

print("ALL PASS")
