"""Text banner for terminal screens: the product mark and the product name in block letters.

The name is drawn from `PRODUCT_NAME` at run time, so a rename needs no new art.
"""

from __future__ import annotations

# The top bar's zigzag mark (frontend TopBar.tsx, favicon.svg), three rows high.
MARK = (
    "   /\\      ",
    "  /  \\  /\\ ",
    " /    \\/  \\",
)

# A three-row box-drawing alphabet. Letters not listed are drawn as themselves.
_FONT: dict[str, tuple[str, str, str]] = {
    "A": ("┌─┐", "├─┤", "┴ ┴"),
    "B": ("┌┐ ", "├┴┐", "└─┘"),
    "C": ("┌─┐", "│  ", "└─┘"),
    "D": ("┌┬┐", " ││", "─┴┘"),
    "E": ("┌─┐", "├┤ ", "└─┘"),
    "F": ("┌─┐", "├┤ ", "└  "),
    "G": ("┌─┐", "│ ┬", "└─┘"),
    "H": ("┬ ┬", "├─┤", "┴ ┴"),
    "I": ("┬", "│", "┴"),
    "J": (" ┬", " │", "└┘"),
    "K": ("┬┌─", "├┴┐", "┴ ┴"),
    "L": ("┬  ", "│  ", "┴─┘"),
    "M": ("┌┬┐", "│││", "┴ ┴"),
    "N": ("┌┐┌", "│││", "┘└┘"),
    "O": ("┌─┐", "│ │", "└─┘"),
    "P": ("┌─┐", "├─┘", "┴  "),
    "Q": ("┌─┐ ", "│─┼┐", "└─┘└"),
    "R": ("┬─┐", "├┬┘", "┴└─"),
    "S": ("┌─┐", "└─┐", "└─┘"),
    "T": ("┌┬┐", " │ ", " ┴ "),
    "U": ("┬ ┬", "│ │", "└─┘"),
    "V": ("┬  ┬", "└┐┌┘", " └┘ "),
    "W": ("┬ ┬", "│││", "└┴┘"),
    "X": ("─┐ ┬", "┌┴┬┘", "┴ └─"),
    "Y": ("┬ ┬", "└┬┘", " ┴ "),
    "Z": ("┌─┐", "┌─┘", "└─┘"),
    " ": ("  ", "  ", "  "),
    "-": ("   ", "───", "   "),
}


def wordmark(name: str) -> tuple[str, str, str]:
    """`name` in block letters, three rows of equal width."""
    rows = ["", "", ""]
    for i, ch in enumerate(name.upper()):
        glyph = _FONT.get(ch, (" ", ch, " "))
        for r in range(3):
            rows[r] += ("" if i == 0 else " ") + glyph[r]
    return rows[0], rows[1], rows[2]


def banner(name: str) -> list[tuple[str, str]]:
    """Rows of (mark, wordmark) for a caller that colors the two parts separately."""
    return list(zip(MARK, wordmark(name), strict=True))
