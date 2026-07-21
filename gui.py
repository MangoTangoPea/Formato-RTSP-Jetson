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
    Gestor de la interfaz gráfica responsive del Receptor.

    Construye el mosaico a resolución nativa (1540x960) para grabación
    y lo escala proporcionalmente al tamaño de la ventana para visualización.

    Parameters
    ----------
    window_name : str
        Nombre de la ventana OpenCV.
    """

    # Resolución nativa del mosaico completo (panel + 4 cámaras)
    NATIVE_W: int = MOSAIC_WIDTH    # 1540
    NATIVE_H: int = MOSAIC_HEIGHT   # 960
    BAR_HEIGHT_NATIVE: int = 25     # Barra de controles en resolución nativa

    def __init__(self, window_name: str = "Receptor RTP - RealSense D435") -> None:
        self.window_name = window_name
        self.font = cv2.FONT_HERSHEY_SIMPLEX

        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
        cv2.resizeWindow(self.window_name, self.NATIVE_W, self.NATIVE_H + self.BAR_HEIGHT_NATIVE)

    def _create_info_panel(
        self,
        telemetry: dict,
        height: int,
    ) -> np.ndarray:
        """
        Dibuja el panel lateral izquierdo con información de telemetría.

        Replica el diseño de realsense_monitor_jetson.py con los datos
        de la Jetson transmitidos por el emisor.

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
        panel = np.zeros((height, PANEL_WIDTH, 3), dtype=np.uint8)

        # Extraer datos de telemetría (con valores por defecto)
        date_str = telemetry.get('date_str', '--/--/----')
        time_str = telemetry.get('time_str', '--:--:--')
        resolution = telemetry.get('resolution', '---x---')
        fps_config = telemetry.get('fps_config', '--')
        asic_temp = telemetry.get('asic_temp')
        jetson_temps = telemetry.get('jetson_temps', {})

        # Construir líneas de información
        info_lines: list[tuple[str, tuple[int, int, int], float, int]] = []

        # Título (estilo especial)
        info_lines.append(("Intel RealSense D435", COLOR_YELLOW, 0.60, 2))
        info_lines.append(("__separator__", COLOR_GRAY, 0, 0))

        # Información general
        info_lines.append((f"Fecha   {date_str}", COLOR_WHITE, 0.48, 1))
        info_lines.append((f"Hora    {time_str}", COLOR_WHITE, 0.48, 1))
        info_lines.append((f"Resol.  {resolution}", COLOR_WHITE, 0.48, 1))
        info_lines.append((f"Config. {fps_config} FPS", COLOR_WHITE, 0.48, 1))

        # Temperatura ASIC
        if asic_temp is not None:
            info_lines.append((f"ASIC    {asic_temp:.1f} C", COLOR_WHITE, 0.48, 1))

        # Separador
        info_lines.append(("", COLOR_WHITE, 0.48, 1))

        # Sección Jetson
        info_lines.append(("Jetson", COLOR_YELLOW, 0.55, 2))

        has_jetson_data = False
        for label in ['CPU', 'GPU', 'SOC', 'Board']:
            temp = jetson_temps.get(label)
            if temp is not None:
                info_lines.append((f"{label:<7} {temp:.1f} C", COLOR_WHITE, 0.48, 1))
                has_jetson_data = True

        if not has_jetson_data:
            info_lines.append(("Sin datos", (100, 100, 100), 0.45, 1))

        # Separador
        info_lines.append(("", COLOR_WHITE, 0.48, 1))

        # Estado de conexión
        connected = bool(telemetry)
        status_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        status_text = "Conectado" if connected else "Sin conexion"
        info_lines.append((f"Estado: {status_text}", status_color, 0.48, 1))

        # Dibujar
        y = 30
        for text, color, scale, thickness in info_lines:
            if text == "__separator__":
                cv2.line(panel, (10, y), (PANEL_WIDTH - 15, y), COLOR_GRAY, 1)
                y += 20
            elif text == "":
                y += 10
            else:
                cv2.putText(panel, text, (10, y), self.font, scale, color, thickness, cv2.LINE_AA)
                y += 28

        # Indicador visual de estado (círculo)
        indicator_y = y + 5
        indicator_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        cv2.circle(panel, (PANEL_WIDTH - 25, indicator_y - 5), 6, indicator_color, -1)

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
        """Dibuja el título y HUD sobre un cuadrante."""
        # Título en esquina superior izquierda
        cv2.putText(img, title, (15, 35), self.font, 0.9, title_color, 2, cv2.LINE_AA)

        # Información técnica en overlay semitransparente
        ts_str = formatear_timestamp_ns(timestamp_ns)
        fid_str = f"FID: {frame_id}" if frame_id is not None else "FID: ---"
        fps_str = f"FPS: {fps:.1f}"

        info_txt = f"{fid_str} | {ts_str} | {fps_str}"
        cv2.putText(img, info_txt, (15, 460), self.font, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    def build_mosaic(
        self,
        frames: dict[str, Optional[np.ndarray]],
        stats: dict[str, dict[str, float | int]],
        sync_info: dict[str, Tuple[Optional[int], Optional[int]]],
        telemetry: dict,
    ) -> np.ndarray:
        """
        Construye el mosaico completo a resolución nativa: panel + cuadrícula 2x2.

        Este frame se usa tanto para la grabación (resolución nativa 1540x960)
        como base para la visualización (se escala después).

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
            Imagen BGR de 1540x960 (panel + mosaico).
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

        # Mosaico 2x2 de las 4 cámaras (1280x960)
        top = np.hstack((processed['color'], processed['depth']))
        bottom = np.hstack((processed['ir_left'], processed['ir_right']))
        video_grid = np.vstack((top, bottom))

        # Panel de telemetría lateral (260x960)
        panel = self._create_info_panel(telemetry, video_grid.shape[0])

        # Mosaico completo: panel | cuadrícula (1540x960)
        return np.hstack((panel, video_grid))

    def render(
        self,
        mosaic: np.ndarray,
        recording: bool,
        rec_info: str,
    ) -> None:
        """
        Renderiza el mosaico en pantalla con escalado responsive.

        El mosaico nativo (1540x960) se escala al tamaño de la ventana
        con interpolación de alta calidad, sin espacios blancos.

        Parameters
        ----------
        mosaic : np.ndarray
            Mosaico nativo de 1540x960 con panel integrado.
        recording : bool
            True si la grabación está activa.
        rec_info : str
            Texto descriptivo de la grabación.
        """
        # Obtener tamaño actual de la ventana
        try:
            rect = cv2.getWindowImageRect(self.window_name)
            win_w, win_h = rect[2], rect[3]
        except cv2.error:
            win_w, win_h = self.NATIVE_W, self.NATIVE_H + self.BAR_HEIGHT_NATIVE

        if win_w <= 0 or win_h <= 0:
            win_w, win_h = self.NATIVE_W, self.NATIVE_H + self.BAR_HEIGHT_NATIVE

        # Calcular factor de escala para la barra de controles
        bar_h_scaled = max(20, int(self.BAR_HEIGHT_NATIVE * (win_h / (self.NATIVE_H + self.BAR_HEIGHT_NATIVE))))

        # Espacio disponible para el mosaico (ventana menos barra)
        avail_h = win_h - bar_h_scaled
        avail_w = win_w

        if avail_h <= 0:
            avail_h = win_h
            bar_h_scaled = 0

        # Escalar mosaico manteniendo relación de aspecto y llenando todo el espacio
        src_h, src_w = mosaic.shape[:2]
        scale_w = avail_w / src_w
        scale_h = avail_h / src_h
        scale = min(scale_w, scale_h)

        new_w = int(src_w * scale)
        new_h = int(src_h * scale)

        # Elegir interpolación según dirección (INTER_CUBIC para máxima nitidez al ampliar)
        if scale > 1.0:
            interp = cv2.INTER_CUBIC
        else:
            interp = cv2.INTER_AREA

        display_mosaic = cv2.resize(mosaic, (new_w, new_h), interpolation=interp)

        # Crear canvas del tamaño exacto de la ventana (fondo negro, sin espacios blancos)
        canvas = np.zeros((win_h, win_w, 3), dtype=np.uint8)

        # Centrar el mosaico escalado en el canvas
        offset_x = (avail_w - new_w) // 2
        offset_y = (avail_h - new_h) // 2

        canvas[offset_y:offset_y + new_h, offset_x:offset_x + new_w] = display_mosaic

        # Factor de escala para textos
        text_scale = max(0.4, scale)

        # Si se está grabando: indicador visual parpadeante y borde rojo
        if recording:
            # Borde rojo alrededor del mosaico
            cv2.rectangle(
                canvas,
                (offset_x, offset_y),
                (offset_x + new_w - 1, offset_y + new_h - 1),
                COLOR_RED, max(2, int(4 * scale))
            )

            # Círculo rojo parpadeante (alterna cada 0.5s)
            parpadeo = int(time.time() * 2) % 2 == 0
            rec_x = offset_x + new_w - int(180 * scale)
            rec_y = offset_y + int(30 * scale)

            if parpadeo:
                cv2.circle(canvas, (rec_x, rec_y), max(5, int(10 * scale)), COLOR_RED, -1)

            cv2.putText(
                canvas, "REC",
                (rec_x + int(18 * scale), rec_y + int(7 * scale)),
                self.font, 0.75 * text_scale, COLOR_RED,
                max(1, int(2 * text_scale)), cv2.LINE_AA
            )

            if rec_info:
                cv2.putText(
                    canvas, rec_info,
                    (rec_x - int(220 * scale), rec_y + int(35 * scale)),
                    self.font, 0.45 * text_scale, COLOR_WHITE,
                    max(1, int(1 * text_scale)), cv2.LINE_AA
                )

        # Barra de estado inferior
        if bar_h_scaled > 0:
            bar_y = win_h - bar_h_scaled
            controles_txt = "Controles: [R] Iniciar Grabacion  |  [E] Detener Grabacion  |  [Q / ESC] Salir"
            font_scale_bar = max(0.35, 0.45 * text_scale)
            cv2.putText(
                canvas, controles_txt,
                (int(15 * scale), bar_y + int(bar_h_scaled * 0.7)),
                self.font, font_scale_bar, COLOR_YELLOW,
                max(1, int(1 * text_scale)), cv2.LINE_AA
            )

        cv2.imshow(self.window_name, canvas)

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
