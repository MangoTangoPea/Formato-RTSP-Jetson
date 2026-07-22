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
        'Board': [
            'tboard_tegra', 'tdiode_tegra', 'tdiode', 'board-thermal', 'board_thermal',
            'aux-thermal', 'aux_thermal', 'tboard', 'board', 'ambient', 'aux', 'pmic',
            'skin', 'temp_board', 'board_temp', 'thermal-est'
        ],
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

    def power_consumption(self) -> dict[str, float]:
        """
        Lee el consumo de potencia (en Watts) del hardware Jetson desde sysfs e i2c/hwmon (INA3221).

        Returns
        -------
        dict[str, float]
            {nombre_riel: potencia_watts}
        """
        powers: dict[str, float] = {}

        search_paths = (
            glob.glob('/sys/bus/i2c/drivers/ina3221/*') +
            glob.glob('/sys/devices/platform/*.ina3221/*') +
            glob.glob('/sys/devices/platform/*.i2c/i2c-*/*-004*') +
            glob.glob('/sys/class/hwmon/hwmon*')
        )

        for hwmon in set(search_paths):
            try:
                for power_in in glob.glob(os.path.join(hwmon, 'power*_input')) + \
                                glob.glob(os.path.join(hwmon, 'hwmon/hwmon*/power*_input')):
                    try:
                        val_str = open(power_in, 'r').read().strip()
                        val = float(val_str)
                    except (ValueError, OSError):
                        continue

                    label = ""
                    base_dir = os.path.dirname(power_in)
                    base_name = os.path.basename(power_in).replace('_input', '')
                    num_suffix = base_name.replace('power', '')

                    rail_files = glob.glob(os.path.join(base_dir, f'rail_name_{num_suffix}')) + \
                                 glob.glob(os.path.join(base_dir, f'in{num_suffix}_label'))
                    if rail_files and os.path.exists(rail_files[0]):
                        try:
                            label = open(rail_files[0]).read().strip()
                        except Exception:
                            pass

                    if not label:
                        label = base_name.upper()

                    if val > 100000:
                        val_w = val / 1000000.0
                    elif val > 100:
                        val_w = val / 1000.0
                    else:
                        val_w = val

                    if 0.01 <= val_w <= 200.0:
                        powers[label] = round(val_w, 2)

                if not powers:
                    for curr_in in glob.glob(os.path.join(hwmon, 'curr*_input')) + \
                                   glob.glob(os.path.join(hwmon, 'hwmon/hwmon*/curr*_input')):
                        in_in = curr_in.replace('curr', 'in')
                        if not os.path.exists(in_in):
                            continue
                        try:
                            curr_val = float(open(curr_in).read().strip())
                            in_val = float(open(in_in).read().strip())
                        except Exception:
                            continue

                        if in_val > 100:
                            in_val /= 1000.0
                        if curr_val > 1000:
                            curr_val /= 1000.0

                        p_watts = in_val * curr_val
                        if 0.01 <= p_watts <= 200.0:
                            label = os.path.basename(curr_in).replace('_input', '').upper()
                            powers[label] = round(p_watts, 2)
            except Exception:
                pass

        return powers

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

        # Potencia de consumo de energía
        powers = self.power_consumption()
        main_power: Optional[float] = None
        for main_rail in ['VDD_IN', 'POM_5V_IN', 'VDD_SYS_SOC', 'SYS_5V', 'MAIN', 'TOTAL', 'POWER1']:
            if main_rail in powers:
                main_power = powers[main_rail]
                break

        if main_power is None and powers:
            main_power = round(sum(powers.values()), 2)

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
            'jetson_powers': powers,
            'power_watts': main_power,
            'asic_temp': asic_temp,
            'datetime': now.isoformat(),
            'date_str': now.strftime('%d/%m/%Y'),
            'time_str': now.strftime('%H:%M:%S'),
            'resolution': f'{camera.width}x{camera.height}' if camera else f'{CAMERA_WIDTH}x{CAMERA_HEIGHT}',
            'fps_config': camera.fps_config if camera else CAMERA_FPS,
            'timestamp': time.time(),
        }
