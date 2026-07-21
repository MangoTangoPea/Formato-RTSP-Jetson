#!/usr/bin/env python3
"""
VideoRecorder — Grabación del mosaico completo (panel + 2x2) en un solo archivo MKV (.mkv).

Graba los 4 canales combinados con el panel de telemetría como una sola toma
de 1540x960 en un archivo .mkv (Matroska Container) independiente con los metadatos
de sincronización esteganografiados en la imagen.
La escritura ocurre en un hilo dedicado para no bloquear la visualización.
"""

import os
import time
import queue
import threading
from typing import Optional

import cv2
import numpy as np

from config import RECORD_CODEC, RECORD_EXT, RECORD_FPS, MOSAIC_WIDTH, MOSAIC_HEIGHT


class VideoRecorder:
    """
    Graba el mosaico completo (panel + 4 canales) en un único archivo MKV (.mkv).

    Parameters
    ----------
    fps : int
        FPS del archivo de salida.
    codec : str
        Codec de video (por defecto 'XVID').
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
        return f"{self._record_name} | {dur:.0f}s | {self._frames_recorded} frames (.mkv)"

    @property
    def record_name(self) -> str:
        """Nombre de la grabación actual."""
        return self._record_name

    def start(self, base_dir: str, nombre: str) -> bool:
        """
        Inicia la grabación del mosaico completo en formato MKV.

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

        self._video_path = os.path.join(self._record_dir, f"{nombre}{RECORD_EXT}")

        # Configurar VideoWriter para MKV (Matroska)
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        self._writer = cv2.VideoWriter(
            self._video_path, fourcc, self.fps, (MOSAIC_WIDTH, MOSAIC_HEIGHT)
        )

        if not self._writer.isOpened():
            # Fallback a MJPG si el codec por defecto falla
            fallback_fourcc = cv2.VideoWriter_fourcc(*'MJPG')
            self._writer = cv2.VideoWriter(
                self._video_path, fallback_fourcc, self.fps, (MOSAIC_WIDTH, MOSAIC_HEIGHT)
            )
            if not self._writer.isOpened():
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
        frame_id: Optional[int] = None,
        timestamp_ns: Optional[int] = None,
    ) -> None:
        """
        Encola el frame del mosaico completo para escritura asíncrona en el archivo MKV.
        """
        if not self._recording or mosaic_frame is None:
            return

        self._queue.put(mosaic_frame.copy())

    def _write_loop(self) -> None:
        """Hilo de escritura: desencola frames del mosaico y los escribe a disco."""
        while self._running or not self._queue.empty():
            try:
                frame = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if self._writer is not None and self._writer.isOpened():
                if frame.shape[:2] != (MOSAIC_HEIGHT, MOSAIC_WIDTH):
                    frame = cv2.resize(frame, (MOSAIC_WIDTH, MOSAIC_HEIGHT), interpolation=cv2.INTER_AREA)
                self._writer.write(frame)

            self._frames_recorded += 1
            self._queue.task_done()

    def stop(self) -> None:
        """Detiene la grabación y cierra el archivo MKV."""
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
