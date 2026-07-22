#!/usr/bin/env python3
"""
TelemetryChartRenderer — Generador de diagramas de líneas para consumo de potencia y telemetría.

Renderiza un panel visual interactivo (1600x900) con diagramas de líneas de 24 horas.
Soporta visualización del día actual en progreso (datos acumulados hasta el momento) y días pasados.
Muestra fecha/hora de consulta, permite minimizar/maximizar y guardar la imagen del diagrama a disco.
"""

import os
import math
import time
import datetime
from typing import List, Dict, Any, Tuple, Optional

import cv2
import numpy as np


class TelemetryChartRenderer:
    """
    Renderizador de diagramas de líneas para consumo de potencia y temperaturas.

    Incluye fecha/hora de consulta, indicador de día en progreso vs completado,
    y soporte para guardar la imagen del diagrama a disco.
    """

    COLOR_BG = (20, 20, 20)
    COLOR_PANEL_BG = (30, 30, 30)
    COLOR_GRID = (50, 50, 50)
    COLOR_AXIS = (90, 90, 90)
    COLOR_TEXT = (220, 220, 220)
    COLOR_YELLOW = (0, 255, 255)
    COLOR_CYAN = (255, 255, 0)
    COLOR_GREEN = (0, 255, 0)
    COLOR_RED = (0, 0, 255)

    TEMP_COLORS: Dict[str, Tuple[int, int, int]] = {
        'CPU': (0, 255, 255),       # Amarillo
        'GPU': (255, 0, 255),       # Magenta
        'SOC': (0, 255, 0),         # Verde
        'Board': (255, 255, 0),     # Cyan
        'ASIC': (0, 165, 255),      # Naranja
    }

    def __init__(self, window_name: str = "Dashboard de Consumo de Potencia y Telemetria") -> None:
        self.window_name = window_name
        self.width = 1600
        self.height = 900
        self.font_bold = cv2.FONT_HERSHEY_DUPLEX
        self.font_regular = cv2.FONT_HERSHEY_SIMPLEX
        self.selected_date_index: int = -1
        self._last_saved_msg: Optional[str] = None
        self._saved_msg_timer: float = 0.0

    def render_dashboard(
        self,
        history_manager,
    ) -> np.ndarray:
        """
        Genera la imagen BGR del Dashboard con los diagramas de líneas.
        """
        canvas = np.full((self.height, self.width, 3), self.COLOR_BG, dtype=np.uint8)

        now = datetime.datetime.now()
        today_str = now.strftime('%d/%m/%Y')
        consult_str = now.strftime('%d/%m/%Y %H:%M:%S')

        # 1. Encabezado superior con Fecha y Hora de Consulta
        cv2.putText(
            canvas,
            "DASHBOARD DE CONSUMO DE ENERGIA Y POTENCIA",
            (40, 42),
            self.font_bold,
            0.82,
            self.COLOR_YELLOW,
            2,
            cv2.LINE_AA,
        )

        cv2.putText(
            canvas,
            f"Consulta: {consult_str}",
            (1150, 42),
            self.font_bold,
            0.65,
            self.COLOR_CYAN,
            2,
            cv2.LINE_AA,
        )

        available_dates = history_manager.get_available_dates()

        # Ajustar índice de fecha seleccionada (por defecto la fecha actual de hoy)
        if self.selected_date_index < 0 or self.selected_date_index >= len(available_dates):
            self.selected_date_index = len(available_dates) - 1

        selected_date = available_dates[self.selected_date_index]
        records = history_manager.get_records_for_date(selected_date)
        is_today = (selected_date == today_str)

        # 2. Barra de selección de fecha y estado
        self._render_date_selector_bar(canvas, available_dates, selected_date, is_today)

        # 3. Rectángulos para los dos gráficos
        rect_power = (40, 130, self.width - 80, 340)
        rect_temps = (40, 500, self.width - 80, 340)

        self._render_power_chart(canvas, rect_power, records, selected_date, is_today)
        self._render_temperature_chart(canvas, rect_temps, records, selected_date, is_today)

        # 4. Mensaje temporal si se guardó la imagen
        if self._last_saved_msg and (time.time() - self._saved_msg_timer < 4.0):
            cv2.putText(
                canvas,
                self._last_saved_msg,
                (40, self.height - 50),
                self.font_bold,
                0.62,
                self.COLOR_GREEN,
                2,
                cv2.LINE_AA,
            )

        # 5. Pie con controles e instrucciones
        cv2.putText(
            canvas,
            "[Flechas / A / D] Navegar Fechas   |   [S] Guardar Imagen del Grafico   |   [Q / ESC] Cerrar",
            (40, self.height - 20),
            self.font_regular,
            0.55,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )

        return canvas

    def notify_saved(self, filepath: str) -> None:
        """Establece una notificación visual cuando la imagen se guarda en disco."""
        self._last_saved_msg = f"[EXITO] Imagen guardada en: {filepath}"
        self._saved_msg_timer = time.time()

    def _render_date_selector_bar(
        self,
        canvas: np.ndarray,
        available_dates: List[str],
        selected_date: str,
        is_today: bool,
    ) -> None:
        """Dibuja la barra superior con la fecha seleccionada y el badge de estado."""
        bar_rect = (40, 65, self.width - 80, 45)
        cv2.rectangle(canvas, (bar_rect[0], bar_rect[1]), (bar_rect[0] + bar_rect[2], bar_rect[1] + bar_rect[3]), self.COLOR_PANEL_BG, -1)
        cv2.rectangle(canvas, (bar_rect[0], bar_rect[1]), (bar_rect[0] + bar_rect[2], bar_rect[1] + bar_rect[3]), self.COLOR_AXIS, 1)

        total = len(available_dates)
        curr_num = self.selected_date_index + 1
        txt_date = f"FECHA CONSULTADA: {selected_date} ({curr_num}/{total})"

        cv2.putText(canvas, txt_date, (60, 95), self.font_bold, 0.65, self.COLOR_YELLOW, 2, cv2.LINE_AA)

        # Badge de estado (En Progreso vs Día Completado)
        if is_today:
            status_text = "DIA ACTUAL EN PROGRESO (Datos acumulados hasta el momento)"
            status_color = self.COLOR_CYAN
        else:
            status_text = "DIA ANTERIOR COMPLETADO (Reporte final de 24 horas)"
            status_color = self.COLOR_GREEN

        cv2.putText(canvas, status_text, (650, 95), self.font_bold, 0.58, status_color, 2, cv2.LINE_AA)

    def _draw_chart_box(self, canvas: np.ndarray, rect: Tuple[int, int, int, int], title: str) -> Tuple[int, int, int, int]:
        """Dibuja la caja contenedora del gráfico."""
        x, y, w, h = rect
        cv2.rectangle(canvas, (x, y), (x + w, y + h), self.COLOR_PANEL_BG, -1)
        cv2.rectangle(canvas, (x, y), (x + w, y + h), self.COLOR_AXIS, 1)

        cv2.putText(canvas, title, (x + 20, y + 32), self.font_bold, 0.65, self.COLOR_YELLOW, 2, cv2.LINE_AA)

        pad_left, pad_right = 80, 40
        pad_top, pad_bottom = 50, 40

        gx = x + pad_left
        gy = y + pad_top
        gw = w - pad_left - pad_right
        gh = h - pad_top - pad_bottom
        return (gx, gy, gw, gh)

    @staticmethod
    def _format_sec_to_time(sec: float, include_seconds: bool = True) -> str:
        """Convierte segundos del día (0..86400) a formato HH:MM:SS o HH:MM."""
        sec = max(0.0, min(86400.0, sec))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        if include_seconds:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{h:02d}:{m:02d}"

    def _get_x_range_and_ticks(self, sec_list: List[float]) -> Tuple[float, float, List[Tuple[float, str]]]:
        """
        Calcula el rango adaptativo [x_min, x_max] según los datos existentes
        para escalar la resolución del gráfico a lo largo del eje X.
        Genera 9 marcas con sus etiquetas.
        """
        if not sec_list:
            x_min, x_max = 0.0, 86400.0
        else:
            min_s = min(sec_list)
            max_s = max(sec_list)
            span_s = max_s - min_s

            if span_s < 60.0:  # Rango menor a 1 minuto: ventana centrada de 60 segundos
                center = (min_s + max_s) / 2.0
                x_min = max(0.0, center - 30.0)
                x_max = min(86400.0, center + 30.0)
            elif span_s < 3600.0:  # Rango menor a 1 hora: agregar 30 segundos de margen
                x_min = max(0.0, min_s - 30.0)
                x_max = min(86400.0, max_s + 30.0)
            else:  # Rango mayor a 1 hora: agregar 2% de margen
                margin = span_s * 0.02
                x_min = max(0.0, min_s - margin)
                x_max = min(86400.0, max_s + margin)

        span = x_max - x_min
        if span <= 0.0:
            span = 60.0
            x_max = x_min + span

        include_seconds = span < 7200.0  # Mostrar segundos si el rango es menor a 2 horas

        ticks = []
        for i in range(9):
            val = x_min + span * (i / 8.0)
            lbl = self._format_sec_to_time(val, include_seconds=include_seconds)
            ticks.append((val, lbl))

        return x_min, x_max, ticks

    def _render_power_chart(
        self,
        canvas: np.ndarray,
        rect: Tuple[int, int, int, int],
        records: List[Dict[str, Any]],
        selected_date: str,
        is_today: bool,
    ) -> None:
        """Dibuja el diagrama de líneas del consumo de potencia en Vatios (W)."""
        state_str = "(EN PROGRESO)" if is_today else "(COMPLETADO)"
        gx, gy, gw, gh = self._draw_chart_box(
            canvas, rect, f"CONSUMO DE POTENCIA (W) - {selected_date} {state_str}"
        )

        power_points = []
        p_vals = []
        sec_list = []

        for r in records:
            p = r.get('power')
            t_str = r.get('time_str', '')
            if p is not None and t_str:
                try:
                    parts = [float(x) for x in t_str.split(':')]
                    sec_in_day = parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
                    power_points.append((sec_in_day, p))
                    p_vals.append(p)
                    sec_list.append(sec_in_day)
                except Exception:
                    pass

        power_points.sort(key=lambda x: x[0])

        # Rango adaptable para Eje X (Resolución temporal)
        x_min, x_max, x_ticks = self._get_x_range_and_ticks(sec_list)
        span_x = x_max - x_min if x_max > x_min else 1.0

        # Rango adaptable para Eje Y (Vatios)
        if p_vals:
            min_p = min(p_vals)
            max_p = max(p_vals)
            p_range = max_p - min_p
            margin = max(1.0, p_range * 0.15)
            min_y = max(0.0, math.floor((min_p - margin) * 2.0) / 2.0)
            max_y = math.ceil((max_p + margin) * 2.0) / 2.0
            if max_y - min_y < 2.0:
                max_y = min_y + 2.0
        else:
            min_y, max_y = 0.0, 15.0

        span_y = max_y - min_y if max_y > min_y else 1.0

        # Eje Y (Vatios) - 5 marcas
        y_step = span_y / 4.0
        for i in range(5):
            val = min_y + i * y_step
            py = gy + int(gh * (1.0 - (val - min_y) / span_y))
            cv2.line(canvas, (gx, py), (gx + gw, py), self.COLOR_GRID, 1)
            cv2.putText(canvas, f"{val:.1f} W", (gx - 70, py + 5), self.font_regular, 0.48, self.COLOR_TEXT, 1, cv2.LINE_AA)

        # Eje X (Resolución adaptable: marcas dinámicas)
        for i, (val, hour_lbl) in enumerate(x_ticks):
            px = gx + int(gw * (i / 8.0))
            cv2.line(canvas, (px, gy), (px, gy + gh), self.COLOR_GRID, 1)
            cv2.putText(canvas, hour_lbl, (px - 28, gy + gh + 25), self.font_regular, 0.45, self.COLOR_TEXT, 1, cv2.LINE_AA)

        cv2.rectangle(canvas, (gx, gy), (gx + gw, gy + gh), self.COLOR_AXIS, 1)

        # Estadísticas
        if p_vals:
            avg_p = sum(p_vals) / len(p_vals)
            last_p_str = f" | Ultimo: {p_vals[-1]:.2f}W" if is_today else ""
            stats_txt = f"Lecturas: {len(p_vals)}  |  Min: {min(p_vals):.2f}W  |  Max: {max(p_vals):.2f}W  |  Prom: {avg_p:.2f}W{last_p_str}"
        else:
            stats_txt = "Esperando lecturas de potencia de la Jetson para este dia..."

        stats_w = cv2.getTextSize(stats_txt, self.font_regular, 0.50, 1)[0][0]
        stats_x = (rect[0] + rect[2] - 20) - stats_w
        cv2.putText(canvas, stats_txt, (stats_x, rect[1] + 32), self.font_regular, 0.50, self.COLOR_CYAN, 1, cv2.LINE_AA)

        if len(power_points) < 2:
            return

        # Dibujar líneas del gráfico escaladas al rango x_min..x_max
        pts_array = []
        for sec_day, val in power_points:
            norm_x = (sec_day - x_min) / span_x
            norm_x = max(0.0, min(1.0, norm_x))
            norm_y = (val - min_y) / span_y
            norm_y = max(0.0, min(1.0, norm_y))

            px = gx + int(gw * norm_x)
            py = gy + int(gh * (1.0 - norm_y))
            pts_array.append([px, py])

        pts_np = np.array(pts_array, dtype=np.int32).reshape((-1, 1, 2))

        # Relleno traslúcido bajo la curva
        fill_pts = np.vstack([
            [[pts_array[0][0], gy + gh]],
            pts_np.reshape((-1, 2)),
            [[pts_array[-1][0], gy + gh]]
        ])
        overlay = canvas.copy()
        cv2.fillPoly(overlay, [fill_pts.reshape((-1, 1, 2))], (180, 140, 0))
        cv2.addWeighted(overlay, 0.18, canvas, 0.82, 0, canvas)

        # Trazo de la línea
        cv2.polylines(canvas, [pts_np], isClosed=False, color=self.COLOR_CYAN, thickness=2, lineType=cv2.LINE_AA)

    def _render_temperature_chart(
        self,
        canvas: np.ndarray,
        rect: Tuple[int, int, int, int],
        records: List[Dict[str, Any]],
        selected_date: str,
        is_today: bool,
    ) -> None:
        """Dibuja el diagrama de líneas de temperaturas del hardware."""
        state_str = "(EN PROGRESO)" if is_today else "(COMPLETADO)"
        gx, gy, gw, gh = self._draw_chart_box(
            canvas, rect, f"TEMPERATURAS DEL HARDWARE (C) - {selected_date} {state_str}"
        )

        series: Dict[str, List[Tuple[float, float]]] = {
            'CPU': [], 'GPU': [], 'SOC': [], 'Board': [], 'ASIC': []
        }
        all_secs = []
        all_temps = []

        for r in records:
            t_str = r.get('time_str', '')
            if not t_str:
                continue
            try:
                parts = [float(x) for x in t_str.split(':')]
                sec_day = parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
            except Exception:
                continue

            asic = r.get('asic_temp')
            if asic is not None:
                series['ASIC'].append((sec_day, asic))
                all_secs.append(sec_day)
                all_temps.append(asic)

            temps = r.get('temps', {})
            for key in ['CPU', 'GPU', 'SOC', 'Board']:
                val = temps.get(key)
                if val is not None:
                    series[key].append((sec_day, val))
                    all_secs.append(sec_day)
                    all_temps.append(val)

        # Rango adaptable para Eje X (Resolución temporal)
        x_min, x_max, x_ticks = self._get_x_range_and_ticks(all_secs)
        span_x = x_max - x_min if x_max > x_min else 1.0

        # Rango adaptable para Eje Y (Temperatura C)
        if all_temps:
            min_t = min(all_temps)
            max_t = max(all_temps)
            t_range = max_t - min_t
            margin = max(3.0, t_range * 0.15)
            min_y = max(0.0, math.floor(min_t - margin))
            max_y = math.ceil(max_t + margin)
            if max_y - min_y < 10.0:
                max_y = min_y + 10.0
        else:
            min_y, max_y = 20.0, 100.0

        span_y = max_y - min_y if max_y > min_y else 1.0

        # Eje Y (Temperatura C) - 5 marcas
        y_step = span_y / 4.0
        for i in range(5):
            val = min_y + i * y_step
            py = gy + int(gh * (1.0 - (val - min_y) / span_y))
            cv2.line(canvas, (gx, py), (gx + gw, py), self.COLOR_GRID, 1)
            cv2.putText(canvas, f"{int(round(val))} C", (gx - 65, py + 5), self.font_regular, 0.48, self.COLOR_TEXT, 1, cv2.LINE_AA)

        # Eje X (Marcas adaptables)
        for i, (val, hour_lbl) in enumerate(x_ticks):
            px = gx + int(gw * (i / 8.0))
            cv2.line(canvas, (px, gy), (px, gy + gh), self.COLOR_GRID, 1)
            cv2.putText(canvas, hour_lbl, (px - 28, gy + gh + 25), self.font_regular, 0.45, self.COLOR_TEXT, 1, cv2.LINE_AA)

        cv2.rectangle(canvas, (gx, gy), (gx + gw, gy + gh), self.COLOR_AXIS, 1)

        legend_x = gx + gw - 460
        legend_y = rect[1] + 25

        for idx, (name, points) in enumerate(series.items()):
            points.sort(key=lambda x: x[0])
            color = self.TEMP_COLORS.get(name, self.COLOR_TEXT)

            lx = legend_x + (idx % 3) * 140
            ly = legend_y + (idx // 3) * 22
            cv2.rectangle(canvas, (lx, ly - 10), (lx + 15, ly + 2), color, -1)
            last_val_str = f" {points[-1][1]:.1f}C" if points else " --"
            cv2.putText(canvas, f"{name}:{last_val_str}", (lx + 22, ly), self.font_regular, 0.48, self.COLOR_TEXT, 1, cv2.LINE_AA)

            if len(points) < 2:
                continue

            pts_array = []
            for sec_day, val in points:
                norm_x = (sec_day - x_min) / span_x
                norm_x = max(0.0, min(1.0, norm_x))
                norm_y = (val - min_y) / span_y
                norm_y = max(0.0, min(1.0, norm_y))

                px = gx + int(gw * norm_x)
                py = gy + int(gh * (1.0 - norm_y))
                pts_array.append([px, py])

            pts_np = np.array(pts_array, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(canvas, [pts_np], isClosed=False, color=color, thickness=2, lineType=cv2.LINE_AA)
