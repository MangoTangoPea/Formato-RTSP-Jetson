#!/usr/bin/env python3
"""
VideoSender — Transmisión de frames por UDP.

Comprime cada frame (JPEG/PNG), construye un header de 32 bytes con
metadatos de sincronización, fragmenta si es necesario, y envía por
un socket UDP dedicado por canal.
"""

import socket
import struct
import threading
from typing import Optional

import cv2
import numpy as np

from config import (
    PACKET_MAGIC, HEADER_FORMAT, HEADER_SIZE, MAX_UDP_PAYLOAD,
    JPEG_QUALITY, CHANNELS,
)


class VideoSender:
    """
    Transmite frames de 4 canales RealSense por UDP.

    Cada canal tiene su propio socket UDP y puerto destino.
    Los frames se comprimen antes de enviar para reducir ancho de banda.

    Parameters
    ----------
    host : str
        IP del receptor destino.
    port_base : int
        Puerto base UDP. Los canales usan port_base + channel_id.
    """

    def __init__(self, host: str, port_base: int = 5000) -> None:
        self.host = host
        self.port_base = port_base

        # Un socket UDP por canal
        self._sockets: dict[int, socket.socket] = {}
        self._locks: dict[int, threading.Lock] = {}

        for ch_id in CHANNELS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)  # 1MB buffer
            self._sockets[ch_id] = sock
            self._locks[ch_id] = threading.Lock()

        # Estadísticas
        self.frames_sent: int = 0
        self.bytes_sent: int = 0

    def send_frame(
        self,
        channel_id: int,
        frame: np.ndarray,
        frame_id: int,
        timestamp_ns: int,
    ) -> None:
        """
        Comprime y envía un frame por UDP.

        Parameters
        ----------
        channel_id : int
            ID del canal (0=color, 1=depth, 2=ir_left, 3=ir_right).
        frame : np.ndarray
            Imagen BGR (HxWx3) o grayscale (HxW).
        frame_id : int
            Número secuencial del frame.
        timestamp_ns : int
            Timestamp del emisor en nanosegundos.
        """
        # Comprimir según tipo de canal
        if frame.ndim == 2:
            # Grayscale (IR) — convertir a BGR para JPEG
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            frame_bgr = frame

        _, encoded = cv2.imencode(
            '.jpg', frame_bgr,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
        )
        data = encoded.tobytes()

        # Fragmentar si es necesario
        total_frags = (len(data) + MAX_UDP_PAYLOAD - 1) // MAX_UDP_PAYLOAD
        if total_frags > 255:
            return  # Frame demasiado grande, descartar

        dest = (self.host, self.port_base + channel_id)
        reserved = b'\x00' * 8

        with self._locks[channel_id]:
            for frag_idx in range(total_frags):
                offset = frag_idx * MAX_UDP_PAYLOAD
                chunk = data[offset:offset + MAX_UDP_PAYLOAD]

                header = struct.pack(
                    HEADER_FORMAT,
                    PACKET_MAGIC,
                    frame_id & 0xFFFFFFFF,
                    timestamp_ns & 0xFFFFFFFFFFFFFFFF,
                    channel_id,
                    frag_idx,
                    total_frags,
                    0,  # reserved byte
                    len(chunk),
                    reserved,
                )

                packet = header + chunk

                try:
                    self._sockets[channel_id].sendto(packet, dest)
                    self.bytes_sent += len(packet)
                except OSError:
                    pass  # Error de red, continuar

        self.frames_sent += 1

    def close(self) -> None:
        """Cierra todos los sockets UDP."""
        for sock in self._sockets.values():
            try:
                sock.close()
            except Exception:
                pass
        self._sockets.clear()
