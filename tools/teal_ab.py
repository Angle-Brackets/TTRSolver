"""Does the relational teal clause change what this frame sees?

One grab, read twice: with the clause on, and with only the original
+/-34 colour box. If both find the same plates, the clause is doing
nothing here and the scene never needed it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np                                    # noqa: E402
from solver.live import vision                        # noqa: E402
from solver.live.watch import Capture                 # noqa: E402


def main() -> int:
    frame = Capture().grab()
    if frame is None:
        print("  no frame -- is the game running?")
        return 1
    print(f"  frame {frame.shape[1]}x{frame.shape[0]}")

    both = vision.find_plates(frame)

    original = vision.teal_mask

    def box_only(f):
        delta = np.abs(f[:, :, :3].astype(np.int16) - np.array(vision.TEAL))
        return np.all(delta < vision.TOLERANCE, axis=2)

    vision.teal_mask = box_only
    try:
        boxed = vision.find_plates(frame)
    finally:
        vision.teal_mask = original

    print(f"  box only        : {len(boxed)} plate(s)")
    for p in boxed:
        x0, y0, x1, y1 = p.slot
        print(f"     {x1 - x0}x{y1 - y0} at ({x0},{y0})")
    print(f"  box + relational: {len(both)} plate(s)")
    for p in both:
        x0, y0, x1, y1 = p.slot
        print(f"     {x1 - x0}x{y1 - y0} at ({x0},{y0})")

    if len(boxed) == len(both):
        print("\n  SAME. The relational clause is not what found these --"
              "\n  the original box was sufficient on this scene.")
    else:
        print("\n  DIFFERENT. The clause is carrying this scene.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
