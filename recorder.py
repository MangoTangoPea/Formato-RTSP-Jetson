#!/usr/bin/env python3
"""
VideoRecorder — Grabación del mosaico completo (panel + 2x2) en un archivo .bag (ROS Bag v2.0).

Graba los 4 canales combinados con el panel de telemetría como un mosaico de 1540x960
en un único archivo .bag independiente con metadatos de sincronización esteganografiados
en los píxeles de la imagen. La escritura ocurre en un hilo dedicado.
"""

import os
import time
import queue
import struct
import threading
from typing import Optional

import cv2
import numpy as np

from config import RECORD_CODEC, RECORD_EXT, RECORD_FPS, MOSAIC_WIDTH, MOSAIC_HEIGHT


class BagWriter:
    """
    Escritor liviano de archivos ROS 1 Bag v2.0 en Python puro.

    Escribe mensajes sensor_msgs/CompressedImage en el tópico /mosaic/compressed.
    """

    def __init__(self, filename: str, topic: str = "/mosaic/compressed") -> None:
        self.filename = filename
        self.topic = topic
        self.file: Optional[object] = None
        self.conn_id: int = 0
        self.msg_seq: int = 0

    def _pack_field(self, name: str, val: bytes) -> bytes:
        data = name.encode('ascii') + b'=' + val
        return struct.pack('<I', len(data)) + data

    def open(self) -> None:
        self.file = open(self.filename, 'wb')
        self.file.write(b'#ROSBAG V2.0\n')

        # 1. Bag Header Record (op=0x03)
        header_bytes = (
            self._pack_field('op', b'\x03') +
            self._pack_field('index_pos', struct.pack('<Q', 0)) +
            self._pack_field('conn_count', struct.pack('<I', 1)) +
            self._pack_field('chunk_count', struct.pack('<I', 0))
        )
        padding = b'\x00' * 4096
        self.file.write(struct.pack('<I', len(header_bytes)) + header_bytes)
        self.file.write(struct.pack('<I', len(padding)) + padding)

        # 2. Connection Record (op=0x07)
        conn_header = (
            self._pack_field('op', b'\x07') +
            self._pack_field('conn', struct.pack('<I', self.conn_id)) +
            self._pack_field('topic', self.topic.encode('ascii'))
        )

        msg_def = (
            "std_msgs/Header header\n"
            "  uint32 seq\n"
            "  time stamp\n"
            "  string frame_id\n"
            "string format\n"
            "uint8[] data\n"
        )

        conn_data = (
            self._pack_field('topic', self.topic.encode('ascii')) +
            self._pack_field('type', b'sensor_msgs/CompressedImage') +
            self._pack_field('md5sum', b'293944692e6a663271362100f1a23e8a') +
            self._pack_field('message_definition', msg_def.encode('utf-8'))
        )

        self.file.write(struct.pack('<I', len(conn_header)) + conn_header)
        self.file.write(struct.pack('<I', len(conn_data)) + conn_data)

    def write_frame(
        self,
        frame_bgr: np.ndarray,
        frame_id: int = 0,
        timestamp_ns: int = 0,
    ) -> None:
        if self.file is None:
            return

        self.msg_seq += 1
        if timestamp_ns == 0:
            timestamp_ns = int(time.time() * 1e9)

        sec = int(timestamp_ns // 1_000_000_000)
        nsec = int(timestamp_ns % 1_000_000_000)

        # Comprimir frame BGR a JPEG de alta calidad
        _, encoded = cv2.imencode('.jpg', frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
        jpg_bytes = encoded.tobytes()

        frame_id_bytes = f"frame_{frame_id}".encode('ascii')
        header_msg = (
            struct.pack('<I', self.msg_seq) +
            struct.pack('<II', sec, nsec) +
            struct.pack('<I', len(frame_id_bytes)) + frame_id_bytes
        )

        fmt_bytes = b'jpeg'
        msg_bytes = (
            header_msg +
            struct.pack('<I', len(fmt_bytes)) + fmt_bytes +
            struct.pack('<I', len(jpg_bytes)) + jpg_bytes
        )

        msg_record_header = (
            self._pack_field('op', b'\x02') +
            self._pack_field('conn', struct.pack('<I', self.conn_id)) +
            self._pack_field('time', struct.pack('<II', sec, nsec))
        )

        self.file.write(struct.pack('<I', len(msg_record_header)) + msg_record_header)
        self.file.write(struct.pack('<I', len(msg_bytes)) + msg_bytes)

    def close(self) -> None:
        if self.file:
            try:
                self.file.close()
            except Exception:
                pass
            self.file = None


class VideoRecorder:
    """
    Graba el mosaico completo (panel + 4 canales) en un único archivo .bag (ROS Bag v2.0).

    Parameters
    ----------
    fps : int
        FPS del archivo.
    codec : str
        Formato de salida ('bag').
    """

    def __init__(self, fps: int = RECORD_FPS, codec: str = RECORD_CODEC) -> None:
        self.fps = fps
        self.codec = codec

        self._recording: bool = False
        self._writer: Optional[BagWriter] = None
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        self._frames_recorded: int = 0
        self._t_start: float = 0.0
        self._record_name: str = ""
        self._record_dir: str = ""
        self._bag_path: str = ""

    @property
    def recording(self) -> bool:
        """True si está grabando activamente."""
        return self._recording

    @property
    def frames_recorded(self) -> int:
        """Número de frames grabados en la sesión actual."""
        return self._frames_recorded

    @property
    def elapsed(self) -> float:
        """Segundos transcurridos desde el inicio de la grabación."""
        if not self._recording:
            return 0.0
        return time.time() - self._t_start

    @property
    def info(self) -> str:
        """Texto descriptivo de la grabación actual."""
        if not self._recording:
            return ""
        dur = self.elapsed
        return f"{self._record_name} | {dur:.0f}s | {self._frames_recorded} frames (.bag)"

    @property
    def record_name(self) -> str:
        """Nombre de la grabación actual."""
        return self._record_name

    def start(self, base_dir: str, nombre: str) -> bool:
        """
        Inicia la grabación del mosaico completo en formato .bag.

        Parameters
        ----------
        base_dir : str
            Carpeta base elegida por el usuario.
        nombre : str
            Nombre de la grabación.

        Returns
        -------
        bool
            True si se inició correctamente.
        """
        if self._recording:
            return False

        self._record_name = nombre
        self._record_dir = os.path.join(base_dir, nombre)
        os.makedirs(self._record_dir, exist_ok=True)

        self._bag_path = os.path.join(self._record_dir, f"{nombre}{RECORD_EXT}")

        try:
            self._writer = BagWriter(self._bag_path)
            self._writer.open()
        except Exception:
            self._cleanup_writer()
            return False

        # Iniciar hilo de escritura
        self._running = True
        self._frames_recorded = 0
        self._t_start = time.time()
        self._queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._write_loop,
            name="VideoRecorder",
            daemon=True,
        )
        self._thread.start()
        self._recording = True

        return True

    def write_frame(
        self,
        mosaic_frame: np.ndarray,
        frame_id: int = 0,
        timestamp_ns: int = 0,
    ) -> None:
        """
        Encola el frame del mosaico completo para escritura asíncrona en el archivo .bag.

        Parameters
        ----------
        mosaic_frame : np.ndarray
            Imagen BGR de 1540x960 con panel de telemetría + 4 cámaras.
        frame_id : int, opcional
            Número del frame.
        timestamp_ns : int, opcional
            Timestamp en nanosegundos.
        """
        if not self._recording or mosaic_frame is None:
            return

        self._queue.put((mosaic_frame.copy(), frame_id, timestamp_ns))

    def _write_loop(self) -> None:
        """Hilo de escritura: desencola frames del mosaico y los escribe a disco en formato .bag."""
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            frame, frame_id, timestamp_ns = item

            if self._writer is not None:
                # Asegurar tamaño correcto para la imagen
                if frame.shape[:2] != (MOSAIC_HEIGHT, MOSAIC_WIDTH):
                    frame = cv2.resize(frame, (MOSAIC_WIDTH, MOSAIC_HEIGHT), interpolation=cv2.INTER_AREA)
                self._writer.write_frame(frame, frame_id, timestamp_ns)

            self._frames_recorded += 1
            self._queue.task_done()

    def stop(self) -> None:
        """Detiene la grabación y cierra el archivo .bag."""
        if not self._recording:
            return

        self._recording = False
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        self._cleanup_writer()

    def _cleanup_writer(self) -> None:
        """Libera el BagWriter."""
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
