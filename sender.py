#!/usr/bin/env python3
"""
Emisor RTP — Intel RealSense D435.

Captura 4 canales de la cámara y los transmite por UDP al receptor.

Uso:
    python3 sender.py --ip 192.168.1.XX
    python3 sender.py --ip 192.168.1.XX --port 5000
"""

import sys
import signal
import time
import argparse

import cv2
import numpy as np

from camera import RealSenseCamera
from sender_stream import VideoSender
from config import (
    UDP_PORT_BASE, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS,
    CHANNEL_COLOR, CHANNEL_DEPTH, CHANNEL_IR_LEFT, CHANNEL_IR_RIGHT,
)

# Flag para cierre limpio
_running: bool = True


def _handle_signal(signum, frame) -> None:
    """Maneja señales POSIX para cierre limpio."""
    global _running
    _running = False


def convert_depth(depth_raw: np.ndarray) -> np.ndarray:
    """
    Convierte depth Z16 a heatmap JET BGR.

    Usa el mismo método que DisplayManager.convert_depth() del original.
    """
    depth_8bit = cv2.convertScaleAbs(depth_raw, alpha=0.03)
    return cv2.applyColorMap(depth_8bit, cv2.COLORMAP_JET)


def convert_ir(ir_raw: np.ndarray) -> np.ndarray:
    """
    Convierte IR Y8 a BGR.

    Usa el mismo método que DisplayManager.convert_ir() del original.
    """
    return cv2.cvtColor(ir_raw, cv2.COLOR_GRAY2BGR)


def main() -> None:
    """Punto de entrada del emisor."""
    global _running

    parser = argparse.ArgumentParser(description="Emisor RTP - RealSense D435")
    parser.add_argument("--ip", required=True, help="IP del receptor")
    parser.add_argument("--port", type=int, default=UDP_PORT_BASE, help="Puerto UDP base")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    camera = None
    sender = None

    try:
        camera = RealSenseCamera()
        sender = VideoSender(args.ip, args.port)

        print(f"Emisor → {args.ip}:{args.port} | "
              f"{CAMERA_WIDTH}×{CAMERA_HEIGHT} @ {CAMERA_FPS}fps")

        frame_id: int = 0

        while _running:
            frames = camera.get_frames()
            if not all(frames):
                continue

            color_f, depth_f, ir_left_f, ir_right_f = frames
            timestamp_ns = time.time_ns()
            frame_id += 1

            # Convertir a numpy arrays
            color = np.asanyarray(color_f.get_data())
            depth_raw = np.asanyarray(depth_f.get_data())
            ir_left = np.asanyarray(ir_left_f.get_data())
            ir_right = np.asanyarray(ir_right_f.get_data())

            # Procesar depth e IR
            depth_color = convert_depth(depth_raw)
            ir_left_bgr = convert_ir(ir_left)
            ir_right_bgr = convert_ir(ir_right)

            # Enviar los 4 canales
            sender.send_frame(CHANNEL_COLOR, color, frame_id, timestamp_ns)
            sender.send_frame(CHANNEL_DEPTH, depth_color, frame_id, timestamp_ns)
            sender.send_frame(CHANNEL_IR_LEFT, ir_left_bgr, frame_id, timestamp_ns)
            sender.send_frame(CHANNEL_IR_RIGHT, ir_right_bgr, frame_id, timestamp_ns)

    except RuntimeError as e:
        print(f"Error cámara: {e}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        if sender:
            sender.close()
        if camera:
            camera.stop()


if __name__ == "__main__":
    main()
