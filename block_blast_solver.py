import itertools
from typing import List, Tuple, Optional, NamedTuple

Board = List[List[int]]
Piece = List[Tuple[int, int]]


class Move(NamedTuple):
    piece_idx: int
    row: int
    col: int
    lines_cleared: int
    score_delta: int
    streak_event: str
    placements_since_after: int
    streak_after: int


def copy_board(board: Board) -> Board:
    return [row[:] for row in board]


def normalize_piece(piece: Piece) -> Piece:
    if not piece:
        return piece
    min_r = min(dr for dr, dc in piece)
    min_c = min(dc for dr, dc in piece)
    return [(dr - min_r, dc - min_c) for dr, dc in piece]


def can_place(board: Board, piece: Piece, row: int, col: int) -> bool:
    for dr, dc in piece:
        r, c = row + dr, col + dc
        if not (0 <= r < 8 and 0 <= c < 8):
            return False
        if board[r][c] == 1:
            return False
    return True


def place_piece(board: Board, piece: Piece, row: int, col: int) -> Board:
    new_board = copy_board(board)
    for dr, dc in piece:
        new_board[row + dr][col + dc] = 1
    return new_board


def clear_lines(board: Board) -> Tuple[Board, int, int]:
    rows_to_clear = [r for r in range(8) if all(board[r][c] == 1 for c in range(8))]
    cols_to_clear = [c for c in range(8) if all(board[r][c] == 1 for r in range(8))]
    lines_cleared = len(rows_to_clear) + len(cols_to_clear)
    if lines_cleared == 0:
        return board, 0, 0
    cleared: set = set()
    for r in rows_to_clear:
        for c in range(8):
            cleared.add((r, c))
    for c in cols_to_clear:
        for r in range(8):
            cleared.add((r, c))
    new_board = copy_board(board)
    for r, c in cleared:
        new_board[r][c] = 0
    return new_board, lines_cleared, len(cleared)


def board_heuristic(board: Board) -> float:
    """
    Board quality score — signals based on what actually kills Block Blast games:

    1. Line progress — reward lines close to clearing, penalise sparse partials.
    2. Isolated filled cells — floating single blocks create unworkable gaps.
    3. Trapped empty cells — 3+ filled/wall neighbors: permanently dead space.
    4. Small empty pockets — connected empty regions too small for real pieces.
    5. Bumpiness — jagged fill variance across adjacent rows/cols fragments the board.
    6. Combo intersections — near-full row ∩ near-full col = high-value clearing alignment.
    7. Density / survival — above 60% approaching game-over territory.

    Vectorized with numpy for speed — called thousands of times per solve().
    """
    # sum(row) is C-level fast; sum(generator) is not — zip(*board) transposes cheaply
    row_fills = [sum(row) for row in board]
    col_fills = [sum(col) for col in zip(*board)]
    total     = sum(row_fills)
    density   = total / 64.0

    # --- line progress ---
    score = 0.0
    for f in row_fills + col_fills:
        if f == 0:
            pass
        elif f <= 2:
            score -= 10
        elif f <= 4:
            score -= 3
        elif f == 5:
            score += 8
        elif f == 6:
            score += 20
        elif f == 7:
            score += 45

    # --- isolated filled cells + trapped empty cells (single pass, no generator) ---
    for r in range(8):
        br  = board[r]
        brp = board[r - 1] if r > 0 else None
        brn = board[r + 1] if r < 7 else None
        for c in range(8):
            cell = br[c]
            up    = brp[c] if brp is not None else 0
            down  = brn[c] if brn is not None else 0
            left  = br[c - 1] if c > 0 else 0
            right = br[c + 1] if c < 7 else 0
            if cell == 1:
                if not (up or down or left or right):
                    score -= 15     # isolated filled block
            else:
                wall_up    = 1 if brp is None else up
                wall_down  = 1 if brn is None else down
                wall_left  = 1 if c == 0 else left
                wall_right = 1 if c == 7 else right
                if wall_up + wall_down + wall_left + wall_right >= 3:
                    score -= 25     # trapped empty cell

    # --- small empty pockets (BFS with flat bytearray — avoids 2D list overhead) ---
    flat = [cell for row in board for cell in row]
    _vis = bytearray(64)
    for start in range(64):
        if flat[start] == 0 and not _vis[start]:
            size = 0
            stack = [start]
            _vis[start] = 1
            while stack:
                idx = stack.pop()
                size += 1
                r, c = idx >> 3, idx & 7   # divmod(idx, 8) without function call
                if r > 0:
                    n = idx - 8
                    if not _vis[n] and flat[n] == 0:
                        _vis[n] = 1; stack.append(n)
                if r < 7:
                    n = idx + 8
                    if not _vis[n] and flat[n] == 0:
                        _vis[n] = 1; stack.append(n)
                if c > 0:
                    n = idx - 1
                    if not _vis[n] and flat[n] == 0:
                        _vis[n] = 1; stack.append(n)
                if c < 7:
                    n = idx + 1
                    if not _vis[n] and flat[n] == 0:
                        _vis[n] = 1; stack.append(n)
            if size == 1:
                score -= 150
            elif size == 2:
                score -= 80
            elif size == 3:
                score -= 20

    # --- bumpiness (direct subtraction, no abs() call overhead in loop) ---
    rb = cb = 0
    for i in range(7):
        d = row_fills[i] - row_fills[i + 1]; rb += d if d >= 0 else -d
        d = col_fills[i] - col_fills[i + 1]; cb += d if d >= 0 else -d
    score -= (rb + cb) * 8.0

    # --- combo intersection bonus ---
    row_near = [f >= 6 for f in row_fills]
    col_near = [f >= 6 for f in col_fills]
    if any(row_near) and any(col_near):
        combo = 0
        for r in range(8):
            if row_near[r]:
                br = board[r]
                for c in range(8):
                    if col_near[c] and br[c] == 0:
                        combo += 1
        score += min(combo * 80.0, 400.0)

    # --- survival / density penalty ---
    if density > 0.60:
        score -= (density - 0.60) ** 2 * 10000
    elif density > 0.40:
        score -= (density - 0.40) ** 2 * 3000

    return score


def valid_placements(board: Board, piece: Piece) -> List[Tuple[int, int]]:
    return [
        (r, c)
        for r in range(8)
        for c in range(8)
        if can_place(board, piece, r, c)
    ]


def _quick_place_score(board: Board, piece: Piece, row: int, col: int) -> int:
    cells = len(piece)
    tmp = place_piece(board, piece, row, col)
    lc = sum(1 for r in range(8) if all(tmp[r][c] == 1 for c in range(8)))
    lc += sum(1 for c in range(8) if all(tmp[r][c] == 1 for r in range(8)))
    return cells + lc * 20


def apply_placement(
    board: Board,
    piece: Piece,
    row: int,
    col: int,
    streak: int,
    placements_since: int,
) -> Tuple[Board, float, int, int, int, str]:
    new_board = place_piece(board, piece, row, col)
    new_board, lines_cleared, cells_cleared = clear_lines(new_board)

    # Flat per-line bonus large enough to always outweigh heuristic differences.
    # Extra flat bonus for clearing multiple lines (combo) — no streak scaling.
    combo = (lines_cleared - 1) * 200 if lines_cleared > 1 else 0
    score: float = cells_cleared * 10 + lines_cleared * 500 + combo

    if lines_cleared > 0:
        if placements_since == 2 and streak > 0:
            score += 400            # saved the streak
            streak_event = "saved"
        else:
            score += 150            # extended the streak
            streak_event = "extended"
        new_streak = streak + 1
        new_placements_since = 0
    else:
        if placements_since == 2 and streak > 0:
            score -= 2000           # flat penalty — no streak scaling
            streak_event = "broken"
            new_streak = 0
            new_placements_since = 1
        else:
            streak_event = "none"
            new_streak = streak
            new_placements_since = placements_since + 1

    return new_board, score, new_streak, new_placements_since, lines_cleared, streak_event


def solve(
    board: Board,
    pieces: List[Piece],
    streak: int,
    placements_since: int,
) -> Tuple[Optional[float], Optional[List[Move]]]:
    best_score: float = float("-inf")
    best_moves: Optional[List[Move]] = None

    # Conservative upper-bound for one placement (for pruning only).
    # 5 cells × 10 + 4 lines × 500 + combo + save bonus
    _MAX_SINGLE = 5 * 10 + 4 * 500 + 3 * 200 + 400

    for perm in itertools.permutations(range(len(pieces))):
        p0, p1, p2 = pieces[perm[0]], pieces[perm[1]], pieces[perm[2]]

        pos0 = valid_placements(board, p0)
        if not pos0:
            continue
        pos0.sort(key=lambda rc: _quick_place_score(board, p0, rc[0], rc[1]), reverse=True)
        pos0 = pos0[:25]

        for r0, c0 in pos0:
            b1, s0, stk1, ps1, lc0, se0 = apply_placement(
                board, p0, r0, c0, streak, placements_since
            )

            if s0 + _MAX_SINGLE * 2 + board_heuristic(b1) < best_score:
                break

            pos1 = valid_placements(b1, p1)
            if not pos1:
                continue
            pos1.sort(key=lambda rc: _quick_place_score(b1, p1, rc[0], rc[1]), reverse=True)
            pos1 = pos1[:20]

            for r1, c1 in pos1:
                b2, s1, stk2, ps2, lc1, se1 = apply_placement(
                    b1, p1, r1, c1, stk1, ps1
                )

                if s0 + s1 + _MAX_SINGLE + board_heuristic(b2) < best_score:
                    break

                pos2 = valid_placements(b2, p2)
                if pos2:
                    pos2.sort(key=lambda rc: _quick_place_score(b2, p2, rc[0], rc[1]), reverse=True)
                    pos2 = pos2[:15]

                if not pos2:
                    # Dying is always the worst possible outcome — far worse than
                    # any streak break.  -1_000_000 guarantees surviving always wins.
                    total = s0 + s1 - 1_000_000 + board_heuristic(b2)
                    if total > best_score:
                        best_score = total
                        best_moves = [
                            Move(perm[0], r0, c0, lc0, int(s0), se0, ps1, stk1),
                            Move(perm[1], r1, c1, lc1, int(s1), se1, ps2, stk2),
                        ]
                    continue

                for r2, c2 in pos2:
                    b3, s2, stk3, ps3, lc2, se2 = apply_placement(
                        b2, p2, r2, c2, stk2, ps2
                    )

                    seq_cleared = lc0 + lc1 + lc2
                    seq_cleared_bonus = 400 if seq_cleared > 0 else 0

                    # Prefer clearing on the last move: next turn starts with
                    # ps=0 (3 free placements) instead of ps=1 (2 placements).
                    if stk3 > 0 and seq_cleared > 0:
                        if ps3 == 0:
                            seq_cleared_bonus += 300
                        elif ps3 == 1:
                            seq_cleared_bonus += 100

                    total = s0 + s1 + s2 + seq_cleared_bonus + 0.25 * board_heuristic(b3)

                    # Discourage leaving the board too empty to build lines.
                    cells_b3 = sum(b3[r][c] for r in range(8) for c in range(8))
                    if cells_b3 < 6:
                        streak_forced = (
                            (placements_since == 2 and streak > 0 and lc0 > 0) or
                            (ps1 == 2 and stk1 > 0 and lc1 > 0) or
                            (ps2 == 2 and stk2 > 0 and lc2 > 0)
                        )
                        if not streak_forced:
                            total -= (6 - cells_b3) * 200

                    if total > best_score:
                        best_score = total
                        best_moves = [
                            Move(perm[0], r0, c0, lc0, int(s0), se0, ps1, stk1),
                            Move(perm[1], r1, c1, lc1, int(s1), se1, ps2, stk2),
                            Move(perm[2], r2, c2, lc2, int(s2), se2, ps3, stk3),
                        ]

    if best_moves is None:
        return None, None

    return best_score, best_moves
