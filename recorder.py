#!/usr/bin/env python3
"""
VideoRecorder — Grabación del mosaico 2x2 en un solo archivo MP4.

Graba los 4 canales combinados en una sola toma de 1280x960 como un archivo .mp4
independiente con el codec mp4v (MPEG-4), acompañado de su archivo metadata.csv.
La escritura ocurre en un hilo dedicado para no bloquear la visualización.
"""

import os
import time
import queue
import threading
import datetime
from typing import Optional

import cv2
import numpy as np

from config import RECORD_CODEC, RECORD_EXT, RECORD_FPS, CAMERA_WIDTH, CAMERA_HEIGHT


class VideoRecorder:
    """
    Graba el mosaico 2x2 de los 4 canales en un único archivo MP4.

    Parameters
    ----------
    fps : int
        FPS del archivo de salida.
    codec : str
        Codec de video (por defecto 'mp4v').
    """

    def __init__(self, fps: int = RECORD_FPS, codec: str = RECORD_CODEC) -> None:
        self.fps = fps
        self.codec = codec

        self._recording: bool = False
        self._writer: Optional[cv2.VideoWriter] = None
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        self._frames_recorded: int = 0
        self._t_start: float = 0.0
        self._record_name: str = ""
        self._record_dir: str = ""
        self._csv_path: str = ""
        self._video_path: str = ""

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
        return f"{self._record_name} | {dur:.0f}s | {self._frames_recorded} frames"

    @property
    def record_name(self) -> str:
        """Nombre de la grabación actual."""
        return self._record_name

    def start(self, base_dir: str, nombre: str) -> bool:
        """
        Inicia la grabación del mosaico.

        Parameters
        ----------
        base_dir : str
            Carpeta base elegida por el usuario.
        nombre : str
            Nombre de la grabación (se usa como subcarpeta y nombre de archivo).

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

        # Mosaico de 2x2 cámaras (640x2 = 1280, 480x2 = 960)
        mosaic_width = CAMERA_WIDTH * 2
        mosaic_height = CAMERA_HEIGHT * 2

        self._video_path = os.path.join(self._record_dir, f"{nombre}{RECORD_EXT}")
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        self._writer = cv2.VideoWriter(
            self._video_path, fourcc, self.fps, (mosaic_width, mosaic_height)
        )

        if not self._writer.isOpened():
            self._cleanup_writer()
            return False

        # CSV de metadatos
        self._csv_path = os.path.join(self._record_dir, "metadata.csv")
        with open(self._csv_path, "w", encoding="utf-8") as f:
            f.write("frame_id,timestamp_ns,timestamp_utc\n")

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
        frame_id: int,
        timestamp_ns: int,
    ) -> None:
        """
        Encola el frame del mosaico para escritura asíncrona.

        Parameters
        ----------
        mosaic_frame : np.ndarray
            Imagen BGR de 1280x960 con las 4 cámaras integradas.
        frame_id : int
            Número del frame.
        timestamp_ns : int
            Timestamp en nanosegundos.
        """
        if not self._recording or mosaic_frame is None:
            return

        self._queue.put((mosaic_frame.copy(), frame_id, timestamp_ns))

    def _write_loop(self) -> None:
        """Hilo de escritura: desencola frames del mosaico y los escribe a disco."""
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            frame, frame_id, timestamp_ns = item

            if self._writer is not None and self._writer.isOpened():
                self._writer.write(frame)

            # Escribir metadatos
            try:
                dt_utc = datetime.datetime.fromtimestamp(
                    timestamp_ns / 1e9, datetime.timezone.utc
                )
                fecha = dt_utc.isoformat()
            except Exception:
                fecha = "unknown"

            try:
                with open(self._csv_path, "a", encoding="utf-8") as f:
                    f.write(f"{frame_id},{timestamp_ns},{fecha}\n")
            except Exception:
                pass

            self._frames_recorded += 1
            self._queue.task_done()

    def stop(self) -> None:
        """Detiene la grabación y cierra el archivo MP4."""
        if not self._recording:
            return

        self._recording = False
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        self._cleanup_writer()

    def _cleanup_writer(self) -> None:
        """Libera el VideoWriter."""
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None
