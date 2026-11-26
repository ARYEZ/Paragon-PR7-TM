"""Terminal colours in the family's hues (no Qt). Programs ask for the 16 standard colours, the 256-colour palette or
exact RGB; the family has no green, blue, cyan, purple or yellow, so each is moved to a family colour that keeps its
role readable (the mock-up's mapping):

    green  -> pearl      (git's "added", ok / success, a running service)
    yellow -> orange     (warnings, modified)
    blue   -> pink       (directories, links)
    purple -> the family red-pink
    cyan   -> peach      (ls's executables, headings)

Exact colours keep their lightness: `family(r, g, b)` keeps reds, pinks and oranges as they are, makes greys and
near-greys stay greys, and turns other hues into the nearest family hue (greens and cyans towards pearl / peach)."""

from __future__ import annotations

import colorsys

# the 16 standard colours (normal 0-7, bright 8-15), as pyte names them
NAMES = ["black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
         "brightblack", "brightred", "brightgreen", "brightbrown", "brightblue", "brightmagenta", "brightcyan",
         "brightwhite"]
PALETTE = {
    "black": "#1C1A1E", "red": "#F4353A", "green": "#E6DCD2", "brown": "#FF7A1A", "blue": "#F06292",
    "magenta": "#DE0639", "cyan": "#F4B49A", "white": "#D8D4D6",
    "brightblack": "#77727A", "brightred": "#FF6B6B", "brightgreen": "#F6EFE8", "brightbrown": "#FFA25A",
    "brightblue": "#F78FB3", "brightmagenta": "#F0426A", "brightcyan": "#FFD2BE", "brightwhite": "#FFFFFF",
}
# the screen itself: dark in both finishes (like keys and menus), as a terminal is
FOREGROUND, BACKGROUND, CURSOR, SELECTION = "#E4DFE2", "#0B090C", "#FF7A1A", "#5A1A22"

ALLOWED_LOW, ALLOWED_HIGH = 42.0, 318.0          # hues 318 -> 360 -> 0 -> 42 are the family's


def family(r: int, g: int, b: int) -> tuple[int, int, int]:
    """An exact colour moved into the family's hues, lightness kept."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    deg = h * 360
    if s < 0.12 or l < 0.06 or l > 0.97:          # greys, near-black, near-white: as they are
        return r, g, b
    if deg <= ALLOWED_LOW or deg >= ALLOWED_HIGH:  # reds, pinks, oranges: the family's own
        return r, g, b
    if deg < 75:                                  # yellow -> orange
        nh, ns = 28 / 360, s
    elif deg < 165:                               # green -> pearl (a warm near-grey, as light)
        nh, ns = 28 / 360, min(s, 0.18)
    elif deg < 200:                               # cyan -> peach
        nh, ns = 18 / 360, min(s, 0.75)
    elif deg < 270:                               # blue -> pink
        nh, ns = 335 / 360, s
    else:                                         # purple -> the red-pink
        nh, ns = 342 / 360, s
    rr, gg, bb = colorsys.hls_to_rgb(nh, l, ns)
    return round(rr * 255), round(gg * 255), round(bb * 255)


def hexrgb(text: str) -> tuple[int, int, int]:
    text = text.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def resolve(colour: str, default: str) -> str:
    """pyte's colour (a name, "default", or six hex digits for 256-colour / RGB) -> "#rrggbb" in the family."""
    if not colour or colour == "default":
        return default
    if colour in PALETTE:
        return PALETTE[colour]
    if len(colour) == 6:
        try:
            r, g, b = hexrgb(colour)
        except ValueError:
            return default
        # pyte gives the 256-colour palette's first 16 as their xterm RGB: bring those back to the family's 16
        idx = XTERM16.get(colour.lower())
        if idx is not None:
            return PALETTE[NAMES[idx]]
        return "#%02X%02X%02X" % family(r, g, b)
    return default


# xterm's RGB for the 16 standard colours (how pyte reports colours 0-15 of a 256-colour request)
XTERM16 = {c: i for i, c in enumerate(["000000", "cd0000", "00cd00", "cdcd00", "0000ee", "cd00cd", "00cdcd", "e5e5e5",
                                       "7f7f7f", "ff0000", "00ff00", "ffff00", "5c5cff", "ff00ff", "00ffff",
                                       "ffffff"])}
