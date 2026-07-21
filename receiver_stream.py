#!/usr/bin/env python3
"""
VideoReceiver — Recepción de frames por UDP con registro automático.

Se registra con el emisor enviando heartbeats periódicos.
Escucha en 4 puertos UDP (uno por canal) + 1 puerto de telemetría,
ensambla fragmentos, decodifica JPEG, y mantiene el frame más
reciente de cada canal en un buffer thread-safe.
"""

import json
import socket
import struct
import time
import threading
from typing import Optional

import cv2
import numpy as np

from config import (
    PACKET_MAGIC, HEADER_FORMAT, HEADER_SIZE, MAX_UDP_PAYLOAD,
    CHANNELS, CHANNEL_TELEMETRY,
    CONTROL_PORT_OFFSET, REGISTER_MAGIC, HEARTBEAT_INTERVAL,
)


class VideoReceiver:
    """
    Recibe frames de 4 canales RealSense por UDP.

    Envía heartbeats al emisor para registrarse. Cada canal tiene
    un hilo de recepción dedicado. Los frames se decodifican y
    almacenan en un buffer thread-safe.

    Parameters
    ----------
    sender_ip : str
        IP del emisor al que conectarse.
    port_base : int
        Puerto base UDP. Los canales escuchan en port_base + channel_id.
    """

    # Timeout para descartar frames incompletos (segundos)
    _FRAGMENT_TIMEOUT: float = 0.15

    def __init__(self, sender_ip: str, port_base: int = 5000) -> None:
        self.sender_ip = sender_ip
        self.port_base = port_base
        self._running: bool = False

        # Estado por canal
        self._frames: dict[int, Optional[np.ndarray]] = {ch: None for ch in CHANNELS}
        self._frame_ids: dict[int, Optional[int]] = {ch: None for ch in CHANNELS}
        self._timestamps: dict[int, Optional[int]] = {ch: None for ch in CHANNELS}
        self._locks: dict[int, threading.Lock] = {ch: threading.Lock() for ch in CHANNELS}

        # Estadísticas por canal
        self._frames_received: dict[int, int] = {ch: 0 for ch in CHANNELS}
        self._frames_lost: dict[int, int] = {ch: 0 for ch in CHANNELS}
        self._fps: dict[int, float] = {ch: 0.0 for ch in CHANNELS}
        self._fps_counters: dict[int, int] = {ch: 0 for ch in CHANNELS}
        self._fps_timers: dict[int, float] = {ch: time.time() for ch in CHANNELS}
        self._last_frame_id: dict[int, int] = {ch: 0 for ch in CHANNELS}

        # Telemetría del emisor
        self._telemetry: dict = {}
        self._telemetry_lock = threading.Lock()

        # Sockets y hilos
        self._sockets: dict[int, socket.socket] = {}
        self._threads: dict[str, threading.Thread] = {}

        # Socket para heartbeat
        self._heartbeat_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def start(self) -> None:
        """Inicia la recepción en los 4 canales + telemetría + heartbeat."""
        self._running = True

        # Hilos de recepción de canales de video
        for ch_id in CHANNELS:
            port = self.port_base + ch_id

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4194304)  # 4MB buffer por canal 720p HD
            sock.settimeout(1.0)
            sock.bind(("0.0.0.0", port))
            self._sockets[ch_id] = sock

            thread = threading.Thread(
                target=self._receive_loop,
                args=(ch_id,),
                name=f"Receiver-{CHANNELS[ch_id]}",
                daemon=True,
            )
            self._threads[f"video_{ch_id}"] = thread
            thread.start()

        # Hilo de recepción de telemetría
        telemetry_port = self.port_base + CHANNEL_TELEMETRY
        telemetry_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        telemetry_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        telemetry_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        telemetry_sock.settimeout(1.0)
        telemetry_sock.bind(("0.0.0.0", telemetry_port))
        self._sockets[CHANNEL_TELEMETRY] = telemetry_sock

        telemetry_thread = threading.Thread(
            target=self._telemetry_loop,
            name="Receiver-Telemetry",
            daemon=True,
        )
        self._threads["telemetry"] = telemetry_thread
        telemetry_thread.start()

        # Hilo de heartbeat (registro periódico)
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="Receiver-Heartbeat",
            daemon=True,
        )
        self._threads["heartbeat"] = heartbeat_thread
        heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        """Envía paquetes de registro al emisor periódicamente."""
        control_port = self.port_base + CONTROL_PORT_OFFSET
        dest = (self.sender_ip, control_port)

        while self._running:
            try:
                self._heartbeat_socket.sendto(REGISTER_MAGIC, dest)
            except OSError:
                pass

            # Dormir en intervalos cortos para responder rápido al cierre
            elapsed = 0.0
            while self._running and elapsed < HEARTBEAT_INTERVAL:
                time.sleep(0.2)
                elapsed += 0.2

    def _telemetry_loop(self) -> None:
        """Recibe paquetes de telemetría del emisor."""
        sock = self._sockets[CHANNEL_TELEMETRY]

        while self._running:
            try:
                packet, _ = sock.recvfrom(HEADER_SIZE + 8192)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                continue

            if len(packet) < HEADER_SIZE:
                continue

            try:
                (magic, _, _, ch_id, _, _, _, data_len, _) = struct.unpack(
                    HEADER_FORMAT, packet[:HEADER_SIZE]
                )
            except struct.error:
                continue

            if magic != PACKET_MAGIC or ch_id != CHANNEL_TELEMETRY:
                continue

            payload = packet[HEADER_SIZE:HEADER_SIZE + data_len]

            try:
                telemetry = json.loads(payload.decode('utf-8'))
                with self._telemetry_lock:
                    self._telemetry = telemetry
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

    def _receive_loop(self, channel_id: int) -> None:
        """
        Bucle de recepción para un canal.

        Recibe paquetes UDP, ensambla fragmentos y decodifica frames.
        """
        sock = self._sockets[channel_id]

        # Buffer de ensamblaje: {frame_id: {frag_idx: data, ...}}
        assembly: dict[int, dict[int, bytes]] = {}
        assembly_meta: dict[int, tuple[int, int, float]] = {}  # frame_id: (total_frags, ts_ns, t_recv)

        while self._running:
            try:
                packet, _ = sock.recvfrom(HEADER_SIZE + MAX_UDP_PAYLOAD + 1024)
            except socket.timeout:
                continue
            except OSError:
                if not self._running:
                    break
                continue

            if len(packet) < HEADER_SIZE:
                continue

            # Parsear header
            try:
                (magic, frame_id, timestamp_ns, ch_id, frag_idx,
                 frag_total, _, data_len, _) = struct.unpack(
                    HEADER_FORMAT, packet[:HEADER_SIZE]
                )
            except struct.error:
                continue

            if magic != PACKET_MAGIC:
                continue

            if ch_id != channel_id:
                continue

            payload = packet[HEADER_SIZE:HEADER_SIZE + data_len]

            # Inicializar buffer para este frame_id si no existe
            if frame_id not in assembly:
                assembly[frame_id] = {}
                assembly_meta[frame_id] = (frag_total, timestamp_ns, time.time())

            assembly[frame_id][frag_idx] = payload

            # Verificar si el frame está completo
            expected_total = assembly_meta[frame_id][0]
            if len(assembly[frame_id]) >= expected_total:
                # Ensamblar datos completos
                full_data = b''.join(
                    assembly[frame_id][i]
                    for i in range(expected_total)
                    if i in assembly[frame_id]
                )

                # Decodificar JPEG
                arr = np.frombuffer(full_data, dtype=np.uint8)
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                if decoded is not None:
                    ts_ns = assembly_meta[frame_id][1]

                    with self._locks[channel_id]:
                        self._frames[channel_id] = decoded
                        self._frame_ids[channel_id] = frame_id
                        self._timestamps[channel_id] = ts_ns
                        self._frames_received[channel_id] += 1
                        self._fps_counters[channel_id] += 1

                        # Detectar frames perdidos
                        expected = self._last_frame_id[channel_id] + 1
                        if frame_id > expected and self._last_frame_id[channel_id] > 0:
                            self._frames_lost[channel_id] += (frame_id - expected)
                        self._last_frame_id[channel_id] = frame_id

                # Limpiar buffer de este frame
                del assembly[frame_id]
                del assembly_meta[frame_id]

            # Limpiar frames viejos/incompletos
            now = time.time()
            stale = [
                fid for fid, (_, _, t_recv) in assembly_meta.items()
                if now - t_recv > self._FRAGMENT_TIMEOUT
            ]
            for fid in stale:
                with self._locks[channel_id]:
                    self._frames_lost[channel_id] += 1
                del assembly[fid]
                del assembly_meta[fid]

            # Actualizar FPS cada segundo
            with self._locks[channel_id]:
                dt = time.time() - self._fps_timers[channel_id]
                if dt >= 1.0:
                    self._fps[channel_id] = self._fps_counters[channel_id] / dt
                    self._fps_counters[channel_id] = 0
                    self._fps_timers[channel_id] = time.time()

    def get_frames(self) -> dict[str, Optional[np.ndarray]]:
        """
        Retorna los 4 frames más recientes.

        Returns
        -------
        dict[str, np.ndarray | None]
            Diccionario con claves 'color', 'depth', 'ir_left', 'ir_right'.
            None si el canal no tiene datos.
        """
        result = {}
        for ch_id, name in CHANNELS.items():
            with self._locks[ch_id]:
                f = self._frames[ch_id]
                result[name] = f.copy() if f is not None else None
        return result

    def get_sync_info(self) -> dict[str, tuple[Optional[int], Optional[int]]]:
        """
        Retorna frame_id y timestamp de cada canal.

        Returns
        -------
        dict[str, tuple[int | None, int | None]]
            {nombre_canal: (frame_id, timestamp_ns)}
        """
        result = {}
        for ch_id, name in CHANNELS.items():
            with self._locks[ch_id]:
                result[name] = (self._frame_ids[ch_id], self._timestamps[ch_id])
        return result

    def get_stats(self) -> dict[str, dict[str, float | int]]:
        """
        Retorna estadísticas por canal.

        Returns
        -------
        dict[str, dict]
            {nombre_canal: {'fps': float, 'received': int, 'lost': int}}
        """
        result = {}
        for ch_id, name in CHANNELS.items():
            with self._locks[ch_id]:
                result[name] = {
                    'fps': self._fps[ch_id],
                    'received': self._frames_received[ch_id],
                    'lost': self._frames_lost[ch_id],
                }
        return result

    def get_telemetry(self) -> dict:
        """
        Retorna los datos de telemetría más recientes del emisor.

        Returns
        -------
        dict
            Datos de telemetría o diccionario vacío si no se han recibido.
        """
        with self._telemetry_lock:
            return self._telemetry.copy()

    @property
    def connected(self) -> bool:
        """True si al menos un canal ha recibido datos."""
        return any(
            self._frames_received[ch] > 0
            for ch in CHANNELS
        )

    def close(self) -> None:
        """Detiene la recepción y cierra sockets."""
        self._running = False

        for thread in self._threads.values():
            thread.join(timeout=2.0)

        for sock in self._sockets.values():
            try:
                sock.close()
            except Exception:
                pass

        try:
            self._heartbeat_socket.close()
        except Exception:
            pass

        self._sockets.clear()
        self._threads.clear()
