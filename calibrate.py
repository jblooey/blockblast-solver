"""
Run this once to calibrate screen regions for auto-detection.

  python3 calibrate.py

You will hover your cursor over corners of the board and piece boxes,
pressing Enter each time to lock in the position.

Requirements:
  - Block Blast must be visible on screen (via iPhone Mirroring)
  - Terminal must have Screen Recording permission:
      System Settings > Privacy & Security > Screen Recording > enable Terminal
"""

import time
import pyautogui
from screen_reader import (
    save_calibration, take_screenshot, detect_board, detect_pieces, detect_scale
)
from runner import print_board, render_piece_block


def hover_and_capture(label: str) -> tuple:
    print(f"\n  >> Hover cursor at: {label}")
    input("     Press Enter to capture position...")
    pos = pyautogui.position()
    print(f"     Captured: ({pos.x}, {pos.y})")
    return pos.x, pos.y


def calibrate():
    print("=" * 56)
    print("   BLOCK BLAST — SCREEN CALIBRATION")
    print("=" * 56)
    print()
    print("Before starting:")
    print("  1. Open iPhone Mirroring and launch Block Blast.")
    print("  2. Get to a state where the board and 3 pieces are visible.")
    print("  3. Grant Screen Recording to Terminal if prompted.")
    print()
    input("Press Enter when ready...")

    scale = detect_scale()
    print(f"\n  Display scale detected: {scale:.1f}x {'(retina)' if scale > 1 else ''}")

    # ── Board region ──────────────────────────────────────────────────────────
    print("\n── Step 1: Board corners ────────────────────────────────────────")
    print("  Click the EXACT corners of the 8×8 game grid (not the phone border).")

    bx1, by1 = hover_and_capture("TOP-LEFT corner of the board grid")
    bx2, by2 = hover_and_capture("BOTTOM-RIGHT corner of the board grid")

    cell_size = (bx2 - bx1) / 8
    cal = {
        "board": [bx1, by1, bx2, by2],
        "pieces": [],
        "cell_size": cell_size,
        "scale": scale,
    }

    # Verify board
    print("\n  Taking screenshot to verify board detection...")
    time.sleep(0.3)
    img = take_screenshot()
    board = detect_board(img, cal)
    print()
    print_board(board)

    ans = input("\n  Does the board look correct? (y = save and continue / n = quit): ").strip().lower()
    if ans != "y":
        print("  Try again — re-run calibrate.py and aim more carefully at the grid corners.")
        return

    # ── Piece row ─────────────────────────────────────────────────────────────
    print("\n── Step 2: Piece area ───────────────────────────────────────────────")
    print("  Capture ONE box that covers ALL THREE piece slots together.")
    print("  Top-left = above the leftmost piece, bottom-right = below the rightmost.")
    print("  Include a few pixels of padding on each side.")

    prx1, pry1 = hover_and_capture("TOP-LEFT corner of the piece area (all 3 slots)")
    prx2, pry2 = hover_and_capture("BOTTOM-RIGHT corner of the piece area (all 3 slots)")
    cal["piece_row"] = [prx1, pry1, prx2, pry2]
    cal.pop("pieces", None)

    # Verify piece detection
    print("\n  Taking screenshot to verify piece detection...")
    time.sleep(0.3)
    img = take_screenshot()

    # Debug: show raw brightness map of the piece row
    from screen_reader import _scale_box, PIECE_FILL_THRESHOLD
    import numpy as np
    scale_val = cal["scale"]
    px1, py1, px2, py2 = _scale_box([prx1, pry1, prx2, pry2], scale_val)
    row_region = img[py1:py2, px1:px2, :3]
    rh, rw = row_region.shape[:2]
    bright_map = np.mean(row_region, axis=2) > PIECE_FILL_THRESHOLD
    rows_to_show = min(rh, 20)
    cols_to_show = min(rw, 80)
    row_step = max(1, rh // rows_to_show)
    col_step = max(1, rw // cols_to_show)
    print(f"\n  Piece row ({rw}×{rh} px):")
    for r in range(0, rh, row_step):
        print("  " + "".join("█" if bright_map[r, c] else "·"
                              for c in range(0, rw, col_step)))

    detected = detect_pieces(img, cal)

    print()
    all_ok = True
    for i, piece in enumerate(detected, 1):
        if piece:
            print(f"  Piece {i} detected:")
            for row in render_piece_block(piece):
                print(f"    {row}")
        else:
            print(f"  Piece {i}: nothing detected")
            all_ok = False
        print()

    if not all_ok:
        print("  Some pieces weren't detected.")
        print("  Make sure the box spans all 3 slots and the pieces are visible.")

    ans = input("  Save this calibration? (y/n): ").strip().lower()
    if ans == "y":
        save_calibration(cal)
        print("\n  Calibration saved to calibration.json")
        print("  Run  python3 runner.py  and type 'auto' at the board/piece prompts.")
    else:
        print("  Calibration discarded. Re-run calibrate.py to try again.")


if __name__ == "__main__":
    calibrate()
