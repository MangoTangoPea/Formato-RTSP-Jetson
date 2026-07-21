#!/usr/bin/env python3
"""
VideoRecorder — Grabación de 4 canales independientes.

Graba Color, Depth, IR_Left e IR_Right como 4 archivos .avi
independientes usando el codec MJPG. La escritura ocurre en un
hilo dedicado para no bloquear la visualización.
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
    Graba 4 canales de video de forma asíncrona.

    La grabación ocurre únicamente en el Receptor. Los frames se
    encolan y un hilo dedicado los escribe a disco.

    Parameters
    ----------
    fps : int
        FPS de los archivos de salida.
    codec : str
        Codec de video (por defecto 'MJPG').
    """

    SUBDIRS: dict[str, str] = {
        'color': 'Color',
        'depth': 'Depth',
        'ir_left': 'IR_Left',
        'ir_right': 'IR_Right',
    }

    def __init__(self, fps: int = RECORD_FPS, codec: str = RECORD_CODEC) -> None:
        self.fps = fps
        self.codec = codec

        self._recording: bool = False
        self._writers: dict[str, cv2.VideoWriter] = {}
        self._queue: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        self._frames_recorded: int = 0
        self._t_start: float = 0.0
        self._record_name: str = ""
        self._record_dir: str = ""
        self._csv_path: str = ""

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
        Inicia la grabación.

        Parameters
        ----------
        base_dir : str
            Carpeta base donde se creará la subcarpeta de la grabación.
        nombre : str
            Nombre de la grabación (se usa como nombre de carpeta).

        Returns
        -------
        bool
            True si se inició correctamente.
        """
        if self._recording:
            return False

        self._record_name = nombre
        self._record_dir = os.path.join(base_dir, nombre)

        # Crear estructura de carpetas
        for subdir in self.SUBDIRS.values():
            os.makedirs(os.path.join(self._record_dir, subdir), exist_ok=True)

        # Crear VideoWriters
        fourcc = cv2.VideoWriter_fourcc(*self.codec)
        for key, subdir in self.SUBDIRS.items():
            filename = f"{key}{RECORD_EXT}"
            filepath = os.path.join(self._record_dir, subdir, filename)
            writer = cv2.VideoWriter(filepath, fourcc, self.fps,
                                     (CAMERA_WIDTH, CAMERA_HEIGHT))
            if not writer.isOpened():
                self._cleanup_writers()
                return False
            self._writers[key] = writer

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
        frames: dict[str, Optional[np.ndarray]],
        frame_id: int,
        timestamp_ns: int,
    ) -> None:
        """
        Encola un set de frames para escritura asíncrona.

        Parameters
        ----------
        frames : dict[str, np.ndarray | None]
            Diccionario con los 4 frames.
        frame_id : int
            Número del frame.
        timestamp_ns : int
            Timestamp en nanosegundos.
        """
        if not self._recording:
            return

        # Copiar frames para el hilo de escritura
        copies = {}
        for key in self.SUBDIRS:
            f = frames.get(key)
            if f is not None:
                copies[key] = f.copy()

        if copies:
            self._queue.put((copies, frame_id, timestamp_ns))

    def _write_loop(self) -> None:
        """Hilo de escritura: desencola frames y los escribe a disco."""
        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue

            copies, frame_id, timestamp_ns = item

            for key, writer in self._writers.items():
                frame = copies.get(key)
                if frame is not None:
                    # Asegurar que sea BGR de 3 canales
                    if frame.ndim == 2:
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    writer.write(frame)

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
        """Detiene la grabación y cierra los archivos."""
        if not self._recording:
            return

        self._recording = False
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        self._cleanup_writers()

    def _cleanup_writers(self) -> None:
        """Libera todos los VideoWriter."""
        for writer in self._writers.values():
            try:
                writer.release()
            except Exception:
                pass
        self._writers.clear()
