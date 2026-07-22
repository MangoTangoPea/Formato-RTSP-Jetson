#!/usr/bin/env python3
"""
TelemetryHistoryManager — Gestión e historial de telemetría y potencia de consumo.

Almacena registros diarios de consumo de energía y temperaturas en disco (telemetry_history.json),
purgando automáticamente datos con antigüedad superior al límite configurado (30 días).
Permite consultar únicamente los días pasados completados para visualización al día siguiente.
"""

import os
import json
import time
import datetime
import threading
from typing import List, Dict, Any, Optional

from config import TELEMETRY_HISTORY_FILE, TELEMETRY_RETENTION_DAYS


class TelemetryHistoryManager:
    """
    Administra el historial de telemetría y consumo de potencia de la Jetson.

    Mantiene la persistencia en disco y aplica el filtro de días pasados completados.
    """

    def __init__(
        self,
        filepath: str = TELEMETRY_HISTORY_FILE,
        retention_days: int = TELEMETRY_RETENTION_DAYS,
    ) -> None:
        self.filepath = filepath
        self.retention_seconds = retention_days * 86400.0
        self._lock = threading.Lock()
        self._records: List[Dict[str, Any]] = []
        self._last_save: float = 0.0

        # Cargar historial guardado y purgar datos antiguos
        self.load_from_file()

    def purge_old_records(self) -> None:
        """
        Elimina todos los registros cuya marca de tiempo supere los días de retención.
        """
        now = time.time()
        cutoff = now - self.retention_seconds
        self._records = [r for r in self._records if r.get('timestamp', 0.0) >= cutoff]

    def add_record(self, telemetry_data: Dict[str, Any]) -> None:
        """
        Agrega un nuevo registro de telemetría e invoca el guardado periódico en disco.

        Parameters
        ----------
        telemetry_data : dict
            Diccionario de telemetría recibido del emisor.
        """
        if not isinstance(telemetry_data, dict) or not telemetry_data:
            return

        ts = telemetry_data.get('timestamp', time.time())
        jetson_temps = telemetry_data.get('jetson_temps', {})
        asic_temp = telemetry_data.get('asic_temp')
        power_watts = telemetry_data.get('power_watts')
        jetson_powers = telemetry_data.get('jetson_powers', {})

        if power_watts is None and jetson_powers:
            power_watts = round(sum(v for v in jetson_powers.values() if v is not None), 2)

        time_str = telemetry_data.get('time_str', '')
        date_str = telemetry_data.get('date_str', '')

        if not date_str or not time_str:
            dt = datetime.datetime.fromtimestamp(ts)
            date_str = dt.strftime('%d/%m/%Y')
            time_str = dt.strftime('%H:%M:%S')

        record = {
            'timestamp': float(ts),
            'date_str': str(date_str),
            'time_str': str(time_str),
            'power': float(power_watts) if power_watts is not None else None,
            'asic_temp': float(asic_temp) if asic_temp is not None else None,
            'temps': {k: float(v) for k, v in jetson_temps.items() if v is not None},
        }

        with self._lock:
            # Evitar duplicados seguidos dentro de 0.5s
            if not self._records or (record['timestamp'] - self._records[-1]['timestamp']) >= 0.5:
                self._records.append(record)

            self.purge_old_records()

            # Guardar a disco periódicamente cada 10 segundos
            now = time.time()
            if now - self._last_save >= 10.0:
                self._save_to_file_locked()
                self._last_save = now

    def get_records(self) -> List[Dict[str, Any]]:
        """Retorna todos los registros actuales."""
        with self._lock:
            self.purge_old_records()
            return list(self._records)

    def get_completed_dates(self) -> List[str]:
        """
        Retorna la lista de fechas (DD/MM/YYYY) estrictamente ANTERIORES a la fecha de hoy.

        Garantiza que solo se puedan visualizar reportes de días pasados completados
        (al día siguiente).
        """
        today_str = datetime.datetime.now().strftime('%d/%m/%Y')

        with self._lock:
            dates = set()
            for r in self._records:
                d = r.get('date_str')
                if d and d != today_str:
                    dates.add(d)

            # Ordenar las fechas cronológicamente
            def _parse_date(d_str: str) -> datetime.datetime:
                try:
                    return datetime.datetime.strptime(d_str, '%d/%m/%Y')
                except ValueError:
                    return datetime.datetime.min

            sorted_dates = sorted(list(dates), key=_parse_date)
            return sorted_dates

    def get_records_for_date(self, target_date_str: str) -> List[Dict[str, Any]]:
        """
        Retorna únicamente los registros pertenecientes a la fecha especificada.

        Parameters
        ----------
        target_date_str : str
            Fecha en formato 'DD/MM/YYYY'.
        """
        with self._lock:
            return [r for r in self._records if r.get('date_str') == target_date_str]

    def _save_to_file_locked(self) -> None:
        """Guarda la lista de registros en disco (invocar bajo lock)."""
        try:
            temp_path = self.filepath + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self._records, f, separators=(',', ':'))
            os.replace(temp_path, self.filepath)
        except Exception:
            pass

    def save_to_file(self) -> None:
        """Guarda los registros en el archivo JSON."""
        with self._lock:
            self.purge_old_records()
            self._save_to_file_locked()

    def load_from_file(self) -> None:
        """Carga el historial desde el archivo JSON."""
        if not os.path.exists(self.filepath):
            return

        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, list):
                with self._lock:
                    self._records = data
                    self.purge_old_records()
        except Exception:
            self._records = []
