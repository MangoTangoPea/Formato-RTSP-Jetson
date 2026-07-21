#!/usr/bin/env python3
"""
GUI — Interfaz visual para el Receptor RTP.

Muestra los 4 canales (Color, Depth, IR Left, IR Right) en una cuadrícula 2x2.
Incluye HUD por cuadrante, barra de estado inferior, indicador visual de grabación
parpadeante y ventana emergente de configuración de grabación (nombre + carpeta).
"""

import time
import datetime
from typing import Optional, Tuple

import cv2
import numpy as np

from utils import formatear_timestamp_ns
from config import CAMERA_WIDTH, CAMERA_HEIGHT

# Colores BGR
COLOR_GREEN = (0, 255, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_RED = (0, 0, 255)
COLOR_YELLOW = (0, 255, 255)
COLOR_GRAY = (70, 70, 70)
COLOR_BG_DARK = (20, 20, 20)

TITULOS_CANALES = {
    'color': ("RGB", COLOR_GREEN),
    'depth': ("DEPTH", COLOR_WHITE),
    'ir_left': ("IR LEFT", COLOR_GREEN),
    'ir_right': ("IR RIGHT", COLOR_GREEN),
}


def crear_placeholder(width: int, height: int, texto: str) -> np.ndarray:
    """Crea una imagen negra con texto centrado para canales no disponibles."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.6
    thickness = 1
    size = cv2.getTextSize(texto, font, scale, thickness)[0]
    x = (width - size[0]) // 2
    y = (height + size[1]) // 2
    cv2.putText(img, texto, (x, y), font, scale, (100, 100, 100), thickness, cv2.LINE_AA)
    return img


class GUI:
    """
    Gestor de la interfaz gráfica del Receptor.

    Parameters
    ----------
    window_name : str
        Nombre de la ventana OpenCV.
    """

    def __init__(self, window_name: str = "Receptor RTP - RealSense D435") -> None:
        self.window_name = window_name
        self.font = cv2.FONT_HERSHEY_SIMPLEX

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(self.window_name, 1280, 980)

    def draw_hud(
        self,
        img: np.ndarray,
        title: str,
        title_color: Tuple[int, int, int],
        fps: float,
        frame_id: Optional[int],
        timestamp_ns: Optional[int],
    ) -> None:
        """Dibuja el título y HUD sobre un cuadrante."""
        # Título en esquina superior izquierda
        cv2.putText(img, title, (15, 35), self.font, 0.9, title_color, 2, cv2.LINE_AA)

        # Información técnica en overlay semitransparente
        ts_str = formatear_timestamp_ns(timestamp_ns)
        fid_str = f"FID: {frame_id}" if frame_id is not None else "FID: ---"
        fps_str = f"FPS: {fps:.1f}"

        info_txt = f"{fid_str} | {ts_str} | {fps_str}"
        cv2.putText(img, info_txt, (15, 460), self.font, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    def render(
        self,
        frames: dict[str, Optional[np.ndarray]],
        stats: dict[str, dict[str, float | int]],
        sync_info: dict[str, Tuple[Optional[int], Optional[int]]],
        recording: bool,
        rec_info: str,
    ) -> None:
        """
        Construye y renderiza el mosaico 2x2 con overlays e indicadores.

        Parameters
        ----------
        frames : dict
            Frames por canal ('color', 'depth', 'ir_left', 'ir_right').
        stats : dict
            Estadísticas FPS por canal.
        sync_info : dict
            Frame ID y Timestamp por canal.
        recording : bool
            True si la grabación está activa.
        rec_info : str
            Texto descriptivo de la grabación.
        """
        processed: dict[str, np.ndarray] = {}

        for ch_key in ['color', 'depth', 'ir_left', 'ir_right']:
            f = frames.get(ch_key)
            title, color = TITULOS_CANALES[ch_key]

            if f is None:
                img = crear_placeholder(CAMERA_WIDTH, CAMERA_HEIGHT, f"Esperando {title}...")
            else:
                img = f.copy()
                if img.ndim == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

            fps = stats.get(ch_key, {}).get('fps', 0.0)
            fid, ts = sync_info.get(ch_key, (None, None))

            self.draw_hud(img, title, color, fps, fid, ts)
            processed[ch_key] = img

        # Mosaico 2x2 (Top: Color | Depth, Bottom: IR Left | IR Right)
        top = np.hstack((processed['color'], processed['depth']))
        bottom = np.hstack((processed['ir_left'], processed['ir_right']))
        mosaico = np.vstack((top, bottom))  # 1280x960

        # Si se está grabando: indicador visual parpadeante y borde rojo
        if recording:
            # Borde rojo alrededor de todo el mosaico
            cv2.rectangle(mosaico, (0, 0), (mosaico.shape[1] - 1, mosaico.shape[0] - 1), COLOR_RED, 4)

            # Círculo rojo parpadeante (alterna cada 0.5s)
            parpadeo = int(time.time() * 2) % 2 == 0
            if parpadeo:
                cv2.circle(mosaico, (mosaico.shape[1] - 180, 30), 10, COLOR_RED, -1)

            cv2.putText(mosaico, "REC", (mosaico.shape[1] - 160, 37), self.font, 0.75, COLOR_RED, 2, cv2.LINE_AA)

            if rec_info:
                cv2.putText(mosaico, rec_info, (mosaico.shape[1] - 400, 65), self.font, 0.45, COLOR_WHITE, 1, cv2.LINE_AA)

        # Barra de estado inferior (20px)
        bar = np.zeros((25, mosaico.shape[1], 3), dtype=np.uint8)
        controles_txt = "Controles: [R] Iniciar Grabacion  |  [E] Detener Grabacion  |  [Q / ESC] Salir"
        cv2.putText(bar, controles_txt, (15, 17), self.font, 0.45, COLOR_YELLOW, 1, cv2.LINE_AA)

        window = np.vstack((mosaico, bar))
        cv2.imshow(self.window_name, window)

    def handle_input(self) -> Optional[str]:
        """
        Captura teclas presionadas en la ventana OpenCV.

        Returns
        -------
        str | None
            'start_rec', 'stop_rec', 'quit' o None.
        """
        key = cv2.waitKey(10) & 0xFF
        if key in (ord('r'), ord('R')):
            return "start_rec"
        elif key in (ord('e'), ord('E')):
            return "stop_rec"
        elif key in (ord('q'), ord('Q'), 27):  # ESC
            return "quit"
        return None

    def ask_recording_info(self) -> Optional[Tuple[str, str]]:
        """
        Muestra un cuadro de diálogo Tkinter para ingresar el nombre de la grabación
        y seleccionar la carpeta de guardado.

        Returns
        -------
        Tuple[str, str] | None
            (directorio_base, nombre_grabacion) o None si el usuario canceló.
        """
        default_name = f"grabacion_{datetime.datetime.now():%Y%m%d_%H%M%S}"

        try:
            import tkinter as tk
            from tkinter import filedialog, simpledialog

            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)

            # 1. Pedir nombre de la grabación
            name = simpledialog.askstring(
                "Nombre de la Grabación",
                "Ingrese el nombre para la carpeta de grabación:",
                initialvalue=default_name,
                parent=root
            )

            if not name or not name.strip():
                root.destroy()
                return None

            name = name.strip()

            # 2. Pedir carpeta de destino
            directory = filedialog.askdirectory(
                title="Seleccione la carpeta donde guardar la grabación",
                parent=root
            )

            root.destroy()

            if not directory:
                return None

            return directory, name

        except Exception:
            # Fallback por terminal si no hay GUI Tkinter
            try:
                print("\n--- Configurar Grabación ---")
                name_in = input(f"Nombre de grabación [{default_name}]: ").strip()
                name = name_in if name_in else default_name

                import os
                default_dir = os.path.abspath("./grabaciones")
                dir_in = input(f"Carpeta destino [{default_dir}]: ").strip()
                directory = dir_in if dir_in else default_dir

                return directory, name
            except Exception:
                return None

    def destroy(self) -> None:
        """Cierra todas las ventanas de OpenCV."""
        cv2.destroyAllWindows()
