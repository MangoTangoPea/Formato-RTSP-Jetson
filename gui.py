#!/usr/bin/env python3
"""
GUI — Interfaz visual responsive para el Receptor RTP.

Muestra los 4 canales (Color, Depth, IR Left, IR Right) en una cuadrícula 2x2
junto a un panel lateral izquierdo con información de telemetría del emisor
(temperaturas Jetson, ASIC, fecha/hora, resolución). La ventana es
redimensionable y maximizable sin espacios blancos ni pérdida de calidad.
"""

import time
import datetime
from typing import Optional, Tuple

import cv2
import numpy as np

from utils import formatear_timestamp_ns
from config import (
    CAMERA_WIDTH, CAMERA_HEIGHT, PANEL_WIDTH,
    MOSAIC_WIDTH, MOSAIC_HEIGHT,
)

# Colores BGR
COLOR_GREEN = (0, 255, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_RED = (0, 0, 255)
COLOR_YELLOW = (0, 255, 255)
COLOR_GRAY = (70, 70, 70)
COLOR_BG_DARK = (20, 20, 20)
COLOR_CONNECTED = (0, 200, 0)
COLOR_DISCONNECTED = (0, 0, 200)

TITULOS_CANALES = {
    'color': ("RGB", COLOR_GREEN),
    'depth': ("DEPTH", COLOR_WHITE),
    'ir_left': ("IR LEFT", COLOR_GREEN),
    'ir_right': ("IR RIGHT", COLOR_GREEN),
}


def crear_placeholder(width: int, height: int, texto: str) -> np.ndarray:
    """Crea una imagen de fondo oscuro con texto centrado para canales no disponibles."""
    img = np.full((height, width, 3), COLOR_BG_DARK, dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.85 if width >= 1280 else 0.60
    thickness = 2 if width >= 1280 else 1
    size = cv2.getTextSize(texto, font, scale, thickness)[0]
    x = (width - size[0]) // 2
    y = (height + size[1]) // 2
    cv2.putText(img, texto, (x, y), font, scale, (140, 140, 140), thickness, cv2.LINE_AA)
    return img


class GUI:
    """
    Gestor de la interfaz gráfica responsive del Receptor.

    Construye el mosaico a resolución nativa (panel + cuadrícula 2x2) para grabación
    y lo escala proporcionalmente al tamaño de la ventana para visualización.

    Parameters
    ----------
    window_name : str
        Nombre de la ventana OpenCV.
    """

    # Resolución nativa del mosaico completo (panel + 4 cámaras)
    NATIVE_W: int = MOSAIC_WIDTH
    NATIVE_H: int = MOSAIC_HEIGHT

    def __init__(self, window_name: str = "Receptor RTP - RealSense D435") -> None:
        self.window_name = window_name
        self.font = cv2.FONT_HERSHEY_SIMPLEX

        # cv2.WINDOW_GUI_NORMAL elimina la barra de herramientas y botones superiores de Qt/OpenCV
        cv2.namedWindow(
            self.window_name,
            cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_NORMAL
        )
        cv2.resizeWindow(self.window_name, self.NATIVE_W, self.NATIVE_H)

    def _create_info_panel(
        self,
        telemetry: dict,
        height: int,
    ) -> np.ndarray:
        """
        Dibuja el panel lateral izquierdo con información de telemetría.

        Replica el diseño de realsense_monitor_jetson.py con los datos
        de la Jetson transmitidos por el emisor, ajustado al ancho amplio del panel.

        Parameters
        ----------
        telemetry : dict
            Datos de telemetría del emisor (puede estar vacío).
        height : int
            Alto del panel en píxeles (debe coincidir con el mosaico).

        Returns
        -------
        np.ndarray
            Imagen BGR de PANEL_WIDTH x height.
        """
        panel = np.full((height, PANEL_WIDTH, 3), COLOR_BG_DARK, dtype=np.uint8)

        # Extraer datos de telemetría (con valores por defecto)
        date_str = telemetry.get('date_str', '--/--/----')
        time_str = telemetry.get('time_str', '--:--:--')
        resolution = telemetry.get('resolution', '---x---')
        fps_config = telemetry.get('fps_config', '--')
        asic_temp = telemetry.get('asic_temp')
        jetson_temps = telemetry.get('jetson_temps', {})

        # Escalas y grosores optimizados para PANEL_WIDTH amplio
        scale_title = 0.95
        scale_section = 0.85
        scale_text = 0.72

        info_lines: list[tuple[str, tuple[int, int, int], float, int]] = []

        # Título principal
        info_lines.append(("Intel RealSense D435", COLOR_YELLOW, scale_title, 2))
        info_lines.append(("__separator__", COLOR_GRAY, 0, 0))

        # Información general de la cámara
        info_lines.append((f"Fecha   {date_str}", COLOR_WHITE, scale_text, 1))
        info_lines.append((f"Hora    {time_str}", COLOR_WHITE, scale_text, 1))
        info_lines.append((f"Resol.  {resolution}", COLOR_WHITE, scale_text, 1))
        info_lines.append((f"Config. {fps_config} FPS", COLOR_WHITE, scale_text, 1))

        if asic_temp is not None:
            info_lines.append((f"ASIC    {asic_temp:.1f} C", COLOR_WHITE, scale_text, 1))

        # Separador
        info_lines.append(("", COLOR_WHITE, scale_text, 1))

        # Sección Hardware Jetson
        info_lines.append(("Jetson Hardware", COLOR_YELLOW, scale_section, 2))

        has_jetson_data = False
        for label in ['CPU', 'GPU', 'SOC', 'Board']:
            temp = jetson_temps.get(label)
            if temp is not None:
                info_lines.append((f"{label:<7} {temp:.1f} C", COLOR_WHITE, scale_text, 1))
                has_jetson_data = True

        if not has_jetson_data:
            info_lines.append(("Sin datos termicos", (120, 120, 120), scale_text, 1))

        # Separador
        info_lines.append(("", COLOR_WHITE, scale_text, 1))

        # Estado de conexión
        connected = bool(telemetry)
        status_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        status_text = "Conectado" if connected else "Sin conexion"
        info_lines.append((f"Estado: {status_text}", status_color, scale_text, 2))

        # Separador
        info_lines.append(("", COLOR_WHITE, scale_text, 1))

        # Sección Controles
        info_lines.append(("Controles", COLOR_YELLOW, scale_section, 2))
        info_lines.append(("[R] Iniciar REC", COLOR_WHITE, scale_text, 1))
        info_lines.append(("[E] Detener REC", COLOR_WHITE, scale_text, 1))
        info_lines.append(("[Q/ESC] Salir", COLOR_WHITE, scale_text, 1))

        # Dibujar elementos con espaciado vertical cómodo
        y = 55
        line_spacing = 42

        for text, color, scale, thickness in info_lines:
            if text == "__separator__":
                cv2.line(panel, (20, y), (PANEL_WIDTH - 20, y), COLOR_GRAY, 2)
                y += 30
            elif text == "":
                y += 15
            else:
                cv2.putText(panel, text, (25, y), self.font, scale, color, thickness, cv2.LINE_AA)
                y += line_spacing

        # Indicador visual de estado (círculo)
        indicator_y = y - line_spacing + 10
        indicator_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        cv2.circle(panel, (PANEL_WIDTH - 40, indicator_y - 8), 10, indicator_color, -1)

        return panel

    def draw_hud(
        self,
        img: np.ndarray,
        title: str,
        title_color: Tuple[int, int, int],
        fps: float,
        frame_id: Optional[int],
        timestamp_ns: Optional[int],
    ) -> None:
        """Dibuja el título y HUD dinámico sobre un cuadrante."""
        h, w = img.shape[:2]

        # Título en esquina superior izquierda (proporcional a resolución)
        title_scale = 1.0 if w >= 1280 else 0.8
        cv2.putText(img, title, (20, 45), self.font, title_scale, title_color, 2, cv2.LINE_AA)

        # Información técnica al pie del cuadrante (dinámico según altura de imagen)
        ts_str = formatear_timestamp_ns(timestamp_ns)
        fid_str = f"FID: {frame_id}" if frame_id is not None else "FID: ---"
        fps_str = f"FPS: {fps:.1f}"

        info_txt = f"{fid_str} | {ts_str} | {fps_str}"
        info_scale = 0.62 if w >= 1280 else 0.45

        # Posicionar dinámicamente a 25px del borde inferior
        cv2.putText(img, info_txt, (20, h - 25), self.font, info_scale, (220, 220, 220), 1, cv2.LINE_AA)

    def build_mosaic(
        self,
        frames: dict[str, Optional[np.ndarray]],
        stats: dict[str, dict[str, float | int]],
        sync_info: dict[str, Tuple[Optional[int], Optional[int]]],
        telemetry: dict,
    ) -> np.ndarray:
        """
        Construye el mosaico completo a resolución nativa: panel amplio + cuadrícula 2x2.

        Este frame se usa tanto para la grabación como base para la visualización.

        Parameters
        ----------
        frames : dict
            Frames de los 4 canales.
        stats : dict
            Estadísticas por canal.
        sync_info : dict
            Info de sincronización por canal.
        telemetry : dict
            Datos de telemetría del emisor.

        Returns
        -------
        np.ndarray
            Imagen BGR de MOSAIC_WIDTH x MOSAIC_HEIGHT (panel + mosaico).
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

                # Asegurar tamaño correcto
                if img.shape[:2] != (CAMERA_HEIGHT, CAMERA_WIDTH):
                    img = cv2.resize(img, (CAMERA_WIDTH, CAMERA_HEIGHT), interpolation=cv2.INTER_AREA)

            fps = stats.get(ch_key, {}).get('fps', 0.0)
            fid, ts = sync_info.get(ch_key, (None, None))

            self.draw_hud(img, title, color, fps, fid, ts)
            processed[ch_key] = img

        # Mosaico 2x2 de las 4 cámaras
        top = np.hstack((processed['color'], processed['depth']))
        bottom = np.hstack((processed['ir_left'], processed['ir_right']))
        video_grid = np.vstack((top, bottom))

        # Panel de telemetría lateral amplio
        panel = self._create_info_panel(telemetry, video_grid.shape[0])

        # Mosaico completo: panel | cuadrícula
        return np.hstack((panel, video_grid))

    def render(
        self,
        mosaic: np.ndarray,
        recording: bool,
        rec_info: str,
    ) -> None:
        """
        Renderiza el mosaico directamente en la ventana OpenCV.

        Aprovecha la gestión nativa de ventanas de OpenCV2 con WINDOW_GUI_NORMAL
        para asegurar compatibilidad directa entre sistemas Ubuntu.

        Parameters
        ----------
        mosaic : np.ndarray
            Mosaico nativo con panel integrado.
        recording : bool
            True si la grabación está activa.
        rec_info : str
            Texto descriptivo de la grabación.
        """
        display_img = mosaic.copy()
        h, w = display_img.shape[:2]

        # Si se está grabando: indicador visual parpadeante y borde rojo
        if recording:
            cv2.rectangle(display_img, (0, 0), (w - 1, h - 1), COLOR_RED, 4)

            # Círculo rojo parpadeante (alterna cada 0.5s)
            parpadeo = int(time.time() * 2) % 2 == 0
            rec_x = w - 220
            rec_y = 35

            if parpadeo:
                cv2.circle(display_img, (rec_x, rec_y), 10, COLOR_RED, -1)

            cv2.putText(
                display_img, "REC",
                (rec_x + 18, rec_y + 7),
                self.font, 0.75, COLOR_RED, 2, cv2.LINE_AA
            )

            if rec_info:
                cv2.putText(
                    display_img, rec_info,
                    (rec_x - 240, rec_y + 35),
                    self.font, 0.45, COLOR_WHITE, 1, cv2.LINE_AA
                )

        cv2.imshow(self.window_name, display_img)

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
                "Ingrese el nombre para el archivo de grabación MP4:",
                initialvalue=default_name,
                parent=root
            )

            if not name or not name.strip():
                root.destroy()
                return None

            name = name.strip()

            # 2. Pedir carpeta de destino
            directory = filedialog.askdirectory(
                title="Seleccione la carpeta donde guardar el video MP4",
                parent=root
            )

            root.destroy()

            if not directory:
                return None

            return directory, name

        except Exception:
            # Fallback por terminal si no hay GUI Tkinter
            try:
                print("\n--- Configurar Grabación MP4 ---")
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
