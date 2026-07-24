#!/usr/bin/env python3
"""
VideoSender — Transmisión de frames por UDP con registro dinámico.

Escucha paquetes de registro del receptor para aprender su IP.
Comprime cada frame (JPEG), construye un header de 32 bytes con
metadatos de sincronización, fragmenta si es necesario, y envía por
un socket UDP dedicado por canal.
"""

import json
import socket
import struct
import threading
import time
from typing import Optional

import cv2
import numpy as np

from config import (
    PACKET_MAGIC, HEADER_FORMAT, HEADER_SIZE, MAX_UDP_PAYLOAD,
    JPEG_QUALITY, PNG_COMPRESSION, LOSSLESS_DEPTH, LOSSLESS_IR,
    CHANNELS, CHANNEL_DEPTH, CHANNEL_IR_LEFT, CHANNEL_IR_RIGHT, CHANNEL_TELEMETRY,
    CONTROL_PORT_OFFSET, REGISTER_MAGIC, HEARTBEAT_TIMEOUT,
    UDP_PORT_BASE,
)
from steganography import FrameSteganography


class VideoSender:
    """
    Transmite frames de 4 canales RealSense por UDP.

    Escucha en un puerto de control para que el receptor se registre.
    Una vez registrado, envía los frames a la dirección del receptor.
    Cada canal tiene su propio socket UDP y puerto destino.

    Parameters
    ----------
    port_base : int
        Puerto base UDP. Los canales usan port_base + channel_id.
        El puerto de control es port_base + CONTROL_PORT_OFFSET.
    """

    def __init__(self, port_base: int = UDP_PORT_BASE) -> None:
        self.port_base = port_base
        self._stego = FrameSteganography()

        # Dirección del receptor registrado
        self._receiver_host: Optional[str] = None
        self._receiver_lock = threading.Lock()
        self._last_heartbeat: float = 0.0

        # Un socket UDP por canal (para enviar)
        self._sockets: dict[int, socket.socket] = {}
        self._locks: dict[int, threading.Lock] = {}

        for ch_id in CHANNELS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1048576)  # 1MB buffer
            self._sockets[ch_id] = sock
            self._locks[ch_id] = threading.Lock()

        # Socket para telemetría
        self._telemetry_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._telemetry_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)

        # Socket de control (escucha registros)
        self._control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        self._control_socket.settimeout(1.0)
        self._control_socket.bind(("0.0.0.0", port_base + CONTROL_PORT_OFFSET))

        # Hilo de escucha de registros
        self._running: bool = True
        self._control_thread = threading.Thread(
            target=self._control_loop,
            name="Sender-Control",
            daemon=True,
        )
        self._control_thread.start()

        # Estadísticas
        self.frames_sent: int = 0
        self.bytes_sent: int = 0

    @property
    def receiver_connected(self) -> bool:
        """True si hay un receptor registrado y activo."""
        with self._receiver_lock:
            if self._receiver_host is None:
                return False
            return (time.time() - self._last_heartbeat) < HEARTBEAT_TIMEOUT

    @property
    def receiver_host(self) -> Optional[str]:
        """IP del receptor registrado, o None si no hay conexión activa."""
        with self._receiver_lock:
            if self._receiver_host is None:
                return None
            if (time.time() - self._last_heartbeat) >= HEARTBEAT_TIMEOUT:
                return None
            return self._receiver_host

    def _control_loop(self) -> None:
        """Escucha paquetes de registro del receptor."""
        while self._running:
            try:
                data, addr = self._control_socket.recvfrom(256)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                continue

            if len(data) < 4:
                continue

            if data[:4] == REGISTER_MAGIC:
                remote_ip = addr[0]
                with self._receiver_lock:
                    was_connected = self._receiver_host is not None
                    self._receiver_host = remote_ip
                    self._last_heartbeat = time.time()

                    if not was_connected:
                        print(f"Receptor registrado: {remote_ip}")

    def send_frame(
        self,
        channel_id: int,
        frame: np.ndarray,
        frame_id: int,
        timestamp_ns: int,
    ) -> None:
        """
        Comprime y envía un frame por UDP al receptor registrado.

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
        host = self.receiver_host
        if host is None:
            return  # No hay receptor, descartar

        # Comprimir según tipo de canal
        if frame.ndim == 2:
            # Grayscale (IR) — convertir a BGR para JPEG
            frame_bgr = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        else:
            frame_bgr = frame.copy()

        # Incrustar metadatos en la fila 0 de píxeles (esteganografía binaria 2x2)
        frame_bgr = self._stego.embed(frame_bgr, frame_id, timestamp_ns, channel_id)

        use_png = (channel_id == CHANNEL_DEPTH and LOSSLESS_DEPTH) or \
                  (channel_id in (CHANNEL_IR_LEFT, CHANNEL_IR_RIGHT) and LOSSLESS_IR)

        if use_png:
            # Compresión PNG SIN PÉRDIDAS (Lossless) — Nivel 1 (ultra rápido para CPU Jetson)
            _, encoded = cv2.imencode(
                '.png', frame_bgr,
                [cv2.IMWRITE_PNG_COMPRESSION, PNG_COMPRESSION]
            )
        else:
            # Compresión JPEG balanceada para canales convencionales
            _, encoded = cv2.imencode(
                '.jpg', frame_bgr,
                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
            )
        data = encoded.tobytes()

        # Fragmentar si es necesario
        total_frags = (len(data) + MAX_UDP_PAYLOAD - 1) // MAX_UDP_PAYLOAD
        if total_frags > 255:
            return  # Frame demasiado grande, descartar

        dest = (host, self.port_base + channel_id)
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

    def send_telemetry(self, telemetry_data: dict, frame_id: int) -> None:
        """
        Envía datos de telemetría al receptor como JSON por canal CHANNEL_TELEMETRY.

        Parameters
        ----------
        telemetry_data : dict
            Diccionario con métricas de telemetría.
        frame_id : int
            Número secuencial del frame actual.
        """
        host = self.receiver_host
        if host is None:
            return

        try:
            payload = json.dumps(telemetry_data, separators=(',', ':')).encode('utf-8')
        except (TypeError, ValueError):
            return

        timestamp_ns = int(time.time() * 1e9)
        reserved = b'\x00' * 8

        header = struct.pack(
            HEADER_FORMAT,
            PACKET_MAGIC,
            frame_id & 0xFFFFFFFF,
            timestamp_ns & 0xFFFFFFFFFFFFFFFF,
            CHANNEL_TELEMETRY,
            0,    # frag_idx
            1,    # frag_total (telemetría nunca se fragmenta)
            0,    # reserved byte
            len(payload),
            reserved,
        )

        packet = header + payload
        dest = (host, self.port_base + CHANNEL_TELEMETRY)

        try:
            self._telemetry_socket.sendto(packet, dest)
        except OSError:
            pass

    def close(self) -> None:
        """Cierra todos los sockets UDP y detiene el hilo de control."""
        self._running = False

        if self._control_thread.is_alive():
            self._control_thread.join(timeout=2.0)

        for sock in self._sockets.values():
            try:
                sock.close()
            except Exception:
                pass
        self._sockets.clear()

        try:
            self._telemetry_socket.close()
        except Exception:
            pass

        try:
            self._control_socket.close()
        except Exception:
            pass
