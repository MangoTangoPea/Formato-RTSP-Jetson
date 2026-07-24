#!/usr/bin/env python3
"""
Utilidades compartidas entre emisor y receptor.

Las operaciones de empaquetado/desempaquetado de profundidad
delegan en gpu_accel.GPU, que gestiona el fallback GPU/CPU
automáticamente. Importar get_gpu_backend() para consultar el
backend activo en el arranque del servidor o cliente.
"""

import datetime
import numpy as np
from typing import Literal

# Importación diferida para evitar ciclos en módulos que importan utils
# antes de que gpu_accel esté listo (p. ej. steganography.py).
# gpu_accel importa solo numpy y cv2, sin dependencias cíclicas.
from gpu_accel import GPU


def get_gpu_backend() -> Literal["cupy", "numpy"]:
    """
    Retorna el backend numérico activo.

    Returns
    -------
    str
        'cupy'  → Operaciones numéricas en GPU (Jetson / PC con CuPy).
        'numpy' → Operaciones numéricas en CPU.
    """
    return "cupy" if GPU.cupy_available else "numpy"


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
    Empaqueta una matriz de profundidad uint16 (Z16) en imagen BGR sin pérdidas.

    Canal B: Byte bajo (bits 0-7)
    Canal G: Byte alto (bits 8-15)
    Canal R: 0

    Delega en gpu_accel.GPU (CuPy/GPU si disponible, NumPy/CPU si no).

    Parameters
    ----------
    depth_z16 : np.ndarray
        Matriz uint16 de profundidad (H x W) en milímetros.

    Returns
    -------
    np.ndarray
        Imagen BGR uint8 (H x W x 3) con profundidad empaquetada.
    """
    return GPU.pack_z16_to_bgr(depth_z16)


def unpack_bgr_to_z16(bgr_packed: np.ndarray) -> np.ndarray:
    """
    Desempaqueta una imagen BGR a la matriz original uint16 de profundidad (Z16 en mm).

    Delega en gpu_accel.GPU (CuPy/GPU si disponible, NumPy/CPU si no).

    Parameters
    ----------
    bgr_packed : np.ndarray
        Imagen BGR uint8 (H x W x 3) con profundidad empaquetada.

    Returns
    -------
    np.ndarray
        Matriz uint16 de profundidad (H x W) en milímetros.
    """
    return GPU.unpack_bgr_to_z16(bgr_packed)