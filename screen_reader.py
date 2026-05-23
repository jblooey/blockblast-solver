import json
import numpy as np
import pyautogui
from pathlib import Path
from typing import Optional, List, Tuple

CALIBRATION_FILE = Path(__file__).parent / "calibration.json"

# Filled board cells are saturated colors (orange, purple, teal…); empty cells are
# black/dark gray regardless of glow from neighbors. Use max-min channel spread
# rather than brightness so glow doesn't cause false "filled" reads.
BOARD_COLOR_THRESHOLD = 30   # min R/G/B spread for a cell to count as filled
# Piece cells can be slightly less bright (darker colours like deep red).
PIECE_FILL_THRESHOLD = 70

Board = List[List[int]]
Piece = List[Tuple[int, int]]


# ── calibration I/O ───────────────────────────────────────────────────────────

def save_calibration(data: dict) -> None:
    with open(CALIBRATION_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_calibration() -> Optional[dict]:
    if CALIBRATION_FILE.exists():
        with open(CALIBRATION_FILE) as f:
            return json.load(f)
    return None


# ── screenshot ────────────────────────────────────────────────────────────────

def take_screenshot() -> np.ndarray:
    """Full-screen capture. Returns RGB numpy array (may be 2x logical size on retina)."""
    img = pyautogui.screenshot()
    return np.array(img)


def detect_scale() -> float:
    """Return pixel-to-logical-pixel ratio (2.0 on retina, 1.0 otherwise)."""
    logical_w, _ = pyautogui.size()
    img = take_screenshot()
    _, img_w = img.shape[:2]
    return img_w / logical_w


# ── detection helpers ─────────────────────────────────────────────────────────

def _sample_brightness(region: np.ndarray, cy: int, cx: int, radius: int = 3) -> float:
    """Mean RGB brightness of a small patch centred at (cy, cx). Ignores alpha."""
    h, w = region.shape[:2]
    y1 = max(0, cy - radius)
    y2 = min(h, cy + radius + 1)
    x1 = max(0, cx - radius)
    x2 = min(w, cx + radius + 1)
    patch = region[y1:y2, x1:x2, :3].astype(np.float32)   # RGB only
    return float(patch.mean())


def _sample_color_spread(region: np.ndarray, cy: int, cx: int, radius: int = 3) -> float:
    """Max-minus-min of per-channel means in a small patch. High for saturated colors,
    near zero for gray/black (even if brightened by glow from adjacent filled cells)."""
    h, w = region.shape[:2]
    y1 = max(0, cy - radius)
    y2 = min(h, cy + radius + 1)
    x1 = max(0, cx - radius)
    x2 = min(w, cx + radius + 1)
    patch = region[y1:y2, x1:x2, :3].astype(np.float32)
    per_ch = patch.mean(axis=(0, 1))   # shape (3,): mean R, mean G, mean B
    return float(per_ch.max() - per_ch.min())


def _scale_box(box: list, scale: float) -> tuple:
    x1, y1, x2, y2 = box
    return int(x1 * scale), int(y1 * scale), int(x2 * scale), int(y2 * scale)


# ── board detection ───────────────────────────────────────────────────────────

def detect_board(img: np.ndarray, cal: dict) -> Board:
    """
    Sample the centre of each of the 64 board cells and threshold by brightness.
    Returns an 8x8 list of 0 (empty) / 1 (filled).
    """
    scale = cal.get("scale", 1.0)
    bx1, by1, bx2, by2 = _scale_box(cal["board"], scale)
    region = img[by1:by2, bx1:bx2, :3]
    h, w = region.shape[:2]
    cell_h = h / 8
    cell_w = w / 8

    board = []
    for r in range(8):
        row = []
        for c in range(8):
            cy = int((r + 0.5) * cell_h)
            cx = int((c + 0.5) * cell_w)
            spread = _sample_color_spread(region, cy, cx)
            row.append(1 if spread > BOARD_COLOR_THRESHOLD else 0)
        board.append(row)
    return board


# ── piece detection ───────────────────────────────────────────────────────────

def _find_segments(arr: np.ndarray) -> list:
    """Return list of (start, end) for contiguous True runs in a 1D boolean array."""
    segs, in_run, start = [], False, 0
    for i, v in enumerate(arr):
        if v and not in_run:
            start = i; in_run = True
        elif not v and in_run:
            segs.append((start, i)); in_run = False
    if in_run:
        segs.append((start, len(arr)))
    return segs


def _cell_size_from_gaps(bright: np.ndarray) -> Optional[float]:
    """
    Scan rows and columns for 2–5 bright segments separated by dark gaps.
    Measure the start-to-start pitch between consecutive segments (= segment
    width + gap width = full cell pitch). Returns the median pitch.

    Pitch, not segment width, is the right value to use for scanning because
    the scanning loop places sample centres at 0.5·cs, 1.5·cs, 2.5·cs … and
    needs cs = pitch so that centres land in the middle of each cell.
    """
    h, w = bright.shape
    pitches = []
    for r in range(h):
        segs = _find_segments(bright[r])
        if 2 <= len(segs) <= 5:
            valid = [s for s in segs if s[1] - s[0] >= 4]
            for i in range(1, len(valid)):
                p = valid[i][0] - valid[i - 1][0]
                if p >= 5:
                    pitches.append(p)
    for c in range(w):
        segs = _find_segments(bright[:, c])
        if 2 <= len(segs) <= 5:
            valid = [s for s in segs if s[1] - s[0] >= 4]
            for i in range(1, len(valid)):
                p = valid[i][0] - valid[i - 1][0]
                if p >= 5:
                    pitches.append(p)
    if not pitches:
        return None
    pitches.sort()
    return float(pitches[len(pitches) // 2])


def _detect_pieces_from_row(img: np.ndarray, box: list, scale: float) -> List[Optional[Piece]]:
    """
    Detect all 3 pieces from a single wide calibrated box covering the piece row.

    1. Crop to bright bounding box.
    2. Separate pieces by the large dark column gaps between piece slots.
    3. For each piece, crop its bounding box and estimate cell size independently
       using _estimate_cell_size (blob bounding box + most-square heuristic).
    4. Scan each piece on a cs-spaced grid to reconstruct its shape.
    """
    px1, py1, px2, py2 = _scale_box(box, scale)
    if px2 <= px1 or py2 <= py1:
        return [None, None, None]

    region = img[py1:py2, px1:px2]
    h, w = region.shape[:2]
    bright = np.mean(region[:, :, :3], axis=2) > PIECE_FILL_THRESHOLD

    # Remove outer dark padding
    bright_rows = np.where(np.any(bright, axis=1))[0]
    bright_cols = np.where(np.any(bright, axis=0))[0]
    if len(bright_rows) == 0 or len(bright_cols) == 0:
        return [None, None, None]
    margin = 3
    r0 = max(0, int(bright_rows[0]) - margin)
    r1 = min(h, int(bright_rows[-1]) + margin + 1)
    c0 = max(0, int(bright_cols[0]) - margin)
    c1 = min(w, int(bright_cols[-1]) + margin + 1)
    region = region[r0:r1, c0:c1]
    bright = bright[r0:r1, c0:c1]
    h, w = region.shape[:2]

    # Split into 3 piece slots using the 2 largest dark column gaps.
    # This is robust even when pieces have internal cell gaps: inter-piece gaps
    # are always much wider than intra-piece gaps, so the 2 largest dark runs
    # reliably identify the 2 separators between the 3 slots.
    col_occ = np.any(bright, axis=0)
    dark_segs = _find_segments(~col_occ)
    inner_dark = [(s, e) for s, e in dark_segs if s > 0 and e < w and e - s >= 3]

    if len(inner_dark) >= 2:
        seps = sorted(inner_dark, key=lambda sg: sg[1] - sg[0], reverse=True)[:2]
        seps = sorted(seps, key=lambda sg: sg[0])
        piece_col_ranges = [
            (0, seps[0][0]),
            (seps[0][1], seps[1][0]),
            (seps[1][1], w),
        ]
    else:
        # Fallback: top 3 bright column segments
        bright_segs = _find_segments(col_occ)
        bright_segs = sorted(bright_segs, key=lambda sg: sg[1] - sg[0], reverse=True)[:3]
        piece_col_ranges = sorted(bright_segs, key=lambda sg: sg[0])

    # First pass: crop each piece to its tight bright bounding box, estimate cell size
    slot_data = []
    for c_start, c_end in piece_col_ranges:
        if c_start >= c_end:
            slot_data.append(None)
            continue
        slot_bright = bright[:, c_start:c_end]
        br = np.where(np.any(slot_bright, axis=1))[0]
        bc = np.where(np.any(slot_bright, axis=0))[0]
        if len(br) == 0 or len(bc) == 0:
            slot_data.append(None)
            continue
        r_start = int(br[0])
        r_end = int(br[-1]) + 1
        c_tight = c_start + int(bc[0])
        c_tight_end = c_start + int(bc[-1]) + 1
        pr = region[r_start:r_end, c_tight:c_tight_end]
        if pr.shape[0] < 4 or pr.shape[1] < 4:
            slot_data.append(None)
            continue
        cs = _estimate_cell_size(pr)
        slot_data.append((pr, cs))

    # Use the minimum valid cell size across all pieces.
    # Square pieces (N×N) whose cells are solid blobs return N·cs instead of cs,
    # inflating the median. The minimum picks up the correct estimate from any
    # non-square piece or any piece whose cell gaps were measured directly.
    valid_cs = [cs for item in slot_data
                if item is not None
                for cs in [item[1]]
                if cs is not None and cs >= 4]
    if not valid_cs:
        return [None, None, None]
    shared_cs = min(valid_cs)

    # Second pass: scan each piece with the shared cell size
    pieces: List[Optional[Piece]] = []
    for item in slot_data:
        if item is None:
            pieces.append(None)
            continue
        pr, _ = item
        ph, pw = pr.shape[:2]

        filled: set = set()
        max_r = max(1, round(ph / shared_cs))
        max_c = max(1, round(pw / shared_cs))
        for r in range(max_r + 1):
            for c in range(max_c + 1):
                cy = int((r + 0.5) * shared_cs)
                cx = int((c + 0.5) * shared_cs)
                if cy >= ph or cx >= pw:
                    continue
                if _sample_brightness(pr, cy, cx) > PIECE_FILL_THRESHOLD:
                    filled.add((r, c))

        if not filled:
            pieces.append(None)
            continue
        min_r = min(r for r, c in filled)
        min_c = min(c for r, c in filled)
        pieces.append(sorted((r - min_r, c - min_c) for r, c in filled))

    while len(pieces) < 3:
        pieces.append(None)
    return pieces[:3]


def _estimate_cell_size(region: np.ndarray) -> Optional[float]:
    """
    Estimate how many pixels wide one piece cell is in this region.

    Strategy (in order):
    1. Gap-based: scan rows/cols for 2–5 bright segments; each segment ≈ one cell.
       Unambiguous for any piece that has visible dark borders between cells.
    2. Blob-based fallback for fully solid pieces (no visible cell gaps).
       Uses the smallest blob as the single-cell reference to avoid overestimating
       when one large connected blob spans multiple cells.
    """
    try:
        import cv2
    except ImportError:
        return None

    bright = (np.mean(region[:, :, :3], axis=2) > PIECE_FILL_THRESHOLD).astype(np.uint8)

    # 1. Gap-based: directly measures individual cell widths/heights.
    gap_cs = _cell_size_from_gaps(bright)
    if gap_cs is not None and gap_cs >= 4:
        return gap_cs

    # 2. Blob-based fallback.
    num, _, stats, _ = cv2.connectedComponentsWithStats(bright * 255, connectivity=8)
    if num <= 1:
        return None

    areas = [stats[i, cv2.CC_STAT_AREA] for i in range(1, num)
             if stats[i, cv2.CC_STAT_AREA] > 8]
    if not areas:
        return None

    if len(areas) >= 2:
        # Use the smallest blob as the single-cell reference.
        # If the smallest is < 1/4 of the next it's likely noise — skip it.
        areas.sort()
        base = areas[1] if areas[0] < areas[1] / 4 else areas[0]
        return base ** 0.5
    else:
        # Single blob — infer cell size from bounding box via most-square heuristic.
        blob_h = int(stats[1, cv2.CC_STAT_HEIGHT])
        blob_w = int(stats[1, cv2.CC_STAT_WIDTH])
        candidates = [
            (1,1),(1,2),(2,1),(1,3),(3,1),(2,2),
            (1,4),(4,1),(2,3),(3,2),(1,5),(5,1),(3,3),
        ]
        best_cs = float(min(blob_h, blob_w))
        best_ratio = float('inf')
        for rows, cols in candidates:
            cs_h = blob_h / rows
            cs_w = blob_w / cols
            if cs_h < 4 or cs_w < 4:
                continue
            ratio = max(cs_h, cs_w) / min(cs_h, cs_w)
            if ratio < best_ratio:
                best_ratio = ratio
                best_cs = (cs_h + cs_w) / 2
        return best_cs


def detect_piece(img: np.ndarray, box: list, scale: float) -> Optional[Piece]:
    """
    Detect a single piece shape from its calibrated screen region.
    Crops to the bounding box of bright pixels first so padding in the
    calibration box doesn't skew cell-size estimation or scanning.
    """
    px1, py1, px2, py2 = _scale_box(box, scale)
    if px2 <= px1 or py2 <= py1:
        return None

    region = img[py1:py2, px1:px2]
    h, w = region.shape[:2]
    if h < 4 or w < 4:
        return None

    # Crop to the tight bounding box of bright pixels, removing empty padding
    bright_mask = np.mean(region[:, :, :3], axis=2) > PIECE_FILL_THRESHOLD
    bright_rows = np.where(np.any(bright_mask, axis=1))[0]
    bright_cols = np.where(np.any(bright_mask, axis=0))[0]
    if len(bright_rows) == 0 or len(bright_cols) == 0:
        return None
    margin = 3
    r0 = max(0, int(bright_rows[0]) - margin)
    r1 = min(h, int(bright_rows[-1]) + margin + 1)
    c0 = max(0, int(bright_cols[0]) - margin)
    c1 = min(w, int(bright_cols[-1]) + margin + 1)
    region = region[r0:r1, c0:c1]
    h, w = region.shape[:2]
    if h < 4 or w < 4:
        return None

    cs = _estimate_cell_size(region)
    if cs is None or cs < 4:
        return None

    # Scan on the estimated grid
    filled: set = set()
    max_r = max(1, round(h / cs))
    max_c = max(1, round(w / cs))
    for r in range(max_r + 1):
        for c in range(max_c + 1):
            cy = int((r + 0.5) * cs)
            cx = int((c + 0.5) * cs)
            if cy >= h or cx >= w:
                continue
            if _sample_brightness(region, cy, cx) > PIECE_FILL_THRESHOLD:
                filled.add((r, c))

    if not filled:
        return None

    min_r = min(r for r, c in filled)
    min_c = min(c for r, c in filled)
    return sorted((r - min_r, c - min_c) for r, c in filled)


def detect_pieces(img: np.ndarray, cal: dict) -> List[Optional[Piece]]:
    """Detect all 3 pieces. Returns list of Piece or None per slot."""
    scale = cal.get("scale", 1.0)
    if "piece_row" in cal:
        return _detect_pieces_from_row(img, cal["piece_row"], scale)
    return [detect_piece(img, box, scale) for box in cal.get("pieces", [])]
