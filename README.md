# Block Blast Solver

A CLI solver for Block Blast that evaluates all valid piece placements and orderings to suggest the highest-scoring move sequence.

---

## Setup

```bash
cd blockblast_solver
pip install -r requirements.txt
```

> The CLI solver (`runner.py`) only needs the standard library. The packages in `requirements.txt` are included for future vision/automation features.

---

## Running

```bash
python runner.py
```

The tool walks you through four input steps, then prints the best move sequence.

---

## Input Guide

### Step 1 — Board

Enter the 8×8 board **row by row**, top to bottom. Use:
- `1` for a filled cell
- `0` for an empty cell

**Example** (row 1 is the top of the board):
```
Row 1: 0 0 0 0 0 0 0 0
Row 2: 0 0 0 0 0 0 0 0
Row 3: 1 1 1 0 0 0 0 0
Row 4: 1 1 1 1 1 0 0 0
Row 5: 1 1 1 1 1 1 0 0
Row 6: 1 1 1 1 1 1 1 0
Row 7: 1 1 1 1 1 1 1 1
Row 8: 1 1 1 1 1 1 1 1
```

---

### Step 2 — Streak Info

- **Current streak count** — how many consecutive "clearing turns" you have. Enter `0` if you have no active streak.
- **Placements since last line clear** — how many individual piece placements have happened since the last time you cleared a line. Enter `0`, `1`, or `2`.

---

### Step 3 — Pieces (three in total)

For each piece, enter its cell offsets **one per line** relative to its top-left corner, then type `done`.

**Row 0, Col 0 is the top-left cell of the piece's bounding box.**

#### Examples

| Piece | Input |
|-------|-------|
| Single block | `0 0` |
| 1×3 horizontal | `0 0` / `0 1` / `0 2` |
| 3×1 vertical | `0 0` / `1 0` / `2 0` |
| 2×2 square | `0 0` / `0 1` / `1 0` / `1 1` |
| L-piece (right foot) | `0 0` / `1 0` / `2 0` / `2 1` |
| J-piece (left foot) | `0 1` / `1 1` / `2 0` / `2 1` |
| T-piece | `0 0` / `0 1` / `0 2` / `1 1` |
| S-piece | `0 1` / `0 2` / `1 0` / `1 1` |
| Z-piece | `0 0` / `0 1` / `1 1` / `1 2` |
| 3×3 square | `0 0` / `0 1` / `0 2` / `1 0` / `1 1` / `1 2` / `2 0` / `2 1` / `2 2` |

The solver normalises your offsets automatically, so `1 1` / `1 2` / `2 1` is treated the same as `0 0` / `0 1` / `1 0`.

---

## Reading the Output

```
====================================================
  BEST MOVE SEQUENCE
====================================================
  Estimated score gain: 450
====================================================

  Step 1: Place Piece 2 at Row 5, Col 3
    [CLEARS 2 LINES!]  score +210
    Streak extended to 4

  Step 2: Place Piece 1 at Row 7, Col 1
    No lines cleared.  score +0
    2 more placement(s) without a clear will break the streak.

  Step 3: Place Piece 3 at Row 2, Col 6
    [CLEARS 1 LINE!]  score +130
    *** STREAK SAVED! (+300 bonus applied) ***
    Streak extended to 5

----------------------------------------------------
  After these moves — streak: 5 | 3 placement(s) before streak breaks next turn.
====================================================
```

- **Row / Col** — 1-indexed board coordinates (Row 1 = top, Col 1 = left).
- `[CLEARS N LINES!]` — that placement completes at least one full row or column.
- `STREAK SAVED!` — you were on your last allowed placement without a clear and this one rescued the streak.
- `STREAK BROKEN!` — no way to avoid losing the streak with this sequence.
- The warning line counts how many more non-clearing placements you can make before the streak resets.

---

## Scoring System

| Event | Points |
|-------|--------|
| Each unique cell in a cleared row/column | +10 |
| 2 lines cleared simultaneously | +50 combo bonus |
| 3 lines cleared simultaneously | +100 combo bonus |
| 4+ lines cleared simultaneously | +150 + 50 per extra line |
| Clearing a line on the last allowed placement (streak save) | +300 |
| Failing to clear a line on the last allowed placement (streak break) | −500 |

The solver also applies a **board heuristic** at the end of each full sequence to prefer boards that are open, low on hidden holes, and have even column fill heights.

---

## How the Solver Works

1. Generates all **6 permutations** of the 3 piece ordering (since the order you place them can open or block positions).
2. For each ordering, exhaustively tries every valid anchor position for each piece in turn.
3. Tracks score, streak state, and board quality across all three placements.
4. Returns the sequence with the highest combined score + board heuristic.

Typical solve time: **1–5 seconds** depending on board fill and piece sizes.
