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
# CANALES
# ===========================================================================

CHANNEL_COLOR: int = 0
CHANNEL_DEPTH: int = 1
CHANNEL_IR_LEFT: int = 2
CHANNEL_IR_RIGHT: int = 3

CHANNELS: dict[int, str] = {
    CHANNEL_COLOR: 'color',
    CHANNEL_DEPTH: 'depth',
    CHANNEL_IR_LEFT: 'ir_left',
    CHANNEL_IR_RIGHT: 'ir_right',
}

# ===========================================================================
# CÁMARA (refleja RealSenseCamera — NO modificar)
# ===========================================================================

CAMERA_WIDTH: int = 640
CAMERA_HEIGHT: int = 480
CAMERA_FPS: int = 30

# ===========================================================================
# TRANSMISIÓN
# ===========================================================================

JPEG_QUALITY: int = 85  # calidad JPEG para transmisión

# ===========================================================================
# GRABACIÓN
# ===========================================================================

RECORD_CODEC: str = 'MJPG'
RECORD_FPS: int = 30
