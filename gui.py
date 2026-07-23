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
    CAMERA_WIDTH, CAMERA_HEIGHT, PANEL_HEIGHT,
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
        self._last_valid_mosaic: Optional[np.ndarray] = None

        # cv2.WINDOW_GUI_NORMAL elimina la barra de herramientas y botones superiores de Qt/OpenCV
        cv2.namedWindow(
            self.window_name,
            cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_NORMAL
        )
        cv2.resizeWindow(self.window_name, self.NATIVE_W, self.NATIVE_H)

    def _create_info_panel(
        self,
        telemetry: dict,
        width: int,
    ) -> np.ndarray:
        """
        Dibuja el panel superior horizontal (rectángulo) con información de telemetría y controles.

        Organiza la telemetría en 4 columnas perfectamente alineadas sobre las cámaras
        con tipografía nítida de alta legibilidad e indicadores visuales.

        Parameters
        ----------
        telemetry : dict
            Datos de telemetría del emisor.
        width : int
            Ancho completo del mosaico (coincide con el ancho de las cámaras, p.ej. 2560px).

        Returns
        -------
        np.ndarray
            Imagen BGR de width x PANEL_HEIGHT.
        """
        panel = np.full((PANEL_HEIGHT, width, 3), (25, 25, 25), dtype=np.uint8)

        # Extraer datos de telemetría
        date_str = telemetry.get('date_str', '--/--/----')
        time_str = telemetry.get('time_str', '--:--:--')
        resolution = telemetry.get('resolution', '1280x720')
        fps_config = telemetry.get('fps_config', '30')
        asic_temp = telemetry.get('asic_temp')
        jetson_temps = telemetry.get('jetson_temps', {})
        connected = bool(telemetry)

        # Fuentes
        font_bold = cv2.FONT_HERSHEY_DUPLEX
        font_regular = cv2.FONT_HERSHEY_SIMPLEX

        # ---------------------------------------------------------------------
        # COLUMNA 1: DISPOSITIVO Y ESTADO (x = 30)
        # ---------------------------------------------------------------------
        cv2.putText(panel, "Intel RealSense D435", (30, 42), font_bold, 0.85, COLOR_YELLOW, 2, cv2.LINE_AA)

        # Estado de conexión
        status_color = COLOR_CONNECTED if connected else COLOR_DISCONNECTED
        status_text = "CONECTADO" if connected else "SIN CONEXION"
        cv2.circle(panel, (42, 80), 9, status_color, -1, cv2.LINE_AA)
        cv2.putText(panel, status_text, (62, 86), font_bold, 0.65, status_color, 2, cv2.LINE_AA)

        # Separador vertical 1
        cv2.line(panel, (520, 15), (520, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # ---------------------------------------------------------------------
        # COLUMNA 2: FECHA, HORA Y RESOLUCIÓN (x = 550)
        # ---------------------------------------------------------------------
        cv2.putText(panel, f"Fecha: {date_str}   |   Hora: {time_str}", (550, 42), font_regular, 0.68, COLOR_WHITE, 2, cv2.LINE_AA)
        cv2.putText(panel, f"Resol: {resolution}   |   Config: {fps_config} FPS", (550, 84), font_regular, 0.68, COLOR_WHITE, 2, cv2.LINE_AA)

        # Separador vertical 2
        cv2.line(panel, (1180, 15), (1180, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # ---------------------------------------------------------------------
        # COLUMNA 3: TELEMETRÍA HARDWARE JETSON (x = 1210)
        # ---------------------------------------------------------------------
        asic_str = f"{asic_temp:.1f} C" if asic_temp is not None else "-- C"
        power_watts = telemetry.get('power_watts')
        jetson_powers = telemetry.get('jetson_powers', {})

        if power_watts is not None:
            power_str = f"Potencia: {power_watts:.2f} W"
        elif jetson_powers:
            tot = sum(v for v in jetson_powers.values() if v is not None)
            power_str = f"Potencia: {tot:.2f} W"
        else:
            power_str = "Potencia: -- W"

        cv2.putText(panel, f"ASIC: {asic_str}   |   {power_str}", (1210, 42), font_regular, 0.68, COLOR_YELLOW, 2, cv2.LINE_AA)

        # Temperaturas Jetson (CPU, GPU, SOC)
        jetson_parts = []
        expected_labels = ['CPU', 'GPU', 'SOC']

        for label in expected_labels:
            val = jetson_temps.get(label)
            if val is not None:
                jetson_parts.append(f"{label}: {val:.1f}C")

        # Incluir cualquier otra categoría adicional de temperatura detectada si existe
        for label, val in jetson_temps.items():
            if label not in expected_labels and label != 'Board' and val is not None:
                jetson_parts.append(f"{label}: {val:.1f}C")

        jetson_str = " | ".join(jetson_parts) if jetson_parts else "Jetson: Esperando telemetria..."
        cv2.putText(panel, jetson_str, (1210, 84), font_regular, 0.62, COLOR_WHITE, 2, cv2.LINE_AA)

        # Separador vertical 3
        cv2.line(panel, (1880, 15), (1880, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # ---------------------------------------------------------------------
        # COLUMNA 4: ATAJOS DE TECLADO / CONTROLES (x = 1910)
        # ---------------------------------------------------------------------
        cv2.putText(panel, "CONTROLES:", (1910, 40), font_bold, 0.68, COLOR_YELLOW, 2, cv2.LINE_AA)
        cv2.putText(panel, "[R] Grabar   [E] Detener   [D] Dashboard   [Q] Salir", (1910, 84), font_bold, 0.60, COLOR_WHITE, 2, cv2.LINE_AA)

        # Borde inferior del panel
        cv2.line(panel, (0, PANEL_HEIGHT - 1), (width, PANEL_HEIGHT - 1), COLOR_GRAY, 2)

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
        """
        Dibuja el título y HUD dinámico sobre cada cámara con badge oscuro de contraste para máxima legibilidad.
        """
        h, w = img.shape[:2]
        font_title = cv2.FONT_HERSHEY_DUPLEX
        font_info = cv2.FONT_HERSHEY_SIMPLEX

        # --- 1. TÍTULO DE CÁMARA (Esquina Superior Izquierda) ---
        title_scale = 1.0 if w >= 1280 else 0.8
        title_thickness = 2
        (title_w, title_h), baseline = cv2.getTextSize(title, font_title, title_scale, title_thickness)

        pad_x, pad_y = 12, 10
        top_left = (15, 12)
        bottom_right = (15 + title_w + 2 * pad_x, 12 + title_h + 2 * pad_y)

        # Fondo oscuro y borde del badge de título
        cv2.rectangle(img, top_left, bottom_right, (15, 15, 15), -1)
        cv2.rectangle(img, top_left, bottom_right, (60, 60, 60), 1)

        # Texto del título
        cv2.putText(
            img, title, (15 + pad_x, 12 + pad_y + title_h),
            font_title, title_scale, title_color, title_thickness, cv2.LINE_AA
        )

        # --- 2. INFORMACIÓN TÉCNICA (Pie del cuadrante: FID | TS | FPS) ---
        ts_str = formatear_timestamp_ns(timestamp_ns)
        fid_str = f"FID: {frame_id}" if frame_id is not None else "FID: ---"
        fps_str = f"FPS: {fps:.1f}"
        info_txt = f"{fid_str}   |   {ts_str}   |   {fps_str}"

        info_scale = 0.62 if w >= 1280 else 0.45
        info_thickness = 2
        (info_w, info_h), baseline_info = cv2.getTextSize(info_txt, font_info, info_scale, info_thickness)

        info_pad_x, info_pad_y = 12, 8
        info_top_left = (15, h - info_h - 2 * info_pad_y - 12)
        info_bottom_right = (15 + info_w + 2 * info_pad_x, h - 12)

        # Fondo oscuro y borde del badge de HUD
        cv2.rectangle(img, info_top_left, info_bottom_right, (15, 15, 15), -1)
        cv2.rectangle(img, info_top_left, info_bottom_right, (60, 60, 60), 1)

        # Texto HUD al pie
        cv2.putText(
            img, info_txt, (15 + info_pad_x, h - 12 - info_pad_y),
            font_info, info_scale, (240, 240, 240), info_thickness, cv2.LINE_AA
        )

    def build_mosaic(
        self,
        frames: dict[str, Optional[np.ndarray]],
        stats: dict[str, dict[str, float | int]],
        sync_info: dict[str, Tuple[Optional[int], Optional[int]]],
        telemetry: dict,
    ) -> np.ndarray:
        """
        Construye el mosaico completo a resolución nativa: panel superior (rectángulo) + cuadrícula 2x2.

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
            Imagen BGR de MOSAIC_WIDTH x MOSAIC_HEIGHT (panel superior + mosaico 2x2).
        """
        processed: dict[str, np.ndarray] = {}
        all_present = all(frames.get(k) is not None for k in ['color', 'depth', 'ir_left', 'ir_right'])

        for ch_key in ['color', 'depth', 'ir_left', 'ir_right']:
            f = frames.get(ch_key)
            title, color = TITULOS_CANALES[ch_key]

            if f is None:
                img = crear_placeholder(CAMERA_WIDTH, CAMERA_HEIGHT, f"Esperando {title}...")
            else:
                img = f.copy()
                if img.ndim == 2:
                    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

                # Limpieza estética visual: retocar filas 0..1 sobre la franja esteganográfica para video e imagen 100% impecables
                if img.shape[0] > 2 and img.shape[1] >= 256:
                    img[0:2, 0:256] = img[2:3, 0:256]

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

        # Panel de telemetría superior (rectángulo horizontal completo)
        panel = self._create_info_panel(telemetry, video_grid.shape[1])

        # Mosaico completo: panel (arriba) + cuadrícula 2x2 (abajo)
        mosaic = np.vstack((panel, video_grid))

        if all_present:
            self._last_valid_mosaic = mosaic.copy()
        elif self._last_valid_mosaic is not None:
            # Si un frame fue borrado por desincronía, mostrar suavemente el último mosaico 100% síncrono
            return self._last_valid_mosaic

        return mosaic

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
            'start_rec', 'stop_rec', 'toggle_dashboard', 'save_dashboard', 'prev_date', 'quit' o None.
        """
        key = cv2.waitKey(10) & 0xFF
        if key in (ord('r'), ord('R')):
            return "start_rec"
        elif key in (ord('e'), ord('E')):
            return "stop_rec"
        elif key in (ord('d'), ord('D')):
            return "toggle_dashboard"
        elif key in (ord('s'), ord('S')):
            return "save_dashboard"
        elif key in (ord('a'), ord('A')):
            return "prev_date"
        elif key in (ord('q'), ord('Q'), 27):  # ESC
            return "quit"
        return None

    def ask_recording_tag(self, base_dir: str = "./grabaciones") -> Optional[Tuple[str, str, str]]:
        """
        Solicita al usuario una etiqueta previa al inicio de la grabación.

        Genera automáticamente:
        1. Carpeta con el nombre de la etiqueta: base_dir/<etiqueta>
        2. Nombre del archivo prefijado por la etiqueta: <etiqueta>_<timestamp>.mkv

        Parameters
        ----------
        base_dir : str
            Directorio base donde se almacenan las grabaciones (por defecto './grabaciones').

        Returns
        -------
        Tuple[str, str, str] | None
            (directorio_destino, nombre_grabacion, etiqueta) o None si el usuario canceló.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        import os
        import re

        tag: Optional[str] = None
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()

            dialog = tk.Toplevel(root)
            dialog.title("Guardar Grabación")

            # Ventana rectangular compacta y centrada (360x160)
            window_w, window_h = 360, 160
            scr_w = dialog.winfo_screenwidth()
            scr_h = dialog.winfo_screenheight()
            x = int((scr_w - window_w) / 2)
            y = int((scr_h - window_h) / 2)
            dialog.geometry(f"{window_w}x{window_h}+{x}+{y}")
            dialog.resizable(False, False)
            dialog.attributes('-topmost', True)

            dialog_res = {"tag": None}

            frame = tk.Frame(dialog, padx=15, pady=12)
            frame.pack(fill=tk.BOTH, expand=True)

            label_msg = tk.Label(
                frame,
                text="Ingrese la etiqueta para organizar la grabación:\n(Ejemplos: C, IA, II, IR)",
                font=("TkDefaultFont", 9),
                anchor="w",
                justify=tk.LEFT
            )
            label_msg.pack(fill=tk.X, pady=(0, 8))

            entry = tk.Entry(
                frame,
                font=("TkDefaultFont", 10),
                width=35
            )
            entry.pack(fill=tk.X, pady=(0, 12))
            entry.focus_set()

            def on_confirm():
                dialog_res["tag"] = entry.get()
                dialog.destroy()
                root.destroy()

            def on_cancel():
                dialog_res["tag"] = None
                dialog.destroy()
                root.destroy()

            entry.bind("<Return>", lambda e: on_confirm())
            entry.bind("<Escape>", lambda e: on_cancel())
            dialog.protocol("WM_DELETE_WINDOW", on_cancel)

            btn_frame = tk.Frame(frame)
            btn_frame.pack(anchor=tk.E)

            btn_ok = tk.Button(
                btn_frame,
                text="OK",
                width=8,
                command=on_confirm
            )
            btn_ok.pack(side=tk.LEFT, padx=(0, 6))

            btn_cancel = tk.Button(
                btn_frame,
                text="Cancelar",
                width=8,
                command=on_cancel
            )
            btn_cancel.pack(side=tk.LEFT)

            dialog.grab_set()
            root.mainloop()

            tag = dialog_res["tag"]
        except Exception:
            # Fallback por terminal si no hay GUI Tkinter
            try:
                print("\n--- Iniciar Grabación ---")
                tag_in = input("Ingrese etiqueta para la grabación [general]: ").strip()
                tag = tag_in if tag_in else "general"
            except Exception:
                tag = None

        if tag is None:
            return None

        tag_clean = tag.strip()
        # Reemplazar espacios y caracteres no válidos para rutas por "_"
        tag_clean = re.sub(r'[\s/\\:\*\?"<>\|]+', '_', tag_clean)
        tag_clean = tag_clean.strip('_')

        if not tag_clean:
            tag_clean = "general"

        target_dir = os.path.abspath(os.path.join(base_dir, tag_clean))
        record_name = f"{tag_clean}_{timestamp}"

        return target_dir, record_name, tag_clean

    def destroy(self) -> None:
        """Cierra todas las ventanas de OpenCV."""
        cv2.destroyAllWindows()
