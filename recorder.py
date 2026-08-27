#!/usr/bin/env python3
"""
VideoRecorder (DB3) — Grabación multicanal en un solo archivo SQLite3 (.db3).

Guarda la totalidad de la información de los 4 canales con preservación 100% SIN PÉRDIDAS
del canal de profundidad en 16 bits (matriz uint16 / Z16 nativa en milímetros),
junto con Color, IR Izquierdo, IR Derecho, telemetría y metadatos de sincronización
en un único archivo autónomo SQLite3 (.db3).
La escritura ocurre en un hilo desacoplado mediante cola asíncrona para no comprometer los 30 FPS.
"""

import os
import time
import json
import zlib
import queue
import sqlite3
import datetime
import threading
from typing import Optional, Union, Dict, Any

import cv2
import numpy as np

from config import RECORD_EXT, RECORD_FPS, CAMERA_WIDTH, CAMERA_HEIGHT


class VideoRecorder:
    """
    Graba todos los canales y telemetría en un único archivo de base de datos SQLite3 (.db3).

    Parameters
    ----------
    fps : int
        FPS objetivo de la grabación.
    """

    def __init__(self, fps: int = RECORD_FPS) -> None:
        self.fps = fps

        self._recording: bool = False
        self._conn: Optional[sqlite3.Connection] = None
        self._cursor: Optional[sqlite3.Cursor] = None
        self._queue: queue.Queue = queue.Queue(maxsize=120)
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

        self._frames_recorded: int = 0
        self._t_start: float = 0.0
        self._record_name: str = ""
        self._record_dir: str = ""
        self._db_path: str = ""

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
        return f"{self._record_name} | {dur:.0f}s | {self._frames_recorded} frames (.db3)"

    @property
    def record_name(self) -> str:
        """Nombre de la grabación actual."""
        return self._record_name

    @property
    def video_path(self) -> str:
        """Ruta completa del archivo .db3 grabado (mantiene compatibilidad de nombre con client.py)."""
        return self._db_path

    @property
    def db_path(self) -> str:
        """Ruta completa del archivo .db3 grabado."""
        return self._db_path

    def start(self, base_dir: str = "./grabaciones", nombre: Optional[str] = None) -> bool:
        """
        Inicia la grabación en un nuevo archivo de base de datos SQLite3 (.db3).

        Parameters
        ----------
        base_dir : str, optional
            Carpeta base donde se guardará la grabación.
        nombre : str, optional
            Nombre base del archivo de grabación.

        Returns
        -------
        bool
            True si la base de datos se inicializó correctamente.
        """
        if self._recording:
            return False

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        if not nombre:
            nombre = f"grabacion_{timestamp}"

        self._record_name = nombre
        self._record_dir = base_dir
        os.makedirs(self._record_dir, exist_ok=True)

        self._db_path = os.path.join(self._record_dir, f"{nombre}{RECORD_EXT}")

        try:
            # Inicializar conexión SQLite3 optimizada
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._cursor = self._conn.cursor()

            # Configuraciones PRAGMA de alto rendimiento para inserciones continuas en tiempo real
            self._cursor.execute("PRAGMA journal_mode = WAL;")
            self._cursor.execute("PRAGMA synchronous = NORMAL;")
            self._cursor.execute("PRAGMA temp_store = MEMORY;")
            self._cursor.execute("PRAGMA cache_size = -64000;")  # 64MB cache en RAM

            # Crear tablas
            self._cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

            self._cursor.execute("""
                CREATE TABLE IF NOT EXISTS frames (
                    frame_id INTEGER PRIMARY KEY,
                    timestamp_ns INTEGER NOT NULL,
                    datetime_str TEXT,
                    color BLOB,
                    depth_z16 BLOB NOT NULL,
                    ir_left BLOB,
                    ir_right BLOB,
                    telemetry TEXT
                );
            """)

            self._cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON frames(timestamp_ns);")

            # Guardar metadatos generales de la sesión
            session_meta = {
                "format_version": "2.0_DB3_Z16",
                "created_at": datetime.datetime.now().isoformat(),
                "width": str(CAMERA_WIDTH),
                "height": str(CAMERA_HEIGHT),
                "fps": str(self.fps),
                "camera_model": "Intel RealSense D435",
                "depth_format": "Z16_UINT16_MM_RAW",
            }
            for k, v in session_meta.items():
                self._cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?);", (k, v))

            self._conn.commit()

        except Exception as e:
            print(f"[ERROR] No se pudo inicializar la base de datos .db3: {e}")
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

        # Iniciar hilo de escritura asíncrono
        self._running = True
        self._frames_recorded = 0
        self._t_start = time.time()
        self._queue = queue.Queue(maxsize=120)
        self._thread = threading.Thread(
            target=self._write_loop,
            name="DB3VideoRecorder",
            daemon=True,
        )
        self._thread.start()
        self._recording = True

        return True

    def write_frame(
        self,
        color: Optional[np.ndarray] = None,
        depth_z16: Optional[np.ndarray] = None,
        ir_left: Optional[np.ndarray] = None,
        ir_right: Optional[np.ndarray] = None,
        telemetry: Optional[Union[dict, str]] = None,
        frame_id: Optional[int] = None,
        timestamp_ns: Optional[int] = None,
        mosaic_fallback: Optional[np.ndarray] = None,
    ) -> None:
        """
        Encola un frame con todos sus canales para escritura asíncrona en la base de datos .db3.

        Parameters
        ----------
        color : np.ndarray, optional
            Imagen Color BGR (H x W x 3).
        depth_z16 : np.ndarray, optional
            Matriz de profundidad uint16 (H x W) en milímetros (Z16 puro).
        ir_left : np.ndarray, optional
            Imagen Infrarrojo Izquierdo Y8 o BGR (H x W).
        ir_right : np.ndarray, optional
            Imagen Infrarrojo Derecho Y8 o BGR (H x W).
        telemetry : dict | str, optional
            Datos de telemetría de hardware Jetson.
        frame_id : int, optional
            Identificador secuencial del frame.
        timestamp_ns : int, optional
            Timestamp en nanosegundos del reloj emisor.
        """
        if not self._recording:
            return

        # Fallback si se pasa un único frame mosaico legacy
        if depth_z16 is None and isinstance(color, np.ndarray) and color.shape[0] > CAMERA_HEIGHT:
            mosaic_fallback = color
            color = None

        if mosaic_fallback is not None:
            # Extraer cuadrantes si se proporcionó mosaico
            h, w = mosaic_fallback.shape[:2]
            panel_h = 120 if h >= 1440 else 0
            color = mosaic_fallback[panel_h:panel_h + CAMERA_HEIGHT, 0:CAMERA_WIDTH]
            depth_bgr = mosaic_fallback[panel_h:panel_h + CAMERA_HEIGHT, CAMERA_WIDTH:CAMERA_WIDTH * 2]
            # Desempaquetar Z16
            low = depth_bgr[:, :, 0].astype(np.uint16)
            high = depth_bgr[:, :, 1].astype(np.uint16)
            depth_z16 = (high << 8) | low
            ir_left = mosaic_fallback[panel_h + CAMERA_HEIGHT:panel_h + CAMERA_HEIGHT * 2, 0:CAMERA_WIDTH]
            ir_right = mosaic_fallback[panel_h + CAMERA_HEIGHT:panel_h + CAMERA_HEIGHT * 2, CAMERA_WIDTH:CAMERA_WIDTH * 2]

        if depth_z16 is None:
            return

        item = (
            frame_id or (self._frames_recorded + 1),
            timestamp_ns or int(time.time() * 1e9),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            color.copy() if color is not None else None,
            depth_z16.copy() if isinstance(depth_z16, np.ndarray) else depth_z16,
            ir_left.copy() if ir_left is not None else None,
            ir_right.copy() if ir_right is not None else None,
            telemetry,
        )

        try:
            self._queue.put_nowait(item)
        except queue.Full:
            pass  # Descartar frame si la cola se satura para no bloquear la visualización

    def _write_loop(self) -> None:
        """Hilo dedicado de escritura a la base de datos SQLite3."""
        if not self._conn or not self._cursor:
            return

        batch_count = 0
        last_commit = time.time()

        while self._running or not self._queue.empty():
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if batch_count > 0 and (time.time() - last_commit) > 0.5:
                    try:
                        self._conn.commit()
                        batch_count = 0
                        last_commit = time.time()
                    except Exception:
                        pass
                continue

            (fid, ts_ns, dt_str, color_img, depth_arr, ir_l_img, ir_r_img, telem) = item

            # 1. Serializar Color a JPEG de alta fidelidad
            color_blob = None
            if color_img is not None:
                _, enc_col = cv2.imencode('.jpg', color_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                color_blob = enc_col.tobytes()

            # 2. Serializar Profundidad Z16 (uint16 puro sin pérdidas comprimido con zlib nivel 1)
            # zlib level 1 comprime en ~1ms por frame reduciendo el tamaño en disco un 60% sin perder 1 solo bit
            if depth_arr.dtype != np.uint16:
                depth_arr = depth_arr.astype(np.uint16)
            depth_bytes = depth_arr.tobytes()
            depth_blob = zlib.compress(depth_bytes, level=1)

            # 3. Serializar IR Left a JPEG
            ir_l_blob = None
            if ir_l_img is not None:
                _, enc_ir_l = cv2.imencode('.jpg', ir_l_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                ir_l_blob = enc_ir_l.tobytes()

            # 4. Serializar IR Right a JPEG
            ir_r_blob = None
            if ir_r_img is not None:
                _, enc_ir_r = cv2.imencode('.jpg', ir_r_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                ir_r_blob = enc_ir_r.tobytes()

            # 5. Serializar Telemetría a JSON
            telem_str = ""
            if isinstance(telem, dict):
                try:
                    telem_str = json.dumps(telem, separators=(',', ':'))
                except Exception:
                    telem_str = "{}"
            elif isinstance(telem, str):
                telem_str = telem

            try:
                self._cursor.execute("""
                    INSERT OR REPLACE INTO frames
                    (frame_id, timestamp_ns, datetime_str, color, depth_z16, ir_left, ir_right, telemetry)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, (fid, ts_ns, dt_str, color_blob, depth_blob, ir_l_blob, ir_r_blob, telem_str))

                self._frames_recorded += 1
                batch_count += 1

                if batch_count >= 15 or (time.time() - last_commit) >= 0.5:
                    self._conn.commit()
                    batch_count = 0
                    last_commit = time.time()

            except Exception as e:
                print(f"[ERROR] Error al insertar frame {fid} en .db3: {e}")

            self._queue.task_done()

        # Commit final
        if self._conn:
            try:
                self._conn.commit()
            except Exception:
                pass

    def stop(self) -> None:
        """Detiene la grabación y cierra limpiamente la base de datos .db3."""
        if not self._recording:
            return

        self._recording = False
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)

        self._cleanup_db()

    def _cleanup_db(self) -> None:
        """Cierra el cursor y la conexión SQLite3 optimizando el archivo WAL."""
        if self._conn is not None:
            try:
                self._conn.commit()
                # Realizar checkpoint del WAL para consolidar todo en el archivo .db3 principal
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._cursor = None
