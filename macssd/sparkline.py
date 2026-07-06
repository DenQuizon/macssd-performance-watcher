"""Turn a list of numbers into a tiny unicode bar chart, e.g. ▁▂▅▇▃▂.

Pure and side-effect free so it is easy to test. Bars are scaled from 0 to the
highest value in the window, so an idle series shows flat low bars and a burst
stands out.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

_BLOCKS = "▁▂▃▄▅▆▇█"


def _clean(value: object) -> float:
    """Coerce to a finite, non-negative float; anything odd becomes 0."""
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return num if math.isfinite(num) and num > 0 else 0.0


def spark(values: Iterable[float], width: int = 10) -> str:
    """Render the last `width` values as a unicode sparkline padded to `width`."""
    vals = [_clean(v) for v in values][-width:]
    if not vals:
        return " " * width
    hi = max(vals)
    if hi <= 0:
        line = _BLOCKS[0] * len(vals)
    else:
        line = "".join(
            _BLOCKS[min(len(_BLOCKS) - 1, int(v / hi * (len(_BLOCKS) - 1)))]
            for v in vals
        )
    return line.rjust(width)
