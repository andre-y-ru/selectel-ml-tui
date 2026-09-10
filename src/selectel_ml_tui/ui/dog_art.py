"""Кадры анимации индикатора-собачки (авто-сгенерировано, не редактировать).

Источник: 236205.gif; квантование в палитру, фон прозрачный (индекс 0).
Кадр хранится как 32x22 индексов палитры (по строке).
"""

from __future__ import annotations

import base64
import zlib

WIDTH = 32
PX_HEIGHT = 22
FRAME_COUNT = 12
FRAME_MS = 40

# Индекс 0 — прозрачный фон; остальные — RGB кадров GIF.
PALETTE: tuple[tuple[int, int, int], ...] = (
    (0,0,0), (255,255,255), (255,253,255), (255,255,249), (255,255,237), (255,250,241),
    (255,255,227), (255,255,205), (251,254,245), (250,252,222), (245,253,237),
    (161,253,251), (248,243,233), (247,241,202), (238,240,213), (224,235,231),
    (254,218,208), (253,213,181), (227,225,205), (215,222,212), (216,215,204),
    (253,204,185), (248,196,180), (225,199,179), (207,202,184), (236,183,173),
    (213,181,176), (216,169,159), (213,153,148), (195,218,240), (196,198,188),
    (191,193,179), (186,184,180), (192,170,157), (175,187,192), (171,169,157),
    (158,172,207), (102,188,250), (190,155,145), (156,155,159), (183,137,135),
    (161,135,133), (142,146,165), (137,132,135), (121,138,193), (121,126,151),
    (227,104,135), (187,107,111), (223,77,125), (134,118,124), (165,84,91),
    (111,116,159), (119,118,123), (117,114,115), (105,105,126), (106,102,104),
    (106,91,101), (91,107,177), (88,94,138), (93,92,107), (84,83,114), (87,82,88),
    (83,75,91), (75,76,104), (76,70,84), (68,68,94), (69,65,77), (176,44,87),
    (135,20,39), (109,27,51), (109,0,13), (69,59,76), (64,59,78), (62,58,79),
    (73,43,62), (86,14,32), (59,57,81), (58,54,74), (56,53,74), (59,54,69), (57,53,68),
    (57,52,69), (58,51,66), (57,51,67), (56,51,68), (56,50,66), (57,45,61),
    (48,59,108), (51,52,69), (53,51,68), (53,50,71), (53,50,65), (55,49,65),
    (55,49,64), (50,49,65), (54,48,64), (54,48,63), (53,48,64), (53,48,63), (51,48,65),
    (54,47,63), (53,47,65), (53,47,63), (53,47,62), (52,47,65), (52,47,63), (52,47,62),
    (48,47,64), (53,46,62), (52,46,62), (51,46,62), (51,45,61), (50,45,61), (51,43,60),
    (48,44,63), (47,43,60), (47,43,59), (46,42,58), (44,40,63), (44,39,57), (44,38,56),
    (28,24,119), (41,36,54), (41,34,53), (42,32,51), (38,31,51), (36,31,50),
    (33,26,47),
)

_DATA_B64 = (
    "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"
    "Sw0="
)


def decode_frames() -> list[bytes]:
    """Вернуть список кадров: каждый — 32*22 байт индексов палитры."""
    raw = zlib.decompress(base64.b64decode(_DATA_B64))
    size = WIDTH * PX_HEIGHT
    return [raw[i * size:(i + 1) * size] for i in range(FRAME_COUNT)]
