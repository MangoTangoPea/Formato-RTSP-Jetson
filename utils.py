#!/usr/bin/env python3
"""
Utilidades compartidas entre emisor y receptor.
"""

import datetime
import numpy as np


def formatear_timestamp_ns(timestamp_ns: int | None) -> str:
    """
    Formatea un timestamp en nanosegundos como HH:MM:SS.mmm.

    Parameters
    ----------
    timestamp_ns : int or None
        Timestamp en nanosegundos.

    Returns
    -------
    str
        Timestamp formateado o '--:--:--.---' si no es válido.
    """
    if timestamp_ns is None or timestamp_ns == 0:
        return "--:--:--.---"
    try:
        ts_sec = timestamp_ns / 1e9
        dt = datetime.datetime.fromtimestamp(ts_sec)
        ms = int((timestamp_ns % 1_000_000_000) / 1_000_000)
        return dt.strftime("%H:%M:%S") + f".{ms:03d}"
    except (OSError, ValueError, OverflowError):
        return "--:--:--.---"


def pack_z16_to_bgr(depth_z16: np.ndarray) -> np.ndarray:
    """
    Empaqueta una matriz de profundidad uint16 (Z16) de 16 bits en una imagen BGR de 3 canales sin pérdidas.

    Canal B: Byte bajo (bits 0-7)
    Canal G: Byte alto (bits 8-15)
    Canal R: 0
    """
    low_byte = (depth_z16 & 0xFF).astype(np.uint8)
    high_byte = ((depth_z16 >> 8) & 0xFF).astype(np.uint8)
    zero = np.zeros_like(low_byte)
    return np.dstack((low_byte, high_byte, zero))


def unpack_bgr_to_z16(bgr_packed: np.ndarray) -> np.ndarray:
    """
    Desempaqueta una imagen BGR reconstruyendo la matriz original uint16 (profundidad Z16 en milímetros).
    """
    low_byte = bgr_packed[:, :, 0].astype(np.uint16)
    high_byte = bgr_packed[:, :, 1].astype(np.uint16)
    return (high_byte << 8) | low_byte