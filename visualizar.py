#!/usr/bin/env python3
"""
Visualizador de Videos MKV Multicanal (RGB, Depth, IR Left, IR Right).

Permite reproducir y analizar grabaciones .mkv con dos modos de visualización:
1. Modo "Por Separado": Muestra la disposición original (panel + mosaico 2x2).
2. Modo "Superpuestos": Fusiona los 4 canales en una única vista combinada con transparencia regulable.

Incluye inspección de distancia en tiempo real al mover/hacer clic con el mouse,
leyenda de profundidad y verificación de integridad del canal Depth.
"""

import sys
import os
import glob
import time
from typing import Optional, Tuple, List

import cv2
import numpy as np

# Intentar importar desde el proyecto local
try:
    from config import CAMERA_WIDTH, CAMERA_HEIGHT, PANEL_HEIGHT, MOSAIC_WIDTH, MOSAIC_HEIGHT
    from utils import unpack_bgr_to_z16, extraer_metadatos_frame
except ImportError:
    CAMERA_WIDTH = 1280
    CAMERA_HEIGHT = 720
    PANEL_HEIGHT = 120
    MOSAIC_WIDTH = 2560
    MOSAIC_HEIGHT = 1560


class DepthDecoder:
    """
    Decodificador y convertidor de profundidad para la cámara Intel RealSense D435.
    Soporta tanto empaquetado BGR uint16 como mapa de calor JET con búsqueda ultra rápida (3D LUT).
    """

    def __init__(self, max_distance_m: float = 8.5) -> None:
        self.max_distance_m = max_distance_m
        self._lut_64: Optional[np.ndarray] = None
        self._init_lut()

    def _init_lut(self) -> None:
        """Construye un 3D LUT (64x64x64) optimizado para inversión de cv2.COLORMAP_JET en <10ms."""
        try:
            from scipy.spatial import cKDTree
            jet_lut = cv2.applyColorMap(np.arange(256, dtype=np.uint8).reshape(256, 1), cv2.COLORMAP_JET).reshape(256, 3)
            tree = cKDTree(jet_lut)
            bgr_grid = np.mgrid[0:256:4, 0:256:4, 0:256:4].reshape(3, -1).T
            _, indices = tree.query(bgr_grid)
            self._lut_64 = indices.reshape(64, 64, 64).astype(np.uint8)
        except Exception:
            self._lut_64 = None

    def decode_depth_to_meters(self, depth_crop: np.ndarray) -> np.ndarray:
        """
        Convierte una matriz BGR de la zona Depth a distancias en metros.

        Parameters
        ----------
        depth_crop : np.ndarray
            Sub-imagen BGR de tamaño 720x1280.

        Returns
        -------
        np.ndarray
            Matriz de distancias en metros (float32).
        """
        if depth_crop is None:
            return np.zeros((CAMERA_HEIGHT, CAMERA_WIDTH), dtype=np.float32)

        # Caso 1: Depth guardado como BGR empaquetado Z16 (Canal R es 0 o casi 0)
        if depth_crop[:, :, 2].max() < 10:
            low_byte = depth_crop[:, :, 0].astype(np.uint16)
            high_byte = depth_crop[:, :, 1].astype(np.uint16)
            z16_mm = (high_byte << 8) | low_byte
            return z16_mm.astype(np.float32) / 1000.0

        # Caso 2: Depth guardado como Mapa de Calor JET
        if self._lut_64 is not None:
            b = (depth_crop[:, :, 0] >> 2)
            g = (depth_crop[:, :, 1] >> 2)
            r = (depth_crop[:, :, 2] >> 2)
            depth8 = self._lut_64[b, g, r]
            return (depth8.astype(np.float32) / 255.0) * self.max_distance_m

        # Fallback a conversión simple por intensidad BGR
        gray = cv2.cvtColor(depth_crop, cv2.COLOR_BGR2GRAY)
        return (gray.astype(np.float32) / 255.0) * self.max_distance_m


class MKVVisualizer:
    """
    Visualizador interactivo de grabaciones MKV multicanal.
    """

    def __init__(self, mkv_path: str) -> None:
        self.mkv_path = mkv_path
        self.cap = cv2.VideoCapture(mkv_path)

        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el archivo de video: {mkv_path}")

        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        self.depth_decoder = DepthDecoder(max_distance_m=8.5)

        # Estado del reproductor
        self.current_frame_idx = 0
        self.paused = False
        self.mode = "separado"  # 'separado' o 'superpuesto'

        # Ajustes de fusión / superposición
        self.depth_alpha = 0.5
        self.ir_alpha = 0.3

        # Mouse y mediciones
        self.mouse_pos: Optional[Tuple[int, int]] = None  # (x, y) en coordenadas de la imagen renderizada
        self.pinned_points: List[Tuple[int, int]] = []  # Lista de puntos marcados por clic

        # Ventana OpenCV
        self.window_name = f"Visualizador MKV - {os.path.basename(mkv_path)}"
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
        cv2.resizeWindow(self.window_name, 1280, 780)
        cv2.setMouseCallback(self.window_name, self._on_mouse)

        # Crear Trackbar para navegación temporal
        cv2.createTrackbar("Frame", self.window_name, 0, max(1, self.total_frames - 1), self._on_trackbar)

    def _on_trackbar(self, val: int) -> None:
        if val != self.current_frame_idx:
            self.current_frame_idx = val
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, val)

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: None) -> None:
        self.mouse_pos = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            self.pinned_points.append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.pinned_points.clear()

    def crop_channels(self, frame: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Extrae el panel superior y los 4 cuadrantes del frame del mosaico."""
        h, w = frame.shape[:2]

        if h >= 1440 and w >= 2560:
            panel = frame[0:PANEL_HEIGHT, 0:w]
            rgb = frame[PANEL_HEIGHT:PANEL_HEIGHT + CAMERA_HEIGHT, 0:CAMERA_WIDTH]
            depth = frame[PANEL_HEIGHT:PANEL_HEIGHT + CAMERA_HEIGHT, CAMERA_WIDTH:w]
            ir_left = frame[PANEL_HEIGHT + CAMERA_HEIGHT:h, 0:CAMERA_WIDTH]
            ir_right = frame[PANEL_HEIGHT + CAMERA_HEIGHT:h, CAMERA_WIDTH:w]
        else:
            mid_y = h // 2
            mid_x = w // 2
            panel = frame[0:60, 0:w]
            rgb = frame[0:mid_y, 0:mid_x]
            depth = frame[0:mid_y, mid_x:w]
            ir_left = frame[mid_y:h, 0:mid_x]
            ir_right = frame[mid_y:h, mid_x:w]

        return panel, rgb, depth, ir_left, ir_right

    def render_separado(self, frame: np.ndarray, depth_m: np.ndarray) -> np.ndarray:
        """Renderiza la vista original con información de canal y guía de distancia."""
        view = frame.copy()
        vh, vw = view.shape[:2]

        # Fondo oscuro inferior para indicación del modo activo
        mode_badge = " MODO: POR SEPARADO (Original 2x2)  |  [M] Cambiar a Superpuesto  |  [P/Espacio] Pausa  |  [<- / ->] Buscar "
        cv2.rectangle(view, (10, vh - 45), (1020, vh - 10), (15, 15, 15), -1)
        cv2.rectangle(view, (10, vh - 45), (1020, vh - 10), (60, 60, 60), 1)
        cv2.putText(view, mode_badge, (20, vh - 22), cv2.FONT_HERSHEY_DUPLEX, 0.55, (0, 255, 255), 1, cv2.LINE_AA)

        # Leyenda y Verificación de Profundidad
        self._draw_depth_legend(view, depth_m)

        return view

    def render_superpuesto(
        self,
        rgb: np.ndarray,
        depth: np.ndarray,
        ir_left: np.ndarray,
        ir_right: np.ndarray,
        depth_m: np.ndarray,
    ) -> np.ndarray:
        """Fusiona los 4 canales (RGB + Depth + IR) en una única vista combinada."""
        h, w = rgb.shape[:2]

        # 1. Base RGB
        fused = rgb.astype(np.float32)

        # 2. Superponer Depth (heatmap)
        depth_f32 = depth.astype(np.float32)
        fused = cv2.addWeighted(fused, 1.0 - self.depth_alpha, depth_f32, self.depth_alpha, 0)

        # 3. Superponer IR Left (detalles estructurales)
        ir_f32 = ir_left.astype(np.float32)
        if self.ir_alpha > 0:
            fused = cv2.addWeighted(fused, 1.0, ir_f32, self.ir_alpha, 0)

        res = np.clip(fused, 0, 255).astype(np.uint8)

        # Panel de control de fusión superior (60px alto)
        panel_bar = np.full((60, w, 3), (25, 25, 25), dtype=np.uint8)
        font = cv2.FONT_HERSHEY_SIMPLEX

        txt_mode = "MODO: FUSION SUPERPUESTA (4 CANALES SUPERPUESTOS)"
        cv2.putText(panel_bar, txt_mode, (20, 25), cv2.FONT_HERSHEY_DUPLEX, 0.65, (0, 255, 255), 2, cv2.LINE_AA)

        txt_ctrls = f"Depth Alpha: {self.depth_alpha:.2f} [1/2] | IR Alpha: {self.ir_alpha:.2f} [3/4] | [M] Modo | [P] Pausa"
        cv2.putText(panel_bar, txt_ctrls, (20, 48), font, 0.52, (220, 220, 220), 1, cv2.LINE_AA)

        full_view = np.vstack((panel_bar, res))

        # Leyenda de Profundidad
        self._draw_depth_legend(full_view, depth_m)

        return full_view

    def _draw_depth_legend(self, canvas: np.ndarray, depth_m: np.ndarray) -> None:
        """Dibuja una barra de escala de profundidad y métricas de verificación del canal Depth."""
        ch, cw = canvas.shape[:2]

        # Barra lateral de profundidad (esquina superior derecha)
        bar_w, bar_h = 22, 160
        x_bar = cw - 55
        y_bar = 85

        # Degradado de colores JET de 0m a 8.5m
        gradient = np.linspace(0, 255, bar_h, dtype=np.uint8).reshape(bar_h, 1)
        grad_jet = cv2.applyColorMap(gradient, cv2.COLORMAP_JET)

        canvas[y_bar:y_bar + bar_h, x_bar:x_bar + bar_w] = grad_jet
        cv2.rectangle(canvas, (x_bar - 1, y_bar - 1), (x_bar + bar_w + 1, y_bar + bar_h + 1), (255, 255, 255), 1)

        # Etiquetas de distancia
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(canvas, "0.0m", (x_bar - 45, y_bar + 12), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"{self.depth_decoder.max_distance_m / 2:.1f}m", (x_bar - 45, y_bar + bar_h // 2 + 4), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, f"{self.depth_decoder.max_distance_m:.1f}m", (x_bar - 45, y_bar + bar_h - 2), font, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

        # Verificación del Canal Depth
        valid_pixels = np.count_nonzero(depth_m > 0.05)
        total_pixels = depth_m.size
        pct_valid = (valid_pixels / total_pixels) * 100.0
        mean_dist = float(np.mean(depth_m[depth_m > 0.05])) if valid_pixels > 0 else 0.0

        badge_txt = f"CANAL DEPTH DETECTADO | {pct_valid:.1f}% Pixeles Validos | Dist. Media: {mean_dist:.2f}m"
        (bw, bh), _ = cv2.getTextSize(badge_txt, font, 0.48, 1)

        bx = cw - bw - 70
        by = y_bar - 15
        cv2.rectangle(canvas, (bx - 8, by - bh - 6), (bx + bw + 8, by + 4), (15, 15, 15), -1)
        cv2.rectangle(canvas, (bx - 8, by - bh - 6), (bx + bw + 8, by + 4), (0, 255, 0), 1)
        cv2.putText(canvas, badge_txt, (bx, by), font, 0.48, (0, 255, 0), 1, cv2.LINE_AA)

    def map_coords_to_depth(self, x: int, y: int, mode: str, ch: int, cw: int) -> Optional[Tuple[int, int]]:
        """
        Mapea las coordenadas del cursor en pantalla a las coordenadas de la matriz Depth (1280x720).
        Soporta los 4 cuadrantes (RGB, Depth, IR Left, IR Right) en modo separado y la vista fusionada.
        """
        if mode == "separado":
            # Cuadrante RGB (Top-Left): y in [120..840], x in [0..1280]
            if PANEL_HEIGHT <= y < PANEL_HEIGHT + CAMERA_HEIGHT and 0 <= x < CAMERA_WIDTH:
                return (x, y - PANEL_HEIGHT)
            # Cuadrante Depth (Top-Right): y in [120..840], x in [1280..2560]
            elif PANEL_HEIGHT <= y < PANEL_HEIGHT + CAMERA_HEIGHT and CAMERA_WIDTH <= x < cw:
                return (x - CAMERA_WIDTH, y - PANEL_HEIGHT)
            # Cuadrante IR Left (Bottom-Left): y in [840..1560], x in [0..1280]
            elif PANEL_HEIGHT + CAMERA_HEIGHT <= y < ch and 0 <= x < CAMERA_WIDTH:
                return (x, y - (PANEL_HEIGHT + CAMERA_HEIGHT))
            # Cuadrante IR Right (Bottom-Right): y in [840..1560], x in [1280..2560]
            elif PANEL_HEIGHT + CAMERA_HEIGHT <= y < ch and CAMERA_WIDTH <= x < cw:
                return (x - CAMERA_WIDTH, y - (PANEL_HEIGHT + CAMERA_HEIGHT))

        elif mode == "superpuesto":
            # La imagen fusionada empieza tras la barra superior de 60px
            if 60 <= y < ch and 0 <= x < cw:
                dx = int((x / cw) * CAMERA_WIDTH)
                dy = int(((y - 60) / (ch - 60)) * CAMERA_HEIGHT)
                if 0 <= dx < CAMERA_WIDTH and 0 <= dy < CAMERA_HEIGHT:
                    return (dx, dy)

        return None

    def process_mouse_and_pins(self, canvas: np.ndarray, depth_m: np.ndarray) -> None:
        """Muestra la distancia medida al pasar el cursor sobre la imagen o hacer clic."""
        if depth_m is None:
            return

        ch, cw = canvas.shape[:2]

        # 1. Dibujar puntos marcados con clic (Pinned points)
        for pt in self.pinned_points:
            d_coords = self.map_coords_to_depth(pt[0], pt[1], self.mode, ch, cw)
            if d_coords:
                dx, dy = d_coords
                dist = depth_m[dy, dx]
                dist_str = f"{dist:.2f} m ({int(dist * 100)} cm)" if dist > 0.02 else "Sin profundidad"

                cv2.circle(canvas, pt, 6, (0, 0, 255), -1, cv2.LINE_AA)
                cv2.circle(canvas, pt, 8, (255, 255, 255), 2, cv2.LINE_AA)

                # Tooltip pin
                txt = f" {dist_str} "
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
                cv2.rectangle(canvas, (pt[0] + 10, pt[1] - th - 8), (pt[0] + 10 + tw, pt[1] + 4), (15, 15, 15), -1)
                cv2.rectangle(canvas, (pt[0] + 10, pt[1] - th - 8), (pt[0] + 10 + tw, pt[1] + 4), (0, 255, 255), 1)
                cv2.putText(canvas, txt, (pt[0] + 10, pt[1] - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)

        # 2. Inspector dinámico con la posición del cursor (Mouse hover)
        if self.mouse_pos:
            mx, my = self.mouse_pos
            d_coords = self.map_coords_to_depth(mx, my, self.mode, ch, cw)
            if d_coords:
                dx, dy = d_coords
                dist = depth_m[dy, dx]
                dist_str = f"{dist:.2f} m ({int(dist * 100)} cm)" if dist > 0.02 else "Sin retorno Depth"

                # Crosshair
                cv2.line(canvas, (mx - 12, my), (mx + 12, my), (0, 255, 0), 1, cv2.LINE_AA)
                cv2.line(canvas, (mx, my - 12), (mx, my + 12), (0, 255, 0), 1, cv2.LINE_AA)

                # Tooltip flotante
                tooltip_txt = f" Distancia: {dist_str} | (X:{dx}, Y:{dy}) "
                (tw, th), _ = cv2.getTextSize(tooltip_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

                tx = min(mx + 15, cw - tw - 15)
                ty = max(my - 15, th + 15)

                cv2.rectangle(canvas, (tx, ty - th - 6), (tx + tw, ty + 4), (15, 15, 15), -1)
                cv2.rectangle(canvas, (tx, ty - th - 6), (tx + tw, ty + 4), (0, 255, 0), 1)
                cv2.putText(canvas, tooltip_txt, (tx, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

    def run(self) -> None:
        """Bucle principal de reproducción y eventos."""
        print("\n=======================================================")
        print(f" Reproduciendo MKV: {os.path.basename(self.mkv_path)}")
        print(f" Resolución: {self.width}x{self.height} | FPS: {self.fps} | Frames: {self.total_frames}")
        print("-------------------------------------------------------")
        print(" CONTROLES DE NAVEGACION Y INSPECCION:")
        print("   [P] o [ESPACIO] : Pausar / Reanudar video")
        print("   [M]             : Alternar entre modo SEPARADO y SUPERPUESTO")
        print("   [1] / [2]       : Ajustar transparencia Depth en modo superpuesto")
        print("   [3] / [4]       : Ajustar transparencia IR en modo superpuesto")
        print("   [<-] / [->]     : Retroceder / Avanzar 1 segundo")
        print("   [Clic Izquierdo]: Marcar un punto de distancia permanente")
        print("   [Clic Derecho]  : Borrar marcas de distancia")
        print("   [Q] o [ESC]     : Salir")
        print("=======================================================\n")

        while True:
            if not self.paused:
                ret, frame = self.cap.read()
                if not ret:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.current_frame_idx = 0
                    continue

                self.current_frame_idx = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                cv2.setTrackbarPos("Frame", self.window_name, min(self.current_frame_idx, self.total_frames - 1))
            else:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)
                ret, frame = self.cap.read()
                if not ret:
                    break

            panel, rgb, depth, ir_left, ir_right = self.crop_channels(frame)
            depth_m = self.depth_decoder.decode_depth_to_meters(depth)

            if self.mode == "separado":
                display_img = self.render_separado(frame, depth_m)
            else:
                display_img = self.render_superpuesto(rgb, depth, ir_left, ir_right, depth_m)

            self.process_mouse_and_pins(display_img, depth_m)

            cv2.imshow(self.window_name, display_img)

            key = cv2.waitKey(20 if not self.paused else 50) & 0xFF

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
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)
            elif key in (83, 3):  # Flecha Derecha
                self.current_frame_idx = min(self.total_frames - 1, self.current_frame_idx + int(self.fps))
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame_idx)

        self.cap.release()
        cv2.destroyAllWindows()


def seleccionar_archivo_mkv() -> Optional[str]:
    """Busca archivos MKV en el proyecto o despliega un selector GUI."""
    mkv_files = glob.glob("./grabaciones/**/*.mkv", recursive=True)
    if not mkv_files:
        mkv_files = glob.glob("./**/*.mkv", recursive=True)

    if mkv_files:
        mkv_files.sort(key=os.path.getmtime, reverse=True)
        print("Archivos MKV encontrados en el sistema:")
        for idx, fpath in enumerate(mkv_files[:5]):
            print(f"  [{idx + 1}] {fpath}")
        print("  [0] Abrir selector de archivos GUI...")

        try:
            opcion = input("\nSeleccione el número de archivo [default 1]: ").strip()
            if not opcion:
                return mkv_files[0]
            val = int(opcion)
            if 1 <= val <= len(mkv_files):
                return mkv_files[val - 1]
        except (ValueError, IndexError):
            pass

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        archivo = filedialog.askopenfilename(
            title="Seleccionar Video MKV Multicanal",
            initialdir="./grabaciones",
            filetypes=[("Archivos MKV", "*.mkv"), ("Todos los archivos", "*.*")]
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
        path = seleccionar_archivo_mkv()

    if not path or not os.path.exists(path):
        print("Error: No se seleccionó un archivo MKV válido.")
        sys.exit(1)

    visualizer = MKVVisualizer(path)
    visualizer.run()


if __name__ == "__main__":
    main()
