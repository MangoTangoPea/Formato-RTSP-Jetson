#!/usr/bin/env python3
"""
Visualizador de Grabaciones Multicanal DB3 / MKV (RGB, Depth Z16 16-bit, IR Left, IR Right).

Permite reproducir, navegar e inspeccionar grabaciones .db3 (base de datos SQLite3 con canal
de profundidad Z16 nativo en 16 bits sin pérdidas) y .mkv (legacy) con dos modos de visualización:
1. Modo "Por Separado": Disposición en panel de telemetría + cuadrícula 2x2 sincronizada.
2. Modo "Superpuestos": Fusión de los 4 canales con transparencia regulable.

Incluye inspección milimétrica de distancia en tiempo real con el mouse y pines de medición fijos.
"""

import os
import sys
import glob
import time
import json
import zlib
import sqlite3
from typing import Optional, Tuple, List, Dict, Any, Union

import cv2
import numpy as np

try:
    from config import CAMERA_WIDTH, CAMERA_HEIGHT, PANEL_HEIGHT, MOSAIC_WIDTH, MOSAIC_HEIGHT
    from utils import formatear_timestamp_ns
except ImportError:
    CAMERA_WIDTH = 1280
    CAMERA_HEIGHT = 720
    PANEL_HEIGHT = 120
    MOSAIC_WIDTH = 2560
    MOSAIC_HEIGHT = 1560

    def formatear_timestamp_ns(timestamp_ns: Optional[int]) -> str:
        if timestamp_ns is None or timestamp_ns == 0:
            return "--:--:--.---"
        try:
            import datetime
            dt = datetime.datetime.fromtimestamp(timestamp_ns / 1e9)
            ms = int((timestamp_ns % 1_000_000_000) / 1_000_000)
            return dt.strftime("%H:%M:%S") + f".{ms:03d}"
        except Exception:
            return "--:--:--.---"


# Colores BGR
COLOR_GREEN = (0, 255, 0)
COLOR_WHITE = (255, 255, 255)
COLOR_YELLOW = (0, 255, 255)
COLOR_CYAN = (255, 255, 0)
COLOR_RED = (0, 0, 255)
COLOR_GRAY = (70, 70, 70)
COLOR_BG_DARK = (20, 20, 20)


class DB3Reader:
    """
    Lector de alta velocidad para grabaciones en base de datos SQLite3 (.db3).
    """

    def __init__(self, db3_path: str) -> None:
        self.db3_path = db3_path
        if not os.path.exists(db3_path):
            raise FileNotFoundError(f"No se encontró el archivo: {db3_path}")

        self.conn = sqlite3.connect(f"file:{os.path.abspath(db3_path)}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()

        # Cargar metadatos
        self.metadata: Dict[str, str] = {}
        try:
            self.cursor.execute("SELECT key, value FROM metadata;")
            for row in self.cursor.fetchall():
                self.metadata[row["key"]] = row["value"]
        except sqlite3.Error:
            pass

        self.width = int(self.metadata.get("width", CAMERA_WIDTH))
        self.height = int(self.metadata.get("height", CAMERA_HEIGHT))
        self.fps = float(self.metadata.get("fps", 30.0))

        # Contar frames disponibles
        self.cursor.execute("SELECT COUNT(*) FROM frames;")
        self.total_frames = self.cursor.fetchone()[0]

        if self.total_frames == 0:
            raise RuntimeError(f"La base de datos {db3_path} no contiene frames grabados.")

    def get_frame(self, index: int) -> Dict[str, Any]:
        """
        Recupera un frame por su índice (0 .. total_frames - 1).
        """
        index = max(0, min(self.total_frames - 1, index))
        self.cursor.execute("""
            SELECT frame_id, timestamp_ns, datetime_str, color, depth_z16, ir_left, ir_right, telemetry
            FROM frames
            ORDER BY frame_id ASC
            LIMIT 1 OFFSET ?;
        """, (index,))
        row = self.cursor.fetchone()
        if not row:
            return {}

        fid = row["frame_id"]
        ts_ns = row["timestamp_ns"]
        dt_str = row["datetime_str"]

        # 1. Decodificar Color
        color_blob = row["color"]
        if color_blob:
            color = cv2.imdecode(np.frombuffer(color_blob, dtype=np.uint8), cv2.IMREAD_COLOR)
        else:
            color = np.full((self.height, self.width, 3), COLOR_BG_DARK, dtype=np.uint8)

        # 2. Decodificar Profundidad Z16 (uint16 en mm 100% lossless)
        depth_blob = row["depth_z16"]
        try:
            depth_bytes = zlib.decompress(depth_blob)
        except Exception:
            depth_bytes = depth_blob  # fallback si no fue comprimido

        depth_z16 = np.frombuffer(depth_bytes, dtype=np.uint16).reshape((self.height, self.width))

        # 3. Decodificar IR Left
        ir_l_blob = row["ir_left"]
        if ir_l_blob:
            ir_left = cv2.imdecode(np.frombuffer(ir_l_blob, dtype=np.uint8), cv2.IMREAD_COLOR)
        else:
            ir_left = np.full((self.height, self.width, 3), COLOR_BG_DARK, dtype=np.uint8)

        # 4. Decodificar IR Right
        ir_r_blob = row["ir_right"]
        if ir_r_blob:
            ir_right = cv2.imdecode(np.frombuffer(ir_r_blob, dtype=np.uint8), cv2.IMREAD_COLOR)
        else:
            ir_right = np.full((self.height, self.width, 3), COLOR_BG_DARK, dtype=np.uint8)

        # 5. Telemetría
        telem_str = row["telemetry"]
        telemetry = {}
        if telem_str:
            try:
                telemetry = json.loads(telem_str)
            except Exception:
                pass

        return {
            "frame_id": fid,
            "timestamp_ns": ts_ns,
            "datetime_str": dt_str,
            "color": color,
            "depth_z16": depth_z16,
            "ir_left": ir_left,
            "ir_right": ir_right,
            "telemetry": telemetry,
        }

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


class VisualizerPlayer:
    """
    Reproductor y visualizador interactivo para grabaciones .db3 (y .mkv legacy).
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.is_db3 = file_path.lower().endswith(".db3")

        if self.is_db3:
            self.db_reader = DB3Reader(file_path)
            self.total_frames = self.db_reader.total_frames
            self.fps = self.db_reader.fps
            self.width = self.db_reader.width
            self.height = self.db_reader.height
            self.cap = None
        else:
            self.db_reader = None
            self.cap = cv2.VideoCapture(file_path)
            if not self.cap.isOpened():
                raise RuntimeError(f"No se pudo abrir el video MKV: {file_path}")
            self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.width = CAMERA_WIDTH
            self.height = CAMERA_HEIGHT

        # Estado del reproductor
        self.current_frame_idx = 0
        self.paused = False
        self.mode = "separado"  # 'separado' o 'superpuesto'

        # Transparencias en modo superpuesto
        self.depth_alpha = 0.55
        self.ir_alpha = 0.25

        # Mouse e inspección de distancia
        self.mouse_pos: Optional[Tuple[int, int]] = None
        self.pinned_points: List[Tuple[int, int]] = []

        # Ventana OpenCV
        self.window_name = f"Visualizador Grabación ({'DB3' if self.is_db3 else 'MKV'}) - {os.path.basename(file_path)}"
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
        cv2.resizeWindow(self.window_name, 1280, 800)
        cv2.setMouseCallback(self.window_name, self._on_mouse)

        # Trackbar para navegación temporal precisa
        cv2.createTrackbar("Frame", self.window_name, 0, max(1, self.total_frames - 1), self._on_trackbar)

    def _on_trackbar(self, val: int) -> None:
        if val != self.current_frame_idx:
            self.current_frame_idx = val

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: None) -> None:
        self.mouse_pos = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self.pinned_points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.pinned_points.clear()

    def _draw_hud(
        self,
        img: np.ndarray,
        title: str,
        title_color: Tuple[int, int, int],
        frame_id: Optional[int],
        timestamp_ns: Optional[int],
    ) -> None:
        """Dibuja título y HUD de frame_id y timestamp sobre cada cuadrante."""
        h, w = img.shape[:2]
        font_title = cv2.FONT_HERSHEY_DUPLEX
        font_info = cv2.FONT_HERSHEY_SIMPLEX

        # Título
        (tw, th), _ = cv2.getTextSize(title, font_title, 0.85, 2)
        cv2.rectangle(img, (15, 12), (15 + tw + 20, 12 + th + 18), (15, 15, 15), -1)
        cv2.rectangle(img, (15, 12), (15 + tw + 20, 12 + th + 18), (60, 60, 60), 1)
        cv2.putText(img, title, (25, 12 + th + 9), font_title, 0.85, title_color, 2, cv2.LINE_AA)

        # Información inferior
        ts_str = formatear_timestamp_ns(timestamp_ns)
        fid_str = f"FID: {frame_id}" if frame_id is not None else "FID: ---"
        info_txt = f"{fid_str}   |   {ts_str}"
        (iw, ih), _ = cv2.getTextSize(info_txt, font_info, 0.52, 1)

        cv2.rectangle(img, (15, h - ih - 22), (15 + iw + 20, h - 10), (15, 15, 15), -1)
        cv2.rectangle(img, (15, h - ih - 22), (15 + iw + 20, h - 10), (60, 60, 60), 1)
        cv2.putText(img, info_txt, (25, h - 14), font_info, 0.52, (240, 240, 240), 1, cv2.LINE_AA)

    def _create_info_panel(self, telemetry: dict, width: int, fid: int, ts_ns: int) -> np.ndarray:
        """Genera el panel superior horizontal con la telemetría del emisor grabada."""
        panel = np.full((PANEL_HEIGHT, width, 3), (25, 25, 25), dtype=np.uint8)

        date_str = telemetry.get('date_str', '--/--/----')
        time_str = telemetry.get('time_str', '--:--:--')
        resolution = telemetry.get('resolution', f'{self.width}x{self.height}')
        fps_config = telemetry.get('fps_config', '30')
        asic_temp = telemetry.get('asic_temp')
        jetson_temps = telemetry.get('jetson_temps', {})
        power_watts = telemetry.get('power_watts')

        font_bold = cv2.FONT_HERSHEY_DUPLEX
        font_regular = cv2.FONT_HERSHEY_SIMPLEX

        # Columna 1: Dispositivo y Formato
        cv2.putText(panel, "Intel RealSense D435", (30, 42), font_bold, 0.85, COLOR_YELLOW, 2, cv2.LINE_AA)
        fmt_label = "DB3 (Z16 16-bit Lossless)" if self.is_db3 else "MKV (Video Stream)"
        cv2.putText(panel, f"Formato: {fmt_label}", (30, 84), font_bold, 0.60, COLOR_GREEN, 2, cv2.LINE_AA)
        cv2.line(panel, (520, 15), (520, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # Columna 2: Fecha, Hora y Sincronización
        cv2.putText(panel, f"Fecha: {date_str}   |   Hora: {time_str}", (550, 42), font_regular, 0.68, COLOR_WHITE, 2, cv2.LINE_AA)
        cv2.putText(panel, f"Resol: {resolution}   |   Config: {fps_config} FPS", (550, 84), font_regular, 0.68, COLOR_WHITE, 2, cv2.LINE_AA)
        cv2.line(panel, (1180, 15), (1180, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # Columna 3: Telemetría Hardware Jetson
        asic_str = f"{asic_temp:.1f} C" if asic_temp is not None else "-- C"
        p_str = f"{power_watts:.2f} W" if power_watts is not None else "-- W"
        cv2.putText(panel, f"ASIC: {asic_str}   |   Potencia: {p_str}", (1210, 42), font_regular, 0.68, COLOR_YELLOW, 2, cv2.LINE_AA)

        temps_parts = [f"{k}: {v:.1f}C" for k, v in jetson_temps.items() if v is not None]
        temps_str = " | ".join(temps_parts[:4]) if temps_parts else "Jetson: Sin telemetria"
        cv2.putText(panel, temps_str, (1210, 84), font_regular, 0.62, COLOR_WHITE, 2, cv2.LINE_AA)
        cv2.line(panel, (1880, 15), (1880, PANEL_HEIGHT - 15), COLOR_GRAY, 2)

        # Columna 4: Controles de reproducción
        cv2.putText(panel, "CONTROLES:", (1910, 40), font_bold, 0.68, COLOR_YELLOW, 2, cv2.LINE_AA)
        cv2.putText(panel, "[M] Modo   [P / Espacio] Pausa   [<- / ->] Buscar   [Q] Salir", (1910, 84), font_bold, 0.52, COLOR_WHITE, 2, cv2.LINE_AA)

        cv2.line(panel, (0, PANEL_HEIGHT - 1), (width, PANEL_HEIGHT - 1), COLOR_GRAY, 2)
        return panel

    def _draw_depth_legend(self, canvas: np.ndarray, depth_m: np.ndarray) -> None:
        """Dibuja barra de escala de colores JET y estadísticas de profundidad."""
        ch, cw = canvas.shape[:2]
        bar_w, bar_h = 22, 160
        x_bar = cw - 55
        y_bar = 135

        gradient = np.linspace(0, 255, bar_h, dtype=np.uint8).reshape(bar_h, 1)
        grad_jet = cv2.applyColorMap(gradient, cv2.COLORMAP_JET)

        canvas[y_bar:y_bar + bar_h, x_bar:x_bar + bar_w] = grad_jet
        cv2.rectangle(canvas, (x_bar - 1, y_bar - 1), (x_bar + bar_w + 1, y_bar + bar_h + 1), (255, 255, 255), 1)

        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(canvas, "0.0m", (x_bar - 45, y_bar + 12), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "4.2m", (x_bar - 45, y_bar + bar_h // 2 + 4), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, "8.5m", (x_bar - 45, y_bar + bar_h - 2), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

        valid_pixels = np.count_nonzero(depth_m > 0.05)
        total_pixels = depth_m.size
        pct_valid = (valid_pixels / total_pixels) * 100.0
        mean_dist = float(np.mean(depth_m[depth_m > 0.05])) if valid_pixels > 0 else 0.0

        badge_txt = f"PROFUNDIDAD Z16 16-BIT (100% EXACTO) | {pct_valid:.1f}% Retorno | Dist. Media: {mean_dist:.2f}m"
        (bw, bh), _ = cv2.getTextSize(badge_txt, font, 0.48, 1)
        bx = cw - bw - 70
        by = y_bar - 15
        cv2.rectangle(canvas, (bx - 8, by - bh - 6), (bx + bw + 8, by + 4), (15, 15, 15), -1)
        cv2.rectangle(canvas, (bx - 8, by - bh - 6), (bx + bw + 8, by + 4), (0, 255, 0), 1)
        cv2.putText(canvas, badge_txt, (bx, by), font, 0.48, (0, 255, 0), 1, cv2.LINE_AA)

    def render_separado(
        self,
        color: np.ndarray,
        depth_jet: np.ndarray,
        depth_m: np.ndarray,
        ir_left: np.ndarray,
        ir_right: np.ndarray,
        telemetry: dict,
        frame_id: int,
        timestamp_ns: int,
    ) -> np.ndarray:
        """Genera la vista por separado (panel de telemetría + mosaico 2x2)."""
        c_img = color.copy()
        d_img = depth_jet.copy()
        il_img = ir_left.copy()
        ir_img = ir_right.copy()

        self._draw_hud(c_img, "RGB", COLOR_GREEN, frame_id, timestamp_ns)
        self._draw_hud(d_img, "DEPTH (Z16 16-BIT)", COLOR_WHITE, frame_id, timestamp_ns)
        self._draw_hud(il_img, "IR LEFT", COLOR_GREEN, frame_id, timestamp_ns)
        self._draw_hud(ir_img, "IR RIGHT", COLOR_GREEN, frame_id, timestamp_ns)

        top = np.hstack((c_img, d_img))
        bottom = np.hstack((il_img, ir_img))
        video_grid = np.vstack((top, bottom))

        panel = self._create_info_panel(telemetry, video_grid.shape[1], frame_id, timestamp_ns)
        mosaic = np.vstack((panel, video_grid))

        # Leyenda de profundidad
        self._draw_depth_legend(mosaic, depth_m)

        # Pie con indicador de modo
        vh = mosaic.shape[0]
        mode_badge = f" MODO: POR SEPARADO (2x2) | Frame: {self.current_frame_idx + 1}/{self.total_frames} | [M] Cambiar a Superpuesto | [P] Pausa "
        cv2.rectangle(mosaic, (15, vh - 45), (1050, vh - 10), (15, 15, 15), -1)
        cv2.rectangle(mosaic, (15, vh - 45), (1050, vh - 10), (60, 60, 60), 1)
        cv2.putText(mosaic, mode_badge, (25, vh - 22), cv2.FONT_HERSHEY_DUPLEX, 0.55, COLOR_YELLOW, 1, cv2.LINE_AA)

        return mosaic

    def render_superpuesto(
        self,
        color: np.ndarray,
        depth_jet: np.ndarray,
        depth_m: np.ndarray,
        ir_left: np.ndarray,
        ir_right: np.ndarray,
        telemetry: dict,
        frame_id: int,
        timestamp_ns: int,
    ) -> np.ndarray:
        """Fusiona los 4 canales en una única imagen combinada con transparencias configurables."""
        h, w = color.shape[:2]

        fused = color.astype(np.float32)
        depth_f32 = depth_jet.astype(np.float32)
        fused = cv2.addWeighted(fused, 1.0 - self.depth_alpha, depth_f32, self.depth_alpha, 0)

        if self.ir_alpha > 0:
            ir_f32 = ir_left.astype(np.float32)
            fused = cv2.addWeighted(fused, 1.0, ir_f32, self.ir_alpha, 0)

        res = np.clip(fused, 0, 255).astype(np.uint8)

        # Barra superior de control de fusión (60px)
        panel_bar = np.full((60, w, 3), (25, 25, 25), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX

        txt_mode = f"MODO: FUSION SUPERPUESTA | Frame {self.current_frame_idx + 1}/{self.total_frames} | FID: {frame_id}"
        cv2.putText(panel_bar, txt_mode, (20, 25), cv2.FONT_HERSHEY_DUPLEX, 0.65, COLOR_YELLOW, 2, cv2.LINE_AA)

        txt_ctrls = f"Depth Alpha: {self.depth_alpha:.2f} [1/2] | IR Alpha: {self.ir_alpha:.2f} [3/4] | [M] Modo | [P] Pausa"
        cv2.putText(panel_bar, txt_ctrls, (20, 48), font, 0.52, (220, 220, 220), 1, cv2.LINE_AA)

        full_view = np.vstack((panel_bar, res))
        self._draw_depth_legend(full_view, depth_m)

        return full_view

    def map_coords_to_depth(self, x: int, y: int, mode: str, ch: int, cw: int) -> Optional[Tuple[int, int]]:
        """Mapea coordenadas de pantalla a coordenadas de píxel en la matriz Depth (1280x720)."""
        if mode == "separado":
            # Cuadrante RGB (Top-Left)
            if PANEL_HEIGHT <= y < PANEL_HEIGHT + CAMERA_HEIGHT and 0 <= x < CAMERA_WIDTH:
                return (x, y - PANEL_HEIGHT)
            # Cuadrante Depth (Top-Right)
            elif PANEL_HEIGHT <= y < PANEL_HEIGHT + CAMERA_HEIGHT and CAMERA_WIDTH <= x < cw:
                return (x - CAMERA_WIDTH, y - PANEL_HEIGHT)
            # Cuadrante IR Left (Bottom-Left)
            elif PANEL_HEIGHT + CAMERA_HEIGHT <= y < ch and 0 <= x < CAMERA_WIDTH:
                return (x, y - (PANEL_HEIGHT + CAMERA_HEIGHT))
            # Cuadrante IR Right (Bottom-Right)
            elif PANEL_HEIGHT + CAMERA_HEIGHT <= y < ch and CAMERA_WIDTH <= x < cw:
                return (x - CAMERA_WIDTH, y - (PANEL_HEIGHT + CAMERA_HEIGHT))

        elif mode == "superpuesto":
            if 60 <= y < ch and 0 <= x < cw:
                dx = int((x / cw) * CAMERA_WIDTH)
                dy = int(((y - 60) / (ch - 60)) * CAMERA_HEIGHT)
                if 0 <= dx < CAMERA_WIDTH and 0 <= dy < CAMERA_HEIGHT:
                    return (dx, dy)

        return None

    def process_mouse_and_pins(self, canvas: np.ndarray, depth_m: np.ndarray) -> None:
        """Dibuja inspección interactiva con crosshair y marcas de distancia."""
        if depth_m is None:
            return

        ch, cw = canvas.shape[:2]

        # 1. Puntos marcados (Pinned points)
        for pt in self.pinned_points:
            d_coords = self.map_coords_to_depth(pt[0], pt[1], self.mode, ch, cw)
            if d_coords:
                dx, dy = d_coords
                dist = depth_m[dy, dx]
                dist_str = f"{dist:.3f} m ({int(round(dist * 1000))} mm)" if dist > 0.02 else "Sin retorno Depth"

                cv2.circle(canvas, pt, 6, (0, 0, 255), -1, cv2.LINE_AA)
                cv2.circle(canvas, pt, 8, (255, 255, 255), 2, cv2.LINE_AA)

                txt = f" {dist_str} "
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
                cv2.rectangle(canvas, (pt[0] + 10, pt[1] - th - 8), (pt[0] + 10 + tw, pt[1] + 4), (15, 15, 15), -1)
                cv2.rectangle(canvas, (pt[0] + 10, pt[1] - th - 8), (pt[0] + 10 + tw, pt[1] + 4), (0, 255, 255), 1)
                cv2.putText(canvas, txt, (pt[0] + 10, pt[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

        # 2. Inspector dinámico al pasar el cursor (Mouse hover)
        if self.mouse_pos:
            mx, my = self.mouse_pos
            d_coords = self.map_coords_to_depth(mx, my, self.mode, ch, cw)
            if d_coords:
                dx, dy = d_coords
                dist = depth_m[dy, dx]
                dist_str = f"{dist:.3f} m ({int(round(dist * 1000))} mm)" if dist > 0.02 else "Sin retorno Depth"

                cv2.line(canvas, (mx - 12, my), (mx + 12, my), (0, 255, 0), 1, cv2.LINE_AA)
                cv2.line(canvas, (mx, my - 12), (mx, my + 12), (0, 255, 0), 1, cv2.LINE_AA)

                tooltip_txt = f" Distancia Exacta: {dist_str} | (X:{dx}, Y:{dy}) "
                (tw, th), _ = cv2.getTextSize(tooltip_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

                tx = min(mx + 15, cw - tw - 15)
                ty = max(my - 15, th + 15)

                cv2.rectangle(canvas, (tx, ty - th - 6), (tx + tw, ty + 4), (15, 15, 15), -1)
                cv2.rectangle(canvas, (tx, ty - th - 6), (tx + tw, ty + 4), (0, 255, 0), 1)
                cv2.putText(canvas, tooltip_txt, (tx, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def run(self) -> None:
        """Bucle principal de reproducción y navegación interactiva."""
        print("\n=======================================================")
        print(f" Reproduciendo Grabación: {os.path.basename(self.file_path)}")
        print(f" Tipo: {'Base de Datos DB3 (16-bit Z16 Puro)' if self.is_db3 else 'Video MKV (Legacy)'}")
        print(f" Resolución: {self.width}x{self.height} | FPS: {self.fps} | Total Frames: {self.total_frames}")
        print("-------------------------------------------------------")
        print(" CONTROLES DE NAVEGACION Y INSPECCION:")
        print("   [P] o [ESPACIO] : Pausar / Reanudar reproducción")
        print("   [M]             : Alternar entre modo SEPARADO y SUPERPUESTO")
        print("   [1] / [2]       : Ajustar transparencia Depth en modo superpuesto")
        print("   [3] / [4]       : Ajustar transparencia IR en modo superpuesto")
        print("   [<-] / [->]     : Retroceder / Avanzar 1 segundo")
        print("   [Clic Izquierdo]: Marcar un punto de distancia permanente")
        print("   [Clic Derecho]  : Borrar marcas de distancia")
        print("   [Q] o [ESC]     : Salir")
        print("=======================================================\n")

        while True:
            # Obtener datos del frame actual
            if self.is_db3:
                frame_data = self.db_reader.get_frame(self.current_frame_idx)
                if not frame_data:
                    break

                color = frame_data["color"]
                depth_z16 = frame_data["depth_z16"]
                ir_left = frame_data["ir_left"]
                ir_right = frame_data["ir_right"]
                telemetry = frame_data["telemetry"]
                frame_id = frame_data["frame_id"]
                timestamp_ns = frame_data["timestamp_ns"]

                # Calcular distancias en metros a partir de Z16 uint16 en mm (precisión exacta de 16 bits)
                depth_m = depth_z16.astype(np.float32) / 1000.0

                # Renderizar mapa de calor JET para visualización
                depth_8bit = cv2.convertScaleAbs(depth_z16, alpha=0.03)
                depth_jet = cv2.applyColorMap(depth_8bit, cv2.COLORMAP_JET)

            else:
                # Soporte MKV legacy
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)
                ret, frame = self.cap.read()
                if not ret:
                    break

                h, w = frame.shape[:2]
                panel_h = PANEL_HEIGHT if h >= 1440 else 0
                color = frame[panel_h:panel_h + CAMERA_HEIGHT, 0:CAMERA_WIDTH]
                depth_bgr = frame[panel_h:panel_h + CAMERA_HEIGHT, CAMERA_WIDTH:w]
                ir_left = frame[panel_h + CAMERA_HEIGHT:h, 0:CAMERA_WIDTH]
                ir_right = frame[panel_h + CAMERA_HEIGHT:h, CAMERA_WIDTH:w]

                # Desempaquetar Z16 desde BGR
                low = depth_bgr[:, :, 0].astype(np.uint16)
                high = depth_bgr[:, :, 1].astype(np.uint16)
                depth_z16 = (high << 8) | low
                depth_m = depth_z16.astype(np.float32) / 1000.0

                depth_8bit = cv2.convertScaleAbs(depth_z16, alpha=0.03)
                depth_jet = cv2.applyColorMap(depth_8bit, cv2.COLORMAP_JET)

                telemetry = {}
                frame_id = self.current_frame_idx + 1
                timestamp_ns = int(time.time() * 1e9)

            # Renderizar según el modo seleccionado
            if self.mode == "separado":
                display_img = self.render_separado(
                    color, depth_jet, depth_m, ir_left, ir_right, telemetry, frame_id, timestamp_ns
                )
            else:
                display_img = self.render_superpuesto(
                    color, depth_jet, depth_m, ir_left, ir_right, telemetry, frame_id, timestamp_ns
                )

            self.process_mouse_and_pins(display_img, depth_m)

            cv2.imshow(self.window_name, display_img)
            cv2.setTrackbarPos("Frame", self.window_name, self.current_frame_idx)

            # Avanzar si no está en pausa
            if not self.paused:
                self.current_frame_idx += 1
                if self.current_frame_idx >= self.total_frames:
                    self.current_frame_idx = 0  # Repetir bucle

            # Espera de teclado
            wait_time = int(1000 / self.fps) if not self.paused else 50
            key = cv2.waitKey(max(1, wait_time)) & 0xFF

            if key in (ord('q'), ord('Q'), 27):  # ESC / Q
                break
            elif key in (ord('p'), ord('P'), 32):  # Espacio / P
                self.paused = not self.paused
            elif key in (ord('m'), ord('M')):
                self.mode = "superpuesto" if self.mode == "separado" else "separado"
            elif key == ord('1'):
                self.depth_alpha = max(0.0, self.depth_alpha - 0.1)
            elif key == ord('2'):
                self.depth_alpha = min(1.0, self.depth_alpha + 0.1)
            elif key == ord('3'):
                self.ir_alpha = max(0.0, self.ir_alpha - 0.1)
            elif key == ord('4'):
                self.ir_alpha = min(1.0, self.ir_alpha + 0.1)
            elif key in (81, 2):  # Flecha Izquierda
                self.current_frame_idx = max(0, self.current_frame_idx - int(self.fps))
            elif key in (83, 3):  # Flecha Derecha
                self.current_frame_idx = min(self.total_frames - 1, self.current_frame_idx + int(self.fps))

        if self.db_reader:
            self.db_reader.close()
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()


def seleccionar_archivo_grabacion() -> Optional[str]:
    """Busca archivos de grabación .db3 y .mkv en el proyecto o despliega un selector GUI."""
    grabaciones = glob.glob("./grabaciones/**/*.db3", recursive=True) + \
                  glob.glob("./**/*.db3", recursive=True) + \
                  glob.glob("./grabaciones/**/*.mkv", recursive=True) + \
                  glob.glob("./**/*.mkv", recursive=True)

    # Eliminar duplicados manteniendo orden
    seen = set()
    unique_files = []
    for f in grabaciones:
        abs_p = os.path.abspath(f)
        if abs_p not in seen and os.path.exists(abs_p):
            seen.add(abs_p)
            unique_files.append(abs_p)

    if unique_files:
        unique_files.sort(key=os.path.getmtime, reverse=True)
        print("Archivos de grabación encontrados:")
        for idx, fpath in enumerate(unique_files[:6]):
            ext = os.path.splitext(fpath)[1].upper()
            print(f"  [{idx + 1}] ({ext}) {fpath}")
        print("  [0] Abrir selector de archivos GUI...")

        try:
            opcion = input("\nSeleccione el número de archivo [default 1]: ").strip()
            if not opcion:
                return unique_files[0]
            val = int(opcion)
            if 1 <= val <= len(unique_files):
                return unique_files[val - 1]
        except (ValueError, IndexError):
            pass

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        archivo = filedialog.askopenfilename(
            title="Seleccionar Grabación (.db3 o .mkv)",
            initialdir="./grabaciones",
            filetypes=[
                ("Grabaciones DB3 SQLite", "*.db3"),
                ("Videos MKV", "*.mkv"),
                ("Todos los archivos", "*.*")
            ]
        )
        root.destroy()
        return archivo if archivo else None
    except Exception:
        return None


def main() -> None:
    path = None
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = seleccionar_archivo_grabacion()

    if not path or not os.path.exists(path):
        print("Error: No se seleccionó un archivo de grabación válido.")
        sys.exit(1)

    player = VisualizerPlayer(path)
    player.run()


if __name__ == "__main__":
    main()
