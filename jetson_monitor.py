#!/usr/bin/env python3
"""
JetsonMonitor — Monitoreo de temperaturas del hardware Jetson.

Lee los sensores térmicos de la Jetson (CPU, GPU, SOC, Board) desde sysfs y hwmon,
soportando todas las versiones de JetPack (4, 5, 6) y modelos (Nano, TX2, Xavier, Orin).
"""

import os
import glob
import time
import datetime
from typing import Optional
from config import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS


class JetsonMonitor:
    """
    Lee temperaturas de la Jetson desde /sys/class/thermal/thermal_zone* o /sys/class/hwmon/*.

    En sistemas no-Jetson (Windows, x86 Linux) retorna diccionarios vacíos o simulados.
    """

    # Palabras clave para mapeo flexible de sensores
    CATEGORY_KEYWORDS: dict[str, list[str]] = {
        'CPU': ['cpu-therm', 'cpu-thermal', 'cpu_thermal', 'cpu'],
        'GPU': ['gpu-therm', 'gpu-thermal', 'gpu_thermal', 'gpu'],
        'SOC': ['soc0-therm', 'soc-thermal', 'soc_thermal', 'tj-thermal', 'soc', 'tj'],
        'Board': ['tboard_tegra', 'board-thermal', 'aux-thermal', 'tboard', 'board', 'ambient', 'aux'],
    }

    def __init__(self) -> None:
        pass

    def temperatures(self) -> dict[str, float]:
        """
        Lee todas las temperaturas disponibles de sysfs.

        Returns
        -------
        dict[str, float]
            {nombre_raw_sensor: temperatura_celsius}
        """
        result: dict[str, float] = {}

        # 1. Escanear /sys/class/thermal/thermal_zone*
        thermal_paths = glob.glob('/sys/class/thermal/thermal_zone*') + glob.glob('/sys/devices/virtual/thermal/thermal_zone*')
        for path in set(thermal_paths):
            try:
                type_file = os.path.join(path, 'type')
                temp_file = os.path.join(path, 'temp')

                if os.path.exists(type_file) and os.path.exists(temp_file):
                    with open(type_file, 'r') as tf:
                        sensor_type = tf.read().strip()
                    with open(temp_file, 'r') as f:
                        val_str = f.read().strip()

                    val = float(val_str)
                    if val > 1000:
                        val /= 1000.0

                    if 0.0 < val < 130.0:
                        result[sensor_type] = round(val, 1)
            except Exception:
                pass

        # 2. Escanear hwmon si no se encontraron zonas térmicas
        if not result:
            for hwmon in glob.glob('/sys/class/hwmon/hwmon*'):
                try:
                    for temp_in in glob.glob(os.path.join(hwmon, 'temp*_input')):
                        val_str = open(temp_in).read().strip()
                        val = float(val_str)
                        if val > 1000:
                            val /= 1000.0
                        if 0.0 < val < 130.0:
                            label_file = temp_in.replace('_input', '_label')
                            if os.path.exists(label_file):
                                label = open(label_file).read().strip()
                            else:
                                label = os.path.basename(temp_in)
                            result[label] = round(val, 1)
                except Exception:
                    pass

        return result

    def get_telemetry(self, camera=None) -> dict:
        """
        Recopila todos los datos de telemetría para transmitir al receptor.

        Parameters
        ----------
        camera : RealSenseCamera, optional
            Instancia de la cámara para leer la temperatura ASIC.

        Returns
        -------
        dict
            Métricas de telemetría mapeadas.
        """
        temps = self.temperatures()
        jetson_temps: dict[str, Optional[float]] = {}

        # Mapeo difuso inteligente por categorías
        for cat_name, keywords in self.CATEGORY_KEYWORDS.items():
            matched_temp: Optional[float] = None
            for sys_type, temp_val in temps.items():
                sys_lower = sys_type.lower()
                if any(kw in sys_lower for kw in keywords):
                    matched_temp = temp_val
                    break
            jetson_temps[cat_name] = matched_temp

        # Fallback: si no se emparejó ninguna categoría pero hay sensores, usar los sensores encontrados
        if not any(v is not None for v in jetson_temps.values()) and temps:
            for sys_type, temp_val in temps.items():
                clean_name = sys_type.replace('_thermal', '').replace('-thermal', '').replace('-therm', '').upper()
                jetson_temps[clean_name] = temp_val

        # Temperatura ASIC de la RealSense
        asic_temp: Optional[float] = None
        if camera is not None:
            try:
                import pyrealsense2 as rs
                if hasattr(camera, 'depth_sensor') and camera.depth_sensor:
                    asic_temp = float(camera.depth_sensor.get_option(rs.option.asic_temperature))
            except Exception:
                pass

        now = datetime.datetime.now()

        return {
            'jetson_temps': jetson_temps,
            'asic_temp': asic_temp,
            'datetime': now.isoformat(),
            'date_str': now.strftime('%d/%m/%Y'),
            'time_str': now.strftime('%H:%M:%S'),
            'resolution': f'{camera.width}x{camera.height}' if camera else f'{CAMERA_WIDTH}x{CAMERA_HEIGHT}',
            'fps_config': camera.fps_config if camera else CAMERA_FPS,
            'timestamp': time.time(),
        }
