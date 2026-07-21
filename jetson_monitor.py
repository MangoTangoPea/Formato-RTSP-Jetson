#!/usr/bin/env python3
"""
JetsonMonitor — Monitoreo de temperaturas del hardware Jetson.

Extraído de realsense_monitor_jetson.py. Lee los sensores térmicos
de la Jetson (CPU, GPU, SOC, Board) desde sysfs.
"""

import glob
import time
import datetime
from config import CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS


class JetsonMonitor:
    """
    Lee temperaturas de la Jetson desde /sys/class/thermal/thermal_zone*.

    En sistemas no-Jetson (Windows, x86 Linux) los sensores no estarán
    disponibles y se retornarán diccionarios vacíos.
    """

    # Mapeo de nombre sysfs → nombre legible para el panel
    SENSOR_MAP: list[tuple[str, str]] = [
        ('CPU-therm', 'CPU'),
        ('GPU-therm', 'GPU'),
        ('SOC0-therm', 'SOC'),
        ('Tboard_tegra', 'Board'),
    ]

    def __init__(self) -> None:
        self.sensors: dict[str, str] = {}
        for path in glob.glob('/sys/class/thermal/thermal_zone*'):
            try:
                name = open(path + '/type').read().strip()
                self.sensors[name] = path + '/temp'
            except Exception:
                pass

    def temperatures(self) -> dict[str, float]:
        """
        Lee todas las temperaturas disponibles.

        Returns
        -------
        dict[str, float]
            {nombre_sensor: temperatura_celsius}
        """
        result: dict[str, float] = {}
        for name, filepath in self.sensors.items():
            try:
                result[name] = int(open(filepath).read()) / 1000.0
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
            Diccionario con todas las métricas de telemetría:
            - 'jetson_temps': {CPU: float, GPU: float, SOC: float, Board: float}
            - 'asic_temp': float | None
            - 'datetime': str (ISO format)
            - 'resolution': str ('640x480')
            - 'fps_config': int
            - 'timestamp': float (epoch seconds)
        """
        temps = self.temperatures()

        # Mapear a nombres legibles
        jetson_temps: dict[str, Optional[float]] = {}
        for sysfs_name, display_name in self.SENSOR_MAP:
            jetson_temps[display_name] = temps.get(sysfs_name)

        # Temperatura ASIC de la RealSense
        asic_temp: Optional[float] = None
        if camera is not None:
            try:
                import pyrealsense2 as rs
                asic_temp = camera.depth_sensor.get_option(rs.option.asic_temperature)
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
