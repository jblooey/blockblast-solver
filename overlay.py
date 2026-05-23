"""
Transparent, click-through overlay that draws move indicators directly on screen.

On macOS, requires pyobjc for click-through:
    pip install pyobjc-framework-Cocoa
Without it the overlay still shows but blocks clicks to iPhone Mirroring.
"""

import sys
import select
import tkinter as tk
from typing import List, Set, Tuple

# (fill color, text color) per step
STEP_COLORS = [
    ("#00E676", "#000000"),  # step 1 — bright green
    ("#FF9100", "#000000"),  # step 2 — orange
    ("#40C4FF", "#000000"),  # step 3 — light blue
]
CLEAR_DASH_COLOR = "#FFFFFF"


def _wait_for_enter(root: tk.Tk) -> None:
    """Keep tkinter alive while blocking on Enter in the terminal."""
    while True:
        root.update()
        ready, _, _ = select.select([sys.stdin], [], [], 0.05)
        if ready:
            sys.stdin.readline()
            return


class BoardOverlay:
    _WINDOW_TITLE = "__bb_overlay__"

    def __init__(self, cal: dict) -> None:
        bx1, by1, bx2, by2 = cal["board"]
        self.bx1 = bx1
        self.by1 = by1
        self.cell_w = (bx2 - bx1) / 8
        self.cell_h = (by2 - by1) / 8

        # Piece tray: split piece_row evenly into 3 slots
        pr = cal.get("piece_row")
        if pr:
            px1, py1, px2, py2 = pr
            slot_w = (px2 - px1) / 3
            self.piece_slots = [
                (px1 + i * slot_w, py1, px1 + (i + 1) * slot_w, py2)
                for i in range(3)
            ]
        else:
            self.piece_slots = []

        self.root = tk.Tk()
        self.root.title(self._WINDOW_TITLE)
        self.root.overrideredirect(True)           # no title bar / chrome
        self.root.attributes("-topmost", True)     # always on top
        self.root.wm_attributes("-transparent", True)
        self.root.config(bg="systemTransparent")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{sw}x{sh}+0+0")

        self.canvas = tk.Canvas(
            self.root, width=sw, height=sh,
            bg="systemTransparent", highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.root.update()
        self._set_click_through()

    def _set_click_through(self) -> None:
        """Tell macOS to pass all mouse events through this window."""
        try:
            from AppKit import NSApp
            for win in NSApp.windows():
                if str(win.title()) == self._WINDOW_TITLE:
                    win.setIgnoresMouseEvents_(True)
                    break
        except Exception:
            # pyobjc not installed — overlay shows but isn't click-through
            pass

    # ── drawing ───────────────────────────────────────────────────────────────

    def _cell_bbox(self, r: int, c: int) -> Tuple[int, int, int, int]:
        x1 = int(self.bx1 + c * self.cell_w)
        y1 = int(self.by1 + r * self.cell_h)
        return x1, y1, int(x1 + self.cell_w), int(y1 + self.cell_h)

    def _draw(
        self,
        step: int,
        piece_idx: int,
        piece_cells: List[Tuple[int, int]],
        clear_cells: Set[Tuple[int, int]],
    ) -> None:
        self.canvas.delete("all")
        fill, text_color = STEP_COLORS[step % len(STEP_COLORS)]
        pad = 4
        font_size = max(10, int(min(self.cell_w, self.cell_h) * 0.40))
        pc_set = set(map(tuple, piece_cells))

        # Cells that will clear (dashed white outline, not covering piece)
        for r, c in clear_cells:
            if (r, c) not in pc_set:
                x1, y1, x2, y2 = self._cell_bbox(r, c)
                self.canvas.create_rectangle(
                    x1 + pad, y1 + pad, x2 - pad, y2 - pad,
                    outline=CLEAR_DASH_COLOR, fill="", width=3, dash=(8, 4),
                )

        # Piece cells — solid filled rectangle with step number
        for r, c in piece_cells:
            x1, y1, x2, y2 = self._cell_bbox(r, c)
            # Shadow for visibility on any background
            self.canvas.create_rectangle(
                x1 + pad + 2, y1 + pad + 2, x2 - pad + 2, y2 - pad + 2,
                fill="black", outline="",
            )
            self.canvas.create_rectangle(
                x1 + pad, y1 + pad, x2 - pad, y2 - pad,
                fill=fill, outline="white", width=2,
            )
            self.canvas.create_text(
                (x1 + x2) // 2, (y1 + y2) // 2,
                text=str(step + 1), fill=text_color,
                font=("Arial", font_size, "bold"),
            )

        # Label above board (shadow + colour)
        lx = int(self.bx1 + 4 * self.cell_w)
        ly = max(20, int(self.by1 - 30))
        label = f"Step {step + 1}  ·  Piece {piece_idx + 1}"
        self.canvas.create_text(lx + 2, ly + 2, text=label, fill="black",
                                font=("Arial", 17, "bold"))
        self.canvas.create_text(lx, ly, text=label, fill=fill,
                                font=("Arial", 17, "bold"))

        self.root.update()

    # ── public API ────────────────────────────────────────────────────────────

    def show_step_and_wait(
        self,
        step: int,
        move,            # Move namedtuple from block_blast_solver
        piece: list,     # list of (dr, dc) offsets
        placed_board,    # board state AFTER placing piece, BEFORE clearing
    ) -> None:
        """Draw the overlay for this step and block until the user presses Enter."""
        piece_cells = [(move.row + dr, move.col + dc) for dr, dc in piece]

        # Determine which cells will be cleared
        clear_cells: Set[Tuple[int, int]] = set()
        for r in range(8):
            if all(placed_board[r][c] == 1 for c in range(8)):
                for c in range(8):
                    clear_cells.add((r, c))
        for c in range(8):
            if all(placed_board[r][c] == 1 for r in range(8)):
                for r in range(8):
                    clear_cells.add((r, c))

        self._draw(step, move.piece_idx, piece_cells, clear_cells)
        self._highlight_piece_slot(move.piece_idx, STEP_COLORS[step % len(STEP_COLORS)][0])
        _wait_for_enter(self.root)

    def _highlight_piece_slot(self, piece_idx: int, color: str) -> None:
        """Draw a pulsing circle around the piece slot in the tray."""
        if not self.piece_slots or piece_idx >= len(self.piece_slots):
            return
        x1, y1, x2, y2 = self.piece_slots[piece_idx]
        pad = 6
        # Shadow oval
        self.canvas.create_oval(
            x1 - pad + 3, y1 - pad + 3, x2 + pad + 3, y2 + pad + 3,
            outline="black", fill="", width=5,
        )
        # Coloured oval matching the step colour
        self.canvas.create_oval(
            x1 - pad, y1 - pad, x2 + pad, y2 + pad,
            outline=color, fill="", width=4,
        )
        self.root.update()

    def clear(self) -> None:
        self.canvas.delete("all")
        self.root.update()

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
