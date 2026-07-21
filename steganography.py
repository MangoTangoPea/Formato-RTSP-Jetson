#!/usr/bin/env python3
"""
Módulo de Esteganografía Orientado a Objetos (Fila 0).

Clase FrameSteganography para la incrustación y extracción de metadatos binarios
de sincronización (frame_id, timestamp_ns, channel_id) en las dos primeras filas
de una matriz de imagen (OpenCV BGR).
"""

import struct
from typing import Optional, Tuple
import numpy as np


class FrameSteganography:
    """
    Gestor de esteganografía binaria en píxeles para metadatos de sincronización de frames.

    Incrusta y extrae metadatos en bloques de píxeles (por defecto 2x2) en la esquina
    superior izquierda de cada imagen.

    Parameters
    ----------
    block_size : int, opcional
        Tamaño en píxeles de cada bloque binario (por defecto 2).
    magic : bytes, opcional
        Firma binaria de validación de 2 bytes (por defecto b'RS').
    """

    DEFAULT_MAGIC: bytes = b'RS'
    HEADER_FORMAT: str = '>2sIQBB'
    HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 16 bytes

    def __init__(self, block_size: int = 2, magic: bytes = DEFAULT_MAGIC) -> None:
        self.block_size = block_size
        self.magic = magic

    def embed(
        self,
        frame: np.ndarray,
        frame_id: int,
        timestamp_ns: int,
        channel_id: int,
    ) -> np.ndarray:
        """
        Incrusta metadatos (frame_id, timestamp_ns, channel_id) en la imagen.

        Parameters
        ----------
        frame : np.ndarray
            Imagen BGR (HxWx3) o escala de grises.
        frame_id : int
            Número secuencial de frame.
        timestamp_ns : int
            Timestamp en nanosegundos.
        channel_id : int
            ID del canal.

        Returns
        -------
        np.ndarray
            Imagen modificada con metadatos incrustados.
        """
        bs = self.block_size
        required_width = 128 * bs
        if frame is None or frame.shape[1] < required_width or frame.shape[0] < bs:
            return frame

        # 1. Empaquetar 15 bytes de metadatos + 1 byte de checksum
        raw = struct.pack('>2sIQB', self.magic, frame_id, timestamp_ns, channel_id)
        checksum = sum(raw) & 0xFF
        payload = raw + bytes([checksum])  # 16 bytes = 128 bits

        # 2. Convertir payload a vector de 128 bits (0 o 1)
        bits = np.unpackbits(np.frombuffer(payload, dtype=np.uint8))

        # 3. Dibujar bloques de bs x bs píxeles (255 para 1, 0 para 0)
        for i, bit in enumerate(bits):
            val = 255 if bit else 0
            x_start = i * bs
            frame[0:bs, x_start:x_start + bs] = val

        return frame

    def extract(self, frame: np.ndarray) -> Optional[Tuple[int, int, int]]:
        """
        Extrae metadatos (frame_id, timestamp_ns, channel_id) desde la imagen.

        Parameters
        ----------
        frame : np.ndarray
            Imagen BGR o escala de grises.

        Returns
        -------
        tuple[int, int, int] | None
            (frame_id, timestamp_ns, channel_id) o None si falla la firma o el checksum.
        """
        bs = self.block_size
        required_width = 128 * bs
        if frame is None or frame.shape[1] < required_width or frame.shape[0] < bs:
            return None

        bits = []
        for i in range(128):
            x_start = i * bs
            block = frame[0:bs, x_start:x_start + bs]
            avg_val = np.mean(block)
            bits.append(1 if avg_val > 127 else 0)

        bits_arr = np.array(bits, dtype=np.uint8)
        payload = np.packbits(bits_arr).tobytes()

        if len(payload) < self.HEADER_SIZE:
            return None

        try:
            magic, frame_id, timestamp_ns, channel_id, checksum = struct.unpack(
                self.HEADER_FORMAT, payload[:self.HEADER_SIZE]
            )
            if magic != self.magic:
                return None
            calc_check = sum(payload[:self.HEADER_SIZE - 1]) & 0xFF
            if checksum != calc_check:
                return None
            return (frame_id, timestamp_ns, channel_id)
        except struct.error:
            return None

    # Métodos estáticos de conveniencia
    @classmethod
    def embed_metadata(
        cls,
        frame: np.ndarray,
        frame_id: int,
        timestamp_ns: int,
        channel_id: int,
    ) -> np.ndarray:
        """Incrusta metadatos usando la configuración por defecto de la clase."""
        instance = cls()
        return instance.embed(frame, frame_id, timestamp_ns, channel_id)

    @classmethod
    def extract_metadata(cls, frame: np.ndarray) -> Optional[Tuple[int, int, int]]:
        """Extrae metadatos usando la configuración por defecto de la clase."""
        instance = cls()
        return instance.extract(frame)


# Funciones de envoltura para mantener compatibilidad directa
def incrustar_metadatos_frame(
    frame: np.ndarray,
    frame_id: int,
    timestamp_ns: int,
    channel_id: int,
) -> np.ndarray:
    return FrameSteganography.embed_metadata(frame, frame_id, timestamp_ns, channel_id)


def extraer_metadatos_frame(frame: np.ndarray) -> Optional[Tuple[int, int, int]]:
    return FrameSteganography.extract_metadata(frame)
