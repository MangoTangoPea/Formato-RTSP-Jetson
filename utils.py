#!/usr/bin/env python3
"""
Utilidades compartidas entre emisor y receptor.
"""

import socket
import datetime


def obtener_ip_local() -> str:
    """
    Obtiene la IP local de la máquina en la red LAN.

    Returns
    -------
    str
        Dirección IP local o '127.0.0.1' si falla.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


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


def verificar_puerto_disponible(puerto: int) -> bool:
    """
    Verifica si un puerto UDP está disponible.

    Parameters
    ----------
    puerto : int
        Número de puerto a verificar.

    Returns
    -------
    bool
        True si el puerto está libre.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("0.0.0.0", puerto))
        s.close()
        return True
    except OSError:
        return False


# Re-exportación de funciones de esteganografía desde el módulo independiente
from steganography import incrustar_metadatos_frame, extraer_metadatos_frame


import numpy as np

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