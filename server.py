#!/usr/bin/env python3
"""
Servidor RTP — Intel RealSense D435.

Captura 4 canales de la cámara y los transmite por UDP al cliente.
Espera a que un cliente se registre enviando un heartbeat al puerto
de control antes de comenzar a transmitir.

Uso:
    python3 server.py
    python3 server.py --port 1043
"""

import os
import sys
import signal
import time
import datetime
import argparse

import cv2
import numpy as np

from camera import RealSenseCamera
from stego_encoder_sender import VideoSender as VideoServer
from jetson_monitor import JetsonMonitor
from utils import pack_z16_to_bgr
from config import (
    UDP_PORT_BASE, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS,
    CHANNEL_COLOR, CHANNEL_DEPTH, CHANNEL_IR_LEFT, CHANNEL_IR_RIGHT,
    CONTROL_PORT_OFFSET, TELEMETRY_INTERVAL, RECORD_BAG_DIR,
)

# Flag para cierre limpio
_running: bool = True


def _handle_signal(signum, frame) -> None:
    """Maneja señales POSIX para cierre limpio."""
    global _running
    _running = False


def convert_ir(ir_raw: np.ndarray) -> np.ndarray:
    """
    Convierte IR Y8 a BGR.
    """
    return cv2.cvtColor(ir_raw, cv2.COLOR_GRAY2BGR)


def main() -> None:
    """Punto de entrada del servidor."""
    global _running

    parser = argparse.ArgumentParser(description="Servidor RTP - RealSense D435")
    parser.add_argument("--port", type=int, default=UDP_PORT_BASE, help="Puerto UDP base")
    parser.add_argument(
        "--record-bag",
        type=str,
        nargs="?",
        const="auto",
        default=None,
        help="Guardar grabación nativa de RealSense en formato .bag (ej. --record-bag o --record-bag mi_video.bag)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    camera = None
    server = None
    jetson = None

    bag_path = None
    if args.record_bag:
        os.makedirs(RECORD_BAG_DIR, exist_ok=True)
        if args.record_bag == "auto":
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            bag_path = os.path.join(RECORD_BAG_DIR, f"realsense_{ts}.bag")
        else:
            bag_path = args.record_bag
            if not bag_path.endswith(".bag"):
                bag_path += ".bag"
            if not os.path.isabs(bag_path) and not os.path.dirname(bag_path):
                bag_path = os.path.join(RECORD_BAG_DIR, bag_path)

    try:
        camera = RealSenseCamera(record_bag_path=bag_path)
        server = VideoServer(port_base=args.port)
        jetson = JetsonMonitor()

        control_port = args.port + CONTROL_PORT_OFFSET

        print(f"Servidor escuchando en puerto {args.port} "
              f"(control: {control_port}) | "
              f"{CAMERA_WIDTH}×{CAMERA_HEIGHT} @ {CAMERA_FPS}fps")
        if bag_path:
            print(f"Grabando en formato .bag (RealSense RAW): {bag_path}")
        print("Esperando cliente...")

        frame_id: int = 0
        last_telemetry: float = 0.0
        was_connected: bool = False

        while _running:
            # Verificar conexión del cliente
            if not server.receiver_connected:
                if was_connected:
                    print("Cliente desconectado. Esperando reconexión...")
                    was_connected = False
                time.sleep(0.1)
                continue

            if not was_connected:
                print(f"Servidor → {server.receiver_host}:{args.port} | "
                      f"{CAMERA_WIDTH}×{CAMERA_HEIGHT} @ {CAMERA_FPS}fps")
                was_connected = True

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

            # Empaquetado vectorizado de 16 bits sin pérdidas (<0.4ms en Jetson)
            depth_packed = pack_z16_to_bgr(depth_raw)
            ir_left_bgr = convert_ir(ir_left)
            ir_right_bgr = convert_ir(ir_right)

            # Enviar los 4 canales
            server.send_frame(CHANNEL_COLOR, color, frame_id, timestamp_ns)
            server.send_frame(CHANNEL_DEPTH, depth_packed, frame_id, timestamp_ns)
            server.send_frame(CHANNEL_IR_LEFT, ir_left_bgr, frame_id, timestamp_ns)
            server.send_frame(CHANNEL_IR_RIGHT, ir_right_bgr, frame_id, timestamp_ns)

            # Enviar telemetría cada TELEMETRY_INTERVAL segundos
            now = time.time()
            if now - last_telemetry >= TELEMETRY_INTERVAL:
                telemetry = jetson.get_telemetry(camera)
                server.send_telemetry(telemetry, frame_id)
                last_telemetry = now

    except RuntimeError as e:
        print(f"Error cámara: {e}", file=sys.stderr)
        sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    finally:
        if server:
            server.close()
        if camera:
            camera.stop()


if __name__ == "__main__":
    main()
