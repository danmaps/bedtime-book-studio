#!/usr/bin/env python3
"""
Zero-dependency ISO/IEC 18004 QR Code Generator (Byte mode, ECC Level L, Versions 1–6)
for generating local Wi-Fi LAN reader QR codes as SVG and terminal Unicode blocks.
"""

from __future__ import annotations

from typing import List, Tuple

# Version -> (total_codewords, ec_codewords_per_block, max_byte_capacity) for ECC Level L (1 block)
_VERSION_SPEC = {
    1: (26, 7, 17),
    2: (44, 10, 32),
    3: (70, 15, 53),
    4: (100, 20, 78),
    5: (134, 26, 106),
    6: (172, 18, 134),  # Note: V6-L uses 2 blocks of (68 data, 18 ec)
}

_ALIGNMENT_POS = {
    1: [],
    2: [6, 18],
    3: [6, 22],
    4: [6, 26],
    5: [6, 30],
    6: [6, 34],
}


def _gf_tables() -> Tuple[List[int], List[int]]:
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


_GF_EXP, _GF_LOG = _gf_tables()


def _gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _GF_EXP[_GF_LOG[a] + _GF_LOG[b]]


def _rs_generator_poly(degree: int) -> List[int]:
    g = [1]
    for i in range(degree):
        nxt = [0] * (len(g) + 1)
        factor = _GF_EXP[i]
        for j, coeff in enumerate(g):
            nxt[j] ^= coeff
            nxt[j + 1] ^= _gf_mul(coeff, factor)
        g = nxt
    return g


def _rs_encode(data: List[int], ec_len: int) -> List[int]:
    gen = _rs_generator_poly(ec_len)
    res = [0] * ec_len
    for b in data:
        factor = b ^ res[0]
        res = res[1:] + [0]
        if factor != 0:
            for i in range(ec_len):
                res[i] ^= _gf_mul(gen[i + 1], factor)
    return res


def _choose_version(byte_len: int) -> int:
    for v in range(1, 7):
        if byte_len <= _VERSION_SPEC[v][2]:
            return v
    raise ValueError(f"URL too long for compact QR (max 134 bytes, got {byte_len})")


def _encode_data_codewords(payload: bytes, version: int) -> List[int]:
    total_cw, ec_cw, _ = _VERSION_SPEC[version]
    data_capacity = total_cw - ec_cw if version < 6 else total_cw - 2 * ec_cw

    bits: List[int] = []

    def append_bits(val: int, length: int) -> None:
        for i in range(length - 1, -1, -1):
            bits.append((val >> i) & 1)

    # Byte mode indicator (0100) + 8-bit character count (versions 1..9)
    append_bits(0b0100, 4)
    append_bits(len(payload), 8)
    for b in payload:
        append_bits(b, 8)

    max_bits = data_capacity * 8
    terminator = min(4, max_bits - len(bits))
    append_bits(0, terminator)
    while len(bits) % 8 != 0:
        bits.append(0)

    codewords = [
        sum(bits[i + j] << (7 - j) for j in range(8))
        for i in range(0, len(bits), 8)
    ]
    pad_bytes = [0xEC, 0x11]
    idx = 0
    while len(codewords) < data_capacity:
        codewords.append(pad_bytes[idx % 2])
        idx += 1

    if version < 6:
        ec = _rs_encode(codewords, ec_cw)
        return codewords + ec
    else:
        # 2 blocks of 68 data codewords + 18 ec codewords each
        b1 = codewords[:68]
        b2 = codewords[68:]
        ec1 = _rs_encode(b1, ec_cw)
        ec2 = _rs_encode(b2, ec_cw)
        interleaved: List[int] = []
        for a, b in zip(b1, b2):
            interleaved.extend([a, b])
        for a, b in zip(ec1, ec2):
            interleaved.extend([a, b])
        return interleaved


def _make_base_matrix(version: int) -> Tuple[List[List[int]], List[List[bool]]]:
    size = 17 + 4 * version
    matrix = [[0] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(r: int, c: int, val: int, res: bool = True) -> None:
        if 0 <= r < size and 0 <= c < size:
            matrix[r][c] = val
            if res:
                reserved[r][c] = True

    def place_finder(row: int, col: int) -> None:
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                if 0 <= dr <= 6 and 0 <= dc <= 6:
                    on = (
                        dr in (0, 6)
                        or dc in (0, 6)
                        or (2 <= dr <= 4 and 2 <= dc <= 4)
                    )
                    set_module(row + dr, col + dc, 1 if on else 0, True)
                else:
                    set_module(row + dr, col + dc, 0, True)

    place_finder(0, 0)
    place_finder(0, size - 7)
    place_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        val = 1 if i % 2 == 0 else 0
        set_module(6, i, val, True)
        set_module(i, 6, val, True)

    # Alignment patterns
    coords = _ALIGNMENT_POS[version]
    for r in coords:
        for c in coords:
            if reserved[r][c]:
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    on = max(abs(dr), abs(dc)) in (0, 2)
                    set_module(r + dr, c + dc, 1 if on else 0, True)

    # Dark module & reserved format info areas
    set_module(4 * version + 9, 8, 1, True)
    for i in range(9):
        if i != 6:
            reserved[8][i] = True
            reserved[i][8] = True
    for i in range(8):
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True

    return matrix, reserved


def _place_format_bits(matrix: List[List[int]], mask: int) -> None:
    size = len(matrix)
    # ECC Level L = 01
    data = (0b01 << 3) | mask
    rem = data << 10
    for i in range(14, 9, -1):
        if (rem >> i) & 1:
            rem ^= 0b10100110111 << (i - 10)
    bits = ((data << 10) | rem) ^ 0b101010000010010

    def bit(i: int) -> int:
        return (bits >> i) & 1

    # Around top-left finder
    tl_coords = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
        (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    ]
    for i, (r, c) in enumerate(tl_coords):
        matrix[r][c] = bit(14 - i)

    # Bottom-left and top-right
    for i in range(7):
        matrix[size - 1 - i][8] = bit(14 - i)
    for i in range(8):
        matrix[8][size - 8 + i] = bit(7 - i)


def encode_qr_matrix(text: str) -> List[List[int]]:
    """Encode `text` into a 2D QR matrix of 0/1 ints."""
    payload = text.encode("utf-8")
    version = _choose_version(len(payload))
    codewords = _encode_data_codewords(payload, version)
    matrix, reserved = _make_base_matrix(version)
    size = len(matrix)

    bit_stream = [
        (cw >> (7 - b)) & 1
        for cw in codewords
        for b in range(8)
    ]

    bit_idx = 0
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for dc in (0, -1):
                c = col + dc
                if not reserved[r][c]:
                    val = bit_stream[bit_idx] if bit_idx < len(bit_stream) else 0
                    bit_idx += 1
                    # Apply mask 0: (r + c) % 2 == 0
                    if (r + c) % 2 == 0:
                        val ^= 1
                    matrix[r][c] = val
        col -= 2
        upward = not upward

    _place_format_bits(matrix, mask=0)
    return matrix


def render_qr_svg(text: str, border: int = 3, scale: int = 6, title: str | None = None) -> str:
    """Render a crisp, standalone SVG QR code for `text`."""
    import html as _html
    matrix = encode_qr_matrix(text)
    n = len(matrix)
    total = (n + 2 * border) * scale
    rects: List[str] = []
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            if val:
                x = (c + border) * scale
                y = (r + border) * scale
                rects.append(f'<rect x="{x}" y="{y}" width="{scale}" height="{scale}" />')
    body = "".join(rects)
    title_el = f"<title>{_html.escape(title or text)}</title>"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
        f'width="{total}" height="{total}" data-url="{_html.escape(text)}" shape-rendering="crispEdges">'
        f"{title_el}"
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<g fill="#111827">{body}</g></svg>'
    )


def render_qr_ascii(text: str, border: int = 2) -> str:
    """Render a compact Unicode half-block QR code for terminal output."""
    matrix = encode_qr_matrix(text)
    n = len(matrix)
    padded_size = n + 2 * border
    grid = [[0] * padded_size for _ in range(padded_size)]
    for r in range(n):
        for c in range(n):
            grid[r + border][c + border] = matrix[r][c]

    lines: List[str] = []
    for r in range(0, padded_size, 2):
        row_chars: List[str] = []
        for c in range(padded_size):
            top = grid[r][c]
            bot = grid[r + 1][c] if (r + 1) < padded_size else 0
            if top and bot:
                row_chars.append("█")
            elif top and not bot:
                row_chars.append("▀")
            elif not top and bot:
                row_chars.append("▄")
            else:
                row_chars.append(" ")
        lines.append("".join(row_chars))
    return "\n".join(lines)
