#!/usr/bin/env python3
"""
Configuración central del proyecto Emisor-Receptor RTP.

Todas las constantes del protocolo, cámara, transmisión y grabación
centralizadas en un solo lugar.
"""

import struct

# ===========================================================================
# PROTOCOLO UDP
# ===========================================================================

UDP_PORT_BASE: int = 1043
PACKET_MAGIC: bytes = b'RS4C'

# Header: magic(4) + frame_id(4) + timestamp_ns(8) + channel(1) +
#          frag_idx(1) + frag_total(1) + reserved(1) + data_len(4) + reserved2(8)
HEADER_FORMAT: str = '>4sIQBBBBI8s'
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 32 bytes
MAX_UDP_PAYLOAD: int = 1200  # 60000bytes por fragmento

# ===========================================================================
# REGISTRO Y CONTROL (Receptor → Emisor)
# ===========================================================================

CONTROL_PORT_OFFSET: int = 10          # Puerto de control = port_base + 10
REGISTER_MAGIC: bytes = b'RGRQ'       # Magic para paquetes de registro
HEARTBEAT_INTERVAL: float = 2.0       # Segundos entre heartbeats del receptor
HEARTBEAT_TIMEOUT: float = 6.0        # Segundos sin heartbeat → pausa envío

# ===========================================================================
# HOLE PUNCHING (Receptor → Emisor, por cada socket de canal)
# ===========================================================================
# Paquete corto que el receptor manda de forma CONTINUA hacia cada puerto de
# canal (video y telemetría) del emisor, usando el mismo socket que escucha
# esos puertos. El objetivo es que un firewall con estado (FortiGate) vea
# tráfico saliente reciente en ese puerto/sesión y así permita el tráfico
# de retorno (los frames reales) sin descartarlo como "no solicitado".
# No requiere respuesta del emisor: el emisor simplemente descarta/drena
# estos paquetes (ver _drain_loop en stego_encoder_sender.py).
PUNCH_MAGIC: bytes = b'PNCH'
PUNCH_INTERVAL: float = 1.0           # Segundos entre punches (igual de agresivo que el heartbeat)

# ===========================================================================
# CANALES
# ===========================================================================

CHANNEL_COLOR: int = 0
CHANNEL_DEPTH: int = 1
CHANNEL_IR_LEFT: int = 2
CHANNEL_IR_RIGHT: int = 3
CHANNEL_TELEMETRY: int = 11            # Canal de telemetría Jetson (port_base + 11)

CHANNELS: dict[int, str] = {
    CHANNEL_COLOR: 'color',
    CHANNEL_DEPTH: 'depth',
    CHANNEL_IR_LEFT: 'ir_left',
    CHANNEL_IR_RIGHT: 'ir_right',
}

# ===========================================================================
# TELEMETRÍA
# ===========================================================================

TELEMETRY_INTERVAL: float = 1.0        # Segundos entre paquetes de telemetría
TELEMETRY_HISTORY_FILE: str = "telemetry_history.json"  # Archivo local del historial de potencia
TELEMETRY_RETENTION_DAYS: int = 30     # Retención de historial de potencia (30 días)
SAVE_TELEMETRY_TO_DISK: bool = False   # False = Mantiene el historial 100% en RAM sin crear ni modificar JSON en disco/Git

# ===========================================================================
# CÁMARA (refleja RealSenseCamera — importada desde config)
# ===========================================================================

CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720
CAMERA_FPS: int = 30

# ===========================================================================
# TRANSMISIÓN Y COMPRESIÓN POR CANAL
# ===========================================================================

JPEG_QUALITY: int = 88          # Calidad JPEG balanceada para canales de color (0-100)
PNG_COMPRESSION: int = 1        # Nivel de compresión PNG (1 = ultra rápido, bajo consumo CPU Jetson)
LOSSLESS_DEPTH: bool = False    # False: Transmisión fluida JPEG (evita saturar el socket UDP/VPN y caída de imagen)
LOSSLESS_IR: bool = False       # False = JPEG rápido en IR (recomendado en Jetson), True = PNG sin pérdidas (mayor ancho de banda)

# ===========================================================================
# GRABACIÓN
# ===========================================================================

RECORD_EXT: str = '.db3'        # Base de datos SQLite3 única con canal de profundidad 16-bit (Z16) puro
RECORD_FPS: int = 30
RECORD_BAG_DIR: str = 'recordings'

# ===========================================================================
# MOSAICO (panel + 4 cámaras en 2x2)
# ===========================================================================

PANEL_HEIGHT: int = 120                  # Alto del panel superior de telemetría (rectángulo sobre cámaras)
MOSAIC_WIDTH: int = CAMERA_WIDTH * 2     # 2560px para 720p HD (ancho completo 2x2)
MOSAIC_HEIGHT: int = CAMERA_HEIGHT * 2 + PANEL_HEIGHT   # 1440 + 120 = 1560px para 720p HD
