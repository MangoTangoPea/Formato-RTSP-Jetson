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

UDP_PORT_BASE: int = 5000
PACKET_MAGIC: bytes = b'RS4C'

# Header: magic(4) + frame_id(4) + timestamp_ns(8) + channel(1) +
#          frag_idx(1) + frag_total(1) + reserved(1) + data_len(4) + reserved2(8)
HEADER_FORMAT: str = '>4sIQBBBBI8s'
HEADER_SIZE: int = struct.calcsize(HEADER_FORMAT)  # 32 bytes
MAX_UDP_PAYLOAD: int = 60000  # bytes por fragmento

# ===========================================================================
# REGISTRO Y CONTROL (Receptor → Emisor)
# ===========================================================================

CONTROL_PORT_OFFSET: int = 10          # Puerto de control = port_base + 10
REGISTER_MAGIC: bytes = b'RGRQ'       # Magic para paquetes de registro
HEARTBEAT_INTERVAL: float = 2.0       # Segundos entre heartbeats del receptor
HEARTBEAT_TIMEOUT: float = 6.0        # Segundos sin heartbeat → pausa envío

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

# ===========================================================================
# CÁMARA (refleja RealSenseCamera — importada desde config)
# ===========================================================================

CAMERA_WIDTH: int = 1280
CAMERA_HEIGHT: int = 720
CAMERA_FPS: int = 30

# ===========================================================================
# TRANSMISIÓN
# ===========================================================================

JPEG_QUALITY: int = 88  # Calidad JPEG balanceada para 720p HD sin lag

# ===========================================================================
# GRABACIÓN
# ===========================================================================

RECORD_CODEC: str = 'mp4v'
RECORD_EXT: str = '.mp4'
RECORD_FPS: int = 30

# ===========================================================================
# MOSAICO (panel + 4 cámaras en 2x2)
# ===========================================================================

PANEL_WIDTH: int = 520                  # Ancho del panel lateral de telemetría (proporcional para 720p HD)
MOSAIC_WIDTH: int = CAMERA_WIDTH * 2 + PANEL_WIDTH   # 3080px para 720p HD
MOSAIC_HEIGHT: int = CAMERA_HEIGHT * 2               # 1440px para 720p HD
