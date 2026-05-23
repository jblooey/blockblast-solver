import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

from block_blast_solver import Board, Move, Piece, solve, place_piece, clear_lines


# ── score tracker ─────────────────────────────────────────────────────────────

_SCORES_FILE = Path(__file__).parent / "scores.json"


def _load_scores() -> dict:
    if _SCORES_FILE.exists():
        try:
            return json.loads(_SCORES_FILE.read_text())
        except Exception:
            pass
    return {"games": []}


def _save_game(score: int, streak_broken_after_10: bool) -> None:
    data = _load_scores()
    data["games"].append({
        "date": str(date.today()),
        "score": score,
        "streak_broken_after_10": streak_broken_after_10,
    })
    _SCORES_FILE.write_text(json.dumps(data, indent=2))


def _print_tracker(data: dict) -> None:
    games = data["games"]
    if not games:
        return
    scores  = [g["score"] for g in games]
    avg     = sum(scores) / len(scores)
    best    = max(scores)
    breaks  = sum(1 for g in games if g.get("streak_broken_after_10"))
    print("  ── Tracker ─────────────────────────────────")
    print(f"  Games:          {len(games)}")
    print(f"  Average score:  {avg:.0f}")
    print(f"  Best score:     {best}")
    print(f"  Streak breaks ≥10: {breaks}/{len(games)}")
    print("  ────────────────────────────────────────────")


# ── piece catalog — every orientation ────────────────────────────────────────
#
# Each entry: (display_name, [(row, col), ...] offsets from top-left).
# normalize_piece() is applied at input time so raw offsets here just need
# to be self-consistent; they don't need to start at (0,0).

PIECE_CATALOG: List[Tuple[str, Piece]] = [

    # ── single ──
    ("Single block",                    [(0,0)]),

    # ── dominoes ──
    ("Domino  ██  horizontal",          [(0,0),(0,1)]),
    ("Domino  █/█  vertical",           [(0,0),(1,0)]),

    # ── 1×3 / 3×1 ──
    ("1×3  ███  horizontal",            [(0,0),(0,1),(0,2)]),
    ("3×1  █/█/█  vertical",            [(0,0),(1,0),(2,0)]),

    # ── 1×4 / 4×1 ──
    ("1×4  ████  horizontal",           [(0,0),(0,1),(0,2),(0,3)]),
    ("4×1  █/█/█/█  vertical",          [(0,0),(1,0),(2,0),(3,0)]),

    # ── 1×5 / 5×1 ──
    ("1×5  █████  horizontal",          [(0,0),(0,1),(0,2),(0,3),(0,4)]),
    ("5×1  █/█/█/█/█  vertical",        [(0,0),(1,0),(2,0),(3,0),(4,0)]),

    # ── squares & rectangles ──
    ("2×2 square",                      [(0,0),(0,1),(1,0),(1,1)]),
    ("3×2 rectangle  ███/███",          [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2)]),
    ("2×3 rectangle  ██/██/██",         [(0,0),(0,1),(1,0),(1,1),(2,0),(2,1)]),
    ("3×3 square",                      [(0,0),(0,1),(0,2),
                                          (1,0),(1,1),(1,2),
                                          (2,0),(2,1),(2,2)]),

    # ── 3-cell corner (small L) — 4 rotations ──
    #   foot at bottom-right      foot at bottom-left
    #   ██                        ██
    #   ·█                        █·
    ("Small corner  ██/·█",             [(0,0),(0,1),(1,1)]),
    ("Small corner  ██/█·",             [(0,0),(0,1),(1,0)]),
    #   foot at top-right         foot at top-left
    #   ·█                        █·
    #   ██                        ██
    ("Small corner  ·█/██",             [(0,1),(1,0),(1,1)]),
    ("Small corner  █·/██",             [(0,0),(1,0),(1,1)]),

    # ── L-piece (4 cells) — 4 rotations ──
    #   R0         R1         R2         R3
    #   █·         ███        ██         ··█
    #   █·         █··        ·█         ███
    #   ██                    ·█
    ("L  █·/█·/██",                     [(0,0),(1,0),(2,0),(2,1)]),
    ("L  ███/█··",                      [(0,0),(0,1),(0,2),(1,0)]),
    ("L  ██/·█/·█",                     [(0,0),(0,1),(1,1),(2,1)]),
    ("L  ··█/███",                      [(0,2),(1,0),(1,1),(1,2)]),

    # ── J-piece (4 cells) — 4 rotations ──
    #   R0         R1         R2         R3
    #   ·█         █··        ██         ███
    #   ·█         ███        █·         ··█
    #   ██                    █·
    ("J  ·█/·█/██",                     [(0,1),(1,1),(2,0),(2,1)]),
    ("J  █··/███",                      [(0,0),(1,0),(1,1),(1,2)]),
    ("J  ██/█·/█·",                     [(0,0),(0,1),(1,0),(2,0)]),
    ("J  ███/··█",                      [(0,0),(0,1),(0,2),(1,2)]),

    # ── T-piece (4 cells) — 4 rotations ──
    #   down       right      up         left
    #   ███        █·         ·█·        ·█
    #   ·█·        ██         ███        ██
    #              █·                    ·█
    ("T  ███/·█·  (pointing down)",     [(0,0),(0,1),(0,2),(1,1)]),
    ("T  █·/██/█·  (pointing right)",   [(0,0),(1,0),(1,1),(2,0)]),
    ("T  ·█·/███  (pointing up)",       [(0,1),(1,0),(1,1),(1,2)]),
    ("T  ·█/██/·█  (pointing left)",    [(0,1),(1,0),(1,1),(2,1)]),

    # ── S-piece (4 cells) — 2 orientations ──
    #   horizontal    vertical
    #   ·██           █·
    #   ██·           ██
    #                 ·█
    ("S  ·██/██·  horizontal",          [(0,1),(0,2),(1,0),(1,1)]),
    ("S  █·/██/·█  vertical",           [(0,0),(1,0),(1,1),(2,1)]),

    # ── Z-piece (4 cells) — 2 orientations ──
    #   horizontal    vertical
    #   ██·           ·█
    #   ·██           ██
    #                 █·
    ("Z  ██·/·██  horizontal",          [(0,0),(0,1),(1,1),(1,2)]),
    ("Z  ·█/██/█·  vertical",           [(0,1),(1,0),(1,1),(2,0)]),

    # ── Big-L (5 cells) — 4 rotations ──
    #   R0           R1           R2           R3
    #   ███          ███          ··█          █··
    #   █··          ··█          ··█          █··
    #   █··          ··█          ███          ███
    ("Big-L  ███/█··/█··",              [(0,0),(0,1),(0,2),(1,0),(2,0)]),
    ("Big-L  ███/··█/··█",              [(0,0),(0,1),(0,2),(1,2),(2,2)]),
    ("Big-L  ··█/··█/███",              [(0,2),(1,2),(2,0),(2,1),(2,2)]),
    ("Big-L  █··/█··/███",              [(0,0),(1,0),(2,0),(2,1),(2,2)]),
]


# ── short-code map ────────────────────────────────────────────────────────────
#
# Maps quick-entry codes (lowercase) to 0-based PIECE_CATALOG indices.

SHORT_CODE_MAP: dict = {
    # singles & straights
    "1":    0,  "h2":  1,  "v2":  2,
    "h3":   3,  "v3":  4,  "h4":  5,
    "v4":   6,  "h5":  7,  "v5":  8,
    # squares & rectangles
    "sq":   9,  "sq2": 9,  "r32": 10, "r23": 11, "sq3": 12,
    # 3-cell corners
    "c1":  13,  "c2": 14,  "c3": 15,  "c4": 16,
    # L-piece (4 rotations)
    "l1":  17,  "l2": 18,  "l3": 19,  "l4": 20,
    # J-piece (4 rotations)
    "j1":  21,  "j2": 22,  "j3": 23,  "j4": 24,
    # T-piece (4 rotations)
    "t1":  25,  "t2": 26,  "t3": 27,  "t4": 28,
    # S / Z (2 orientations each)
    "s":   29,  "sv": 30,  "z":  31,  "zv": 32,
    # Big-L (5-cell, 4 rotations)
    "bl1": 33, "bl2": 34, "bl3": 35, "bl4": 36,
}

_QUICK_GROUPS = [
    ("Straights",       ["1",  "h2", "v2", "h3", "v3", "h4", "v4", "h5", "v5"]),
    ("Sq & Rect",       ["sq", "r32","r23","sq3"]),
    ("Corner (3-cell)", ["c1", "c2", "c3", "c4"]),
    ("L & J",           ["l1", "l2", "l3", "l4", "j1", "j2", "j3", "j4"]),
    ("T, S & Z",        ["t1", "t2", "t3", "t4", "s",  "sv", "z",  "zv"]),
    ("Big-L (5-cell)",  ["bl1","bl2","bl3","bl4"]),
]


# ── piece rendering ───────────────────────────────────────────────────────────


def render_piece_rows(piece: Piece) -> List[str]:
    """Return compact ASCII-art lines for a piece using █ and · (used in menus)."""
    if not piece:
        return []
    max_r = max(r for r, c in piece)
    max_c = max(c for r, c in piece)
    grid = [["·"] * (max_c + 1) for _ in range(max_r + 1)]
    for r, c in piece:
        grid[r][c] = "█"
    return ["".join(row) for row in grid]


def render_piece_block(piece: Piece) -> List[str]:
    """Return bordered ASCII-art for a piece — each cell is clearly distinct."""
    if not piece:
        return []
    cell_set = set(map(tuple, piece))
    max_r = max(r for r, c in piece)
    max_c = max(c for r, c in piece)
    nc = max_c + 1
    top = "┌" + "──┬" * (nc - 1) + "──┐"
    mid = "├" + "──┼" * (nc - 1) + "──┤"
    bot = "└" + "──┴" * (nc - 1) + "──┘"
    lines: List[str] = []
    for r in range(max_r + 1):
        lines.append(top if r == 0 else mid)
        lines.append("│" + "".join(("██" if (r, c) in cell_set else "  ") + "│" for c in range(nc)))
    lines.append(bot)
    return lines


def build_piece_menu() -> str:
    """Build a numbered piece selection menu from PIECE_CATALOG."""
    lines = ["", "  ── PIECE MENU ──────────────────────────────────────────", ""]
    for idx, (name, piece) in enumerate(PIECE_CATALOG, start=1):
        art_rows = render_piece_rows(piece)
        prefix = f"  {idx:>2}."
        for i, row in enumerate(art_rows):
            if i == 0:
                lines.append(f"{prefix} {name}")
                lines.append(f"       {row}")
            else:
                lines.append(f"       {row}")
        lines.append("")
    return "\n".join(lines)


PIECE_MENU = build_piece_menu()


def _build_quick_ref() -> str:
    COL_W = 8
    lines = [
        "",
        "━" * 60,
        "  QUICK-CODES  (type code or 1-37; ? = full numbered list)",
        "━" * 60,
    ]
    for group_name, codes in _QUICK_GROUPS:
        lines.append(f"  {group_name}:")
        items = [
            (code, render_piece_rows(PIECE_CATALOG[SHORT_CODE_MAP[code]][1]))
            for code in codes
        ]
        max_rows = max(len(art) for _, art in items)
        lines.append("  " + "".join(f"{c:<{COL_W}}" for c, _ in items))
        for r in range(max_rows):
            lines.append("  " + "".join(
                f"{(art[r] if r < len(art) else ''):<{COL_W}}"
                for _, art in items
            ))
        lines.append("")
    lines.append("━" * 60)
    return "\n".join(lines)


QUICK_REF = _build_quick_ref()


# ── display helpers ───────────────────────────────────────────────────────────


def print_board(board: Board, highlight: set = None) -> None:
    """Print the board. Cells in highlight set are shown as ▓ (new piece)."""
    if highlight is None:
        highlight = set()
    print("   " + " ".join(str(c + 1) for c in range(8)))
    for r, row in enumerate(board):
        cells = []
        for c, val in enumerate(row):
            if (r, c) in highlight:
                cells.append("▓")
            elif val:
                cells.append("█")
            else:
                cells.append(".")
        print(f" {r + 1} {' '.join(cells)}")


def print_divider(char: str = "=", width: int = 52) -> None:
    print(char * width)


# ── input helpers ─────────────────────────────────────────────────────────────


def _try_auto_board() -> Optional[Board]:
    """Attempt board detection from screen. Returns None if uncalibrated or on error."""
    try:
        from screen_reader import load_calibration, take_screenshot, detect_board
        cal = load_calibration()
        if cal is None:
            print("  (No calibration found — run calibrate.py first to enable auto-detect)")
            return None
        print("  Capturing screen...")
        img = take_screenshot()
        board = detect_board(img, cal)
        return board
    except Exception as e:
        print(f"  Auto-detect failed: {e}")
        return None


def input_board() -> Board:
    print("\n=== BOARD INPUT ===")
    print("Options:  auto = detect from screen   blank = empty board")
    print("          or enter each row manually as 8 values (1=filled, 0=empty)\n")

    first = input("  Row 1 (or 'auto' / 'blank'): ").strip().lower()

    if first == "blank":
        board = [[0] * 8 for _ in range(8)]
        print("\nUsing empty board.")
        print_board(board)
        return board

    if first == "auto":
        board = _try_auto_board()
        if board is not None:
            print("\nDetected board:")
            print_board(board)
            ans = input("  Looks right? (y = use it / n = enter manually): ").strip().lower()
            if ans == "y":
                return board
        # Fall through to manual entry
        first = input("  Row 1: ").strip()

    board: Board = []
    for i in range(8):
        raw = first if i == 0 else input(f"  Row {i + 1}: ").strip()
        while True:
            try:
                vals = list(map(int, raw.split()))
                if len(vals) == 8 and all(v in (0, 1) for v in vals):
                    board.append(vals)
                    break
                print("    Need exactly 8 values, each 0 or 1.")
            except ValueError:
                print("    Invalid input. Enter 8 space-separated 0s and 1s.")
            raw = input(f"  Row {i + 1}: ").strip()

    print("\nBoard confirmed:")
    print_board(board)
    return board


def input_streak_info() -> Tuple[int, int]:
    print("\n=== STREAK INFO ===")
    streak = 0
    psince = 0
    while True:
        try:
            streak = int(input("  Current streak count (0 if none): ").strip())
            if streak >= 0:
                break
        except ValueError:
            pass
        print("    Enter a non-negative integer.")
    while True:
        try:
            psince = int(
                input("  Placements since last line clear (0, 1, or 2): ").strip()
            )
            if 0 <= psince <= 2:
                break
        except ValueError:
            pass
        print("    Enter 0, 1, or 2.")
    return streak, psince


def _try_auto_pieces() -> Optional[List[Piece]]:
    """Attempt piece detection from screen. Returns None if uncalibrated or on error."""
    try:
        from screen_reader import load_calibration, take_screenshot, detect_pieces
        cal = load_calibration()
        if cal is None:
            print("  (No calibration found — run calibrate.py first to enable auto-detect)")
            return None
        print("  Capturing screen...")
        img = take_screenshot()
        detected = detect_pieces(img, cal)
        return detected  # list of Piece or None per slot
    except Exception as e:
        print(f"  Auto-detect failed: {e}")
        return None


def input_piece(piece_num: int, auto_piece: Optional[Piece] = None) -> Piece:
    if auto_piece is not None:
        print(f"\n  Piece {piece_num} — auto-detected:")
        for row in render_piece_block(auto_piece):
            print(f"    {row}")
        ans = input("  Use this? (y = yes / n = pick manually): ").strip().lower()
        if ans == "y":
            return list(auto_piece)

    print(QUICK_REF)
    while True:
        raw = input(f"  Piece {piece_num}: ").strip().lower()
        if raw == "?":
            print(PIECE_MENU)
            continue
        # Try short code
        idx = SHORT_CODE_MAP.get(raw)
        if idx is not None:
            _, piece = PIECE_CATALOG[idx]
            for row in render_piece_block(piece):
                print(f"  {row}")
            return list(piece)
        # Try numeric selection
        try:
            choice = int(raw)
            if 1 <= choice <= len(PIECE_CATALOG):
                _, piece = PIECE_CATALOG[choice - 1]
                for row in render_piece_block(piece):
                    print(f"  {row}")
                return list(piece)
        except ValueError:
            pass
        print(f"  Unknown '{raw}'. Enter a code, 1-{len(PIECE_CATALOG)}, or ? for full list.")


# ── result display ────────────────────────────────────────────────────────────


def print_results(
    best_score: float,
    moves: List[Move],
    initial_board: Board,
    pieces: List[Piece],
) -> None:
    print("\n")
    print_divider()
    print("  BEST MOVE SEQUENCE")
    print_divider()
    print(f"  Estimated score gain: {best_score:.0f}")
    print_divider()

    board = initial_board
    for step, move in enumerate(moves):
        print(f"\n  ── Step {step + 1} ──────────────────────────────────────")
        print(f"  Place Piece {move.piece_idx + 1} at Row {move.row + 1}, Col {move.col + 1}")

        # Show board with new piece highlighted before clearing
        piece = pieces[move.piece_idx]
        new_cells = {(move.row + dr, move.col + dc) for dr, dc in piece}
        placed_board = place_piece(board, piece, move.row, move.col)
        print()
        print_board(placed_board, highlight=new_cells)

        # Clear lines and show result if anything was cleared
        cleared_board, lines_cleared, _ = clear_lines(placed_board)
        if lines_cleared > 0:
            word = "line" if lines_cleared == 1 else "lines"
            print(f"\n  → Clears {lines_cleared} {word}! score +{move.score_delta}", end="")
            if move.streak_event == "saved":
                print("  *** STREAK SAVED! ***", end="")
            print(f"  (streak: {move.streak_after})")
            print()
            print_board(cleared_board)
        else:
            print(f"\n  → No lines cleared.  score {move.score_delta:+d}", end="")
            if move.streak_event == "broken":
                print("  *** STREAK BROKEN! ***", end="")
            elif move.streak_after > 0:
                remaining = 3 - move.placements_since_after
                tag = "  WARNING" if remaining == 1 else ""
                print(f"{tag}  ({remaining} placement(s) left before streak breaks)", end="")
            print()

        board = cleared_board

    print()
    print_divider("-")
    final = moves[-1]
    if final.streak_after > 0:
        remain = 3 - final.placements_since_after
        print(f"  Streak: {final.streak_after} | {remain} placement(s) before it breaks next turn.")
    else:
        print("  No active streak after these moves.")
    print_divider()
    return board


# ── overlay results ───────────────────────────────────────────────────────────


def run_with_overlay(
    result_score: float,
    moves: List[Move],
    initial_board: Board,
    pieces: List[Piece],
    cal: dict,
) -> Board:
    """Show move indicators overlaid on the screen and advance step by step."""
    from overlay import BoardOverlay, _wait_for_enter
    from block_blast_solver import place_piece, clear_lines as bl_clear_lines

    print(f"\n  Score gain: {result_score:.0f}")
    print_divider("-")

    overlay = BoardOverlay(cal)
    board = initial_board

    for step, move in enumerate(moves):
        piece = pieces[move.piece_idx]
        placed = place_piece(board, piece, move.row, move.col)

        # Terminal hint for this step
        print(f"\n  Step {step + 1}: Place Piece {move.piece_idx + 1}"
              f"  →  Row {move.row + 1}, Col {move.col + 1}", end="")
        if move.lines_cleared > 0:
            word = "line" if move.lines_cleared == 1 else "lines"
            print(f"   [{move.lines_cleared} {word.upper()} cleared!]", end="")
        if move.streak_event == "saved":
            print("  *** STREAK SAVED ***", end="")
        elif move.streak_event == "broken":
            print("  *** STREAK BROKEN ***", end="")
        print()

        # Overlay shows WHERE on the screen — user presses Enter when done
        overlay.show_step_and_wait(step, move, piece, placed)

        cleared_board, _, _ = bl_clear_lines(placed)
        board = cleared_board

    overlay.clear()
    overlay.close()

    print()
    print_divider("-")
    final = moves[-1]
    if final.streak_after > 0:
        remain = 3 - final.placements_since_after
        print(f"  Streak: {final.streak_after} | {remain} placement(s) before it breaks next turn.")
    else:
        print("  No active streak after these moves.")
    print_divider()
    return board


def run_with_overlay_fast(
    result_score: float,
    moves: List[Move],
    initial_board: Board,
    pieces: List[Piece],
    cal: dict,
) -> Board:
    """Show all 3 moves at once (green/yellow/red) and wait for a single Enter."""
    from overlay import BoardOverlay, _wait_for_enter
    from block_blast_solver import place_piece, clear_lines as bl_clear_lines

    overlay = BoardOverlay(cal)

    # Print all 3 steps at once in terminal
    print(f"\n  Score gain: {result_score:.0f}")
    print_divider("-")
    for step, move in enumerate(moves):
        tag = ["[1] green", "[2] yellow", "[3] red"][step]
        print(f"  {tag}  Piece {move.piece_idx + 1}  →  Row {move.row + 1}, Col {move.col + 1}", end="")
        if move.lines_cleared > 0:
            word = "line" if move.lines_cleared == 1 else "lines"
            print(f"   [{move.lines_cleared} {word} cleared!]", end="")
        if move.streak_event == "saved":
            print("  *** STREAK SAVED ***", end="")
        elif move.streak_event == "broken":
            print("  *** STREAK BROKEN ***", end="")
        print()

    overlay.show_all_steps(moves, pieces)
    _wait_for_enter(overlay.root)
    overlay.clear()
    overlay.close()

    # Compute final board by replaying all moves
    board = initial_board
    for move in moves:
        piece = pieces[move.piece_idx]
        placed = place_piece(board, piece, move.row, move.col)
        board, _, _ = bl_clear_lines(placed)

    print_divider("-")
    final = moves[-1]
    if final.streak_after > 0:
        remain = 3 - final.placements_since_after
        print(f"  Streak: {final.streak_after} | {remain} placement(s) before it breaks next turn.")
    else:
        print("  No active streak after these moves.")
    print_divider()
    return board


# ── actual game score ────────────────────────────────────────────────────────


def actual_turn_score(moves: List[Move], pieces: List[Piece]) -> int:
    """
    Compute real game points for a completed 3-move turn.

    Per the actual game rules:
      - 1 pt per cell placed (linear, unaffected by clears or streak)
      - 1 line cleared:  new_streak × 10
      - n lines cleared: new_streak × n × 20  (combo)
    """
    total = 0
    for move in moves:
        total += len(pieces[move.piece_idx])          # cell placement pts
        if move.lines_cleared == 1:
            total += move.streak_after * 10
        elif move.lines_cleared > 1:
            total += move.streak_after * move.lines_cleared * 20
    return total


# ── entry point ───────────────────────────────────────────────────────────────


def _auto_detect_round(cal: dict):
    """Take one screenshot and return (board, pieces). Pieces may contain None."""
    from screen_reader import take_screenshot, detect_board, detect_pieces
    img = take_screenshot()
    board = detect_board(img, cal)
    pieces = detect_pieces(img, cal)
    return board, pieces


def _detect_pieces_only(cal: dict) -> List[Optional[Piece]]:
    """Scan just the piece slots — skips the board region entirely."""
    from screen_reader import take_screenshot, detect_pieces
    img = take_screenshot()
    return detect_pieces(img, cal)


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fast", action="store_true")
    args, _ = parser.parse_known_args()
    fast_mode = args.fast

    print_divider()
    print("         BLOCK BLAST SOLVER" + ("  [FAST]" if fast_mode else ""))
    print_divider()
    _print_tracker(_load_scores())
    print()

    cal: Optional[dict] = None
    try:
        from screen_reader import load_calibration
        cal = load_calibration()
    except Exception:
        pass

    use_overlay = cal is not None  # overlay on whenever calibration exists

    streak = 0
    psince = 0

    game_score             = 0
    round_num              = 1
    streak_broken_after_10 = False
    board: Optional[Board] = None  # carried over between rounds in fast mode

    if not cal:
        board_override = input_board()
    else:
        board_override = None  # always detect from screen

    while True:
        print(f"\n{'='*52}")
        print(f"  ROUND {round_num}")
        print(f"{'='*52}")

        if cal:
            skip_board_scan = fast_mode and board is not None

            if skip_board_scan:
                print("  Scanning pieces...")
                detected_pieces = _detect_pieces_only(cal)
                print("\n  Board (carried over):")
                print_board(board)
            else:
                print("  Detecting from screen...")
                board, detected_pieces = _auto_detect_round(cal)
                print()
                print_board(board)

            if fast_mode:
                # No prompt — display pieces and solve immediately
                pieces: List[Piece] = []
                for i, ap in enumerate(detected_pieces):
                    if ap is not None:
                        print(f"\n  Piece {i + 1}:")
                        for row in render_piece_block(ap):
                            print(f"    {row}")
                        pieces.append(list(ap))
                    else:
                        print(f"\n  Piece {i + 1}: not detected — pick manually")
                        pieces.append(input_piece(i + 1))
            else:
                while True:
                    pieces = []
                    for i, ap in enumerate(detected_pieces):
                        if ap is not None:
                            print(f"\n  Piece {i + 1}:")
                            for row in render_piece_block(ap):
                                print(f"    {row}")
                            pieces.append(list(ap))
                        else:
                            print(f"\n  Piece {i + 1}: not detected — pick manually")
                            pieces.append(input_piece(i + 1))

                    cmd = input("\n  Enter to solve   r = re-scan pieces: ").strip().lower()
                    if cmd == "r":
                        print("  Re-scanning pieces...")
                        detected_pieces = _detect_pieces_only(cal)
                    else:
                        break
        else:
            board = board_override
            pieces = []
            for i in range(1, 4):
                pieces.append(input_piece(i))

        print("\nSolving...")
        result_score, moves = solve(board, pieces, streak, psince)

        if moves is None:
            print("\nNo valid move sequence found. Board may be too full.")
            sys.exit(1)

        if use_overlay and fast_mode:
            board = run_with_overlay_fast(result_score, moves, board, pieces, cal)
        elif use_overlay:
            board = run_with_overlay(result_score, moves, board, pieces, cal)
        else:
            board = print_results(result_score, moves, board, pieces)

        turn_pts   = actual_turn_score(moves, pieces)
        game_score += turn_pts
        print(f"  Score this turn: +{turn_pts}   │   Session total: {game_score}")
        print_divider("-")

        # Check if streak was broken this round after having reached ≥10
        for i, move in enumerate(moves):
            if move.streak_event == "broken":
                prior = streak if i == 0 else moves[i - 1].streak_after
                if prior >= 10:
                    streak_broken_after_10 = True

        streak = moves[-1].streak_after
        psince = moves[-1].placements_since_after
        round_num += 1

        print()
        cont = input("  Press Enter for next round (q to quit): ").strip().lower()
        if cont == "q":
            print(f"\n  Final score: {game_score}")
            ans = input("  Save score to tracker? (y/n): ").strip().lower()
            if ans == "y":
                _save_game(game_score, streak_broken_after_10)
                print("  Saved!")
            _print_tracker(_load_scores())
            print("\nGood game!")
            break

        if not cal:
            board_override = input_board()


if __name__ == "__main__":
    main()
