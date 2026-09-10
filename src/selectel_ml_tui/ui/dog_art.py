"""Кадры анимации индикатора-собачки (авто-сгенерировано, не редактировать).

Источник: 236205.gif; квантование в палитру, фон прозрачный (индекс 0).
Кадр хранится как 64x42 индексов палитры (по строке).
"""

from __future__ import annotations

import base64
import zlib

WIDTH = 64
PX_HEIGHT = 42
FRAME_COUNT = 12
FRAME_MS = 40

# Индекс 0 — прозрачный фон; остальные — RGB кадров GIF.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (0,0,0), (255,255,255), (255,243,255), (255,255,238), (255,255,227), (255,255,221),
    (255,255,207), (255,250,188), (250,255,245), (250,255,226), (249,251,237),
    (246,248,245), (250,251,216), (248,248,214), (244,244,216), (246,242,193),
    (239,249,234), (238,241,219), (236,237,211), (237,236,201), (231,239,224),
    (183,246,251), (238,228,215), (246,219,178), (253,205,185), (253,202,176),
    (250,197,180), (249,195,173), (240,190,172), (237,185,168), (224,229,216),
    (222,221,200), (220,206,188), (221,184,175), (204,207,201), (198,189,183),
    (185,187,181), (164,194,224), (213,166,158), (189,157,150), (163,168,178),
    (155,155,159), (183,136,134), (142,136,134), (231,93,136), (159,104,113),
    (127,137,174), (122,115,122), (98,125,184), (103,106,127), (104,98,108),
    (98,89,96), (83,92,132), (81,82,104), (233,74,126), (205,57,101), (145,65,86),
    (145,41,56), (138,8,35), (130,6,27), (124,7,27), (123,0,17), (85,73,86),
    (74,70,87), (69,71,98), (68,62,77), (82,50,69), (85,28,47), (111,6,22), (62,68,99),
    (61,61,85), (59,57,79), (61,57,72), (57,53,72), (58,52,68), (57,51,66), (58,50,65),
    (56,50,65), (55,50,66), (55,49,65), (55,49,64), (57,48,64), (55,48,64), (58,44,60),
    (54,51,69), (54,49,67), (54,49,65), (53,49,65), (54,49,64), (54,48,65), (54,48,64),
    (53,48,65), (53,48,64), (54,48,63), (53,48,63), (54,47,64), (53,47,64), (54,47,63),
    (53,47,63), (53,47,62), (53,46,62), (53,45,60), (48,51,75), (51,49,65), (52,48,64),
    (52,47,64), (50,48,64), (52,48,63), (52,47,63), (52,46,63), (51,47,63), (49,47,63),
    (52,47,62), (52,46,61), (51,46,62), (48,46,61), (51,45,62), (51,45,59), (46,44,61),
    (49,43,59), (47,42,59), (44,42,59), (41,37,70), (47,40,55), (42,38,55), (41,36,54),
    (39,33,52), (28,23,41),
)

_DATA_B64 = (
    "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"
    "PwncIAw="
)


def decode_frames() -> list[bytes]:
    """Вернуть список кадров: каждый — 64*42 байт индексов палитры."""
    raw = zlib.decompress(base64.b64decode(_DATA_B64))
    size = WIDTH * PX_HEIGHT
    return [raw[i * size:(i + 1) * size] for i in range(FRAME_COUNT)]
