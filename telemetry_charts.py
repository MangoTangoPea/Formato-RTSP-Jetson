#!/usr/bin/env python3
"""
TelemetryChartRenderer — Generador de diagramas de líneas para consumo de potencia y telemetría.

Renderiza un panel visual interactivo (1600x900) con diagramas de líneas de 24 horas.
RESTRICCIÓN CLAVE: Solo permite visualizar reportes completados de días pasados (al día siguiente).
"""

import math
import time
import datetime
from typing import List, Dict, Any, Tuple, Optional

import cv2
import numpy as np


class TelemetryChartRenderer:
    """
    Renderizador de diagramas de líneas para consumo de potencia y temperaturas.

    Cumple con la regla de visualización al día siguiente (días pasados completados).
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
    COLOR_BLUE = (255, 100, 0)

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

    def render_dashboard(
        self,
        history_manager,
    ) -> np.ndarray:
        """
        Genera la imagen BGR del Dashboard con los diagramas de líneas de días pasados completados.
        """
        canvas = np.full((self.height, self.width, 3), self.COLOR_BG, dtype=np.uint8)

        # Encabezado superior
        cv2.putText(
            canvas,
            "DASHBOARD DE CONSUMO DE ENERGIA Y POTENCIA (HISTORIAL DIARIO)",
            (40, 45),
            self.font_bold,
            0.85,
            self.COLOR_YELLOW,
            2,
            cv2.LINE_AA,
        )

        today_str = datetime.datetime.now().strftime('%d/%m/%Y')
        completed_dates = history_manager.get_completed_dates()

        # Si no hay días pasados completados todavía
        if not completed_dates:
            self._render_no_past_days_notice(canvas, today_str)
            return canvas

        # Ajustar índice de fecha seleccionada (por defecto la más reciente completada, ej. ayer)
        if self.selected_date_index < 0 or self.selected_date_index >= len(completed_dates):
            self.selected_date_index = len(completed_dates) - 1

        selected_date = completed_dates[self.selected_date_index]
        records = history_manager.get_records_for_date(selected_date)

        # Barra de selección de fecha de día anterior
        self._render_date_selector_bar(canvas, completed_dates, selected_date, today_str)

        # Dividir área en 2 rectángulos de gráficos
        rect_power = (40, 130, self.width - 80, 340)
        rect_temps = (40, 500, self.width - 80, 340)

        self._render_power_chart(canvas, rect_power, records, selected_date)
        self._render_temperature_chart(canvas, rect_temps, records, selected_date)

        # Pie con controles
        cv2.putText(
            canvas,
            "[Flechas/A/D] Cambiar Dia Pasado   |   [Q/ESC] Cerrar Dashboard",
            (40, self.height - 20),
            self.font_regular,
            0.55,
            (180, 180, 180),
            1,
            cv2.LINE_AA,
        )

        return canvas

    def _render_no_past_days_notice(self, canvas: np.ndarray, today_str: str) -> None:
        """Dibuja la notificación indicando que los datos de hoy se están registrando y estarán disponibles mañana."""
        box_w, box_h = 1000, 300
        box_x = (self.width - box_w) // 2
        box_y = (self.height - box_h) // 2

        cv2.rectangle(canvas, (box_x, box_y), (box_x + box_w, box_y + box_h), self.COLOR_PANEL_BG, -1)
        cv2.rectangle(canvas, (box_x, box_y), (box_x + box_w, box_y + box_h), self.COLOR_YELLOW, 2)

        cv2.putText(
            canvas,
            "REGISTRO EN PROGRESO - VISUALIZACION AL DIA SIGUIENTE",
            (box_x + 60, box_y + 70),
            self.font_bold,
            0.75,
            self.COLOR_YELLOW,
            2,
            cv2.LINE_AA,
        )

        msg_lines = [
            f"Dia actual en registro: {today_str}",
            "El sistema esta guardando continuamente el consumo de potencia y telemetria de hoy.",
            "Los diagramas de lineas completos de 24h estaran disponibles para su visualizacion",
            "a partir de manana (al completar el dia).",
        ]

        y_offset = box_y + 130
        for line in msg_lines:
            cv2.putText(
                canvas,
                line,
                (box_x + 60, y_offset),
                self.font_regular,
                0.62,
                self.COLOR_TEXT,
                1,
                cv2.LINE_AA,
            )
            y_offset += 35

    def _render_date_selector_bar(
        self,
        canvas: np.ndarray,
        completed_dates: List[str],
        selected_date: str,
        today_str: str,
    ) -> None:
        """Dibuja la barra con el selector de fecha del día anterior completado."""
        bar_rect = (40, 70, self.width - 80, 45)
        cv2.rectangle(canvas, (bar_rect[0], bar_rect[1]), (bar_rect[0] + bar_rect[2], bar_rect[1] + bar_rect[3]), self.COLOR_PANEL_BG, -1)
        cv2.rectangle(canvas, (bar_rect[0], bar_rect[1]), (bar_rect[0] + bar_rect[2], bar_rect[1] + bar_rect[3]), self.COLOR_AXIS, 1)

        total = len(completed_dates)
        curr_num = self.selected_date_index + 1
        txt_date = f"REPORTE DIA COMPLETADO: {selected_date} ({curr_num}/{total})"

        cv2.putText(canvas, txt_date, (60, 100), self.font_bold, 0.65, self.COLOR_GREEN, 2, cv2.LINE_AA)
        cv2.putText(canvas, f"[Dia de Hoy: {today_str} - En progreso]", (650, 100), self.font_regular, 0.58, (150, 150, 150), 1, cv2.LINE_AA)

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

    def _render_power_chart(
        self,
        canvas: np.ndarray,
        rect: Tuple[int, int, int, int],
        records: List[Dict[str, Any]],
        selected_date: str,
    ) -> None:
        """Dibuja el diagrama de líneas del consumo de potencia en Vatios (W) durante 24h."""
        gx, gy, gw, gh = self._draw_chart_box(
            canvas, rect, f"DIAGRAMA DE CONSUMO DE POTENCIA (VATIOS / W) — DIA: {selected_date}"
        )

        # Extraer puntos de potencia ordenados por la hora del día (00:00:00 a 23:59:59)
        power_points = []
        p_vals = []

        for r in records:
            p = r.get('power')
            t_str = r.get('time_str', '')
            if p is not None and t_str:
                try:
                    parts = [float(x) for x in t_str.split(':')]
                    sec_in_day = parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
                    power_points.append((sec_in_day, p))
                    p_vals.append(p)
                except Exception:
                    pass

        # Ordenar por segundo del día
        power_points.sort(key=lambda x: x[0])

        max_p = max(p_vals) if p_vals else 15.0
        max_y = math.ceil(max_p / 5.0) * 5.0
        max_y = max(max_y, 10.0)
        min_y = 0.0

        # Eje Y (Vatios)
        y_step = max_y / 5.0
        for val in np.arange(min_y, max_y + 0.1, y_step):
            py = gy + int(gh * (1.0 - (val - min_y) / (max_y - min_y)))
            cv2.line(canvas, (gx, py), (gx + gw, py), self.COLOR_GRID, 1)
            cv2.putText(canvas, f"{val:.1f} W", (gx - 70, py + 5), self.font_regular, 0.5, self.COLOR_TEXT, 1, cv2.LINE_AA)

        # Eje X (24 horas del día: 00:00 a 24:00 cada 3 horas)
        for i in range(9):
            px = gx + int(gw * (i / 8.0))
            cv2.line(canvas, (px, gy), (px, gy + gh), self.COLOR_GRID, 1)
            hour_lbl = f"{i * 3:02d}:00"
            cv2.putText(canvas, hour_lbl, (px - 20, gy + gh + 25), self.font_regular, 0.5, self.COLOR_TEXT, 1, cv2.LINE_AA)

        cv2.rectangle(canvas, (gx, gy), (gx + gw, gy + gh), self.COLOR_AXIS, 1)

        # Estadísticas 24h
        if p_vals:
            avg_p = sum(p_vals) / len(p_vals)
            stats_txt = f"Estadísticas 24h:  Mín: {min(p_vals):.2f}W  |  Máx: {max(p_vals):.2f}W  |  Promedio: {avg_p:.2f}W"
        else:
            stats_txt = "Sin registros suficientes para este día..."

        cv2.putText(canvas, stats_txt, (gx + gw - 620, rect[1] + 32), self.font_regular, 0.52, self.COLOR_CYAN, 1, cv2.LINE_AA)

        if len(power_points) < 2:
            return

        # Dibujar líneas del gráfico
        pts_array = []
        for sec_day, val in power_points:
            norm_x = sec_day / 86400.0
            norm_x = max(0.0, min(1.0, norm_x))
            norm_y = (val - min_y) / (max_y - min_y)
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
    ) -> None:
        """Dibuja el diagrama de líneas de temperaturas del hardware durante 24h."""
        gx, gy, gw, gh = self._draw_chart_box(
            canvas, rect, f"DIAGRAMA DE TEMPERATURAS HARDWARE (°C) — DIA: {selected_date}"
        )

        min_y, max_y = 20.0, 100.0
        y_step = 20.0

        for val in np.arange(min_y, max_y + 1.0, y_step):
            py = gy + int(gh * (1.0 - (val - min_y) / (max_y - min_y)))
            cv2.line(canvas, (gx, py), (gx + gw, py), self.COLOR_GRID, 1)
            cv2.putText(canvas, f"{int(val)} C", (gx - 65, py + 5), self.font_regular, 0.5, self.COLOR_TEXT, 1, cv2.LINE_AA)

        for i in range(9):
            px = gx + int(gw * (i / 8.0))
            cv2.line(canvas, (px, gy), (px, gy + gh), self.COLOR_GRID, 1)
            hour_lbl = f"{i * 3:02d}:00"
            cv2.putText(canvas, hour_lbl, (px - 20, gy + gh + 25), self.font_regular, 0.5, self.COLOR_TEXT, 1, cv2.LINE_AA)

        cv2.rectangle(canvas, (gx, gy), (gx + gw, gy + gh), self.COLOR_AXIS, 1)

        series: Dict[str, List[Tuple[float, float]]] = {
            'CPU': [], 'GPU': [], 'SOC': [], 'Board': [], 'ASIC': []
        }

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

            temps = r.get('temps', {})
            for key in ['CPU', 'GPU', 'SOC', 'Board']:
                val = temps.get(key)
                if val is not None:
                    series[key].append((sec_day, val))

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
                norm_x = sec_day / 86400.0
                norm_x = max(0.0, min(1.0, norm_x))
                norm_y = (val - min_y) / (max_y - min_y)
                norm_y = max(0.0, min(1.0, norm_y))

                px = gx + int(gw * norm_x)
                py = gy + int(gh * (1.0 - norm_y))
                pts_array.append([px, py])

            pts_np = np.array(pts_array, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(canvas, [pts_np], isClosed=False, color=color, thickness=2, lineType=cv2.LINE_AA)
