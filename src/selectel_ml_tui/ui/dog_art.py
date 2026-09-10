"""Кадры анимации индикатора-собачки (авто-сгенерировано, не редактировать).

Источник: 236205.gif; квантование в палитру, фон прозрачный (индекс 0).
Кадр хранится как 48x32 индексов палитры (по строке).
"""

from __future__ import annotations

import base64
import zlib

WIDTH = 48
PX_HEIGHT = 32
FRAME_COUNT = 12
FRAME_MS = 40

# Индекс 0 — прозрачный фон; остальные — RGB кадров GIF.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (0,0,0), (30,24,46), (38,32,52), (40,33,52),
    (40,34,53), (40,36,54), (120,0,12), (42,36,55),
    (44,36,55), (44,39,56), (127,0,14), (43,41,60),
    (47,41,58), (47,43,60), (50,43,59), (50,44,60),
    (53,43,59), (85,26,45), (47,46,63), (51,45,60),
    (50,45,61), (51,46,62), (52,46,61), (50,47,63),
    (51,46,63), (52,46,62), (53,46,62), (52,47,62),
    (53,47,62), (49,48,65), (52,47,63), (53,47,63),
    (48,49,66), (52,47,64), (53,48,63), (54,47,63),
    (53,47,64), (52,48,64), (55,47,63), (53,48,64),
    (54,48,64), (53,48,65), (45,51,70), (54,49,64),
    (54,48,65), (55,49,64), (54,49,65), (55,49,65),
    (56,49,65), (55,50,66), (56,50,66), (56,51,67),
    (54,51,69), (66,46,64), (50,52,75), (56,52,70),
    (128,17,35), (113,25,47), (58,55,74), (59,55,74),
    (56,56,77), (64,56,73), (56,61,91), (70,64,77),
    (60,62,89), (62,63,87), (137,31,49), (73,69,82),
    (61,69,101), (70,74,98), (92,76,90), (76,80,102),
    (93,86,95), (98,94,103), (149,67,88), (178,50,78),
    (105,103,108), (143,95,102), (113,111,118), (119,120,126),
    (143,117,118), (137,128,127), (138,138,134), (226,69,121),
    (174,132,129), (150,142,143), (226,88,128), (152,150,150),
    (199,135,136), (159,159,153), (176,158,158), (181,171,160),
    (202,162,150), (183,182,169), (211,174,164), (196,194,177),
    (228,181,167), (231,191,171), (201,205,188), (222,201,176),
    (246,192,173), (215,214,194), (250,197,176), (204,214,211),
    (254,200,178), (254,204,182), (220,224,201), (249,212,186),
    (232,229,188), (238,222,189), (230,230,208), (214,226,232),
    (233,234,206), (238,237,203), (228,234,220), (230,237,219),
    (242,243,206), (240,241,220), (253,252,200), (229,242,238),
    (243,246,227), (243,251,223), (251,252,216), (253,253,223),
    (255,255,229), (245,251,245), (251,253,242), (255,255,239),
)

_DATA_B64 = (
    "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"
    "sab/AIrxKUs="
)


def decode_frames() -> list[bytes]:
    """Вернуть список кадров: каждый — 48*32 байт индексов палитры."""
    raw = zlib.decompress(base64.b64decode(_DATA_B64))
    size = WIDTH * PX_HEIGHT
    return [raw[i * size:(i + 1) * size] for i in range(FRAME_COUNT)]
