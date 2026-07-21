#!/usr/bin/env python3
"""
Receptor RTP — Intel RealSense D435.

Recibe los 4 canales de video transmitidos por el Emisor mediante RTP/UDP,
muestra una interfaz responsive con vista simultánea 2x2 + panel de telemetría
lateral y gestiona la grabación local del mosaico completo como un solo archivo MP4.

Uso:
    python3 receiver.py --ip 192.168.1.XX
    python3 receiver.py --ip 192.168.1.XX --port 1043
"""

import sys
import signal
import argparse

from receiver_stream import VideoReceiver
from recorder import VideoRecorder
from gui import GUI
from config import UDP_PORT_BASE

_running: bool = True


def _handle_signal(signum, frame) -> None:
    global _running
    _running = False


def main() -> None:
    global _running

    parser = argparse.ArgumentParser(description="Receptor RTP - RealSense D435")
    parser.add_argument("--ip", required=True, help="IP del emisor (Jetson / PC con cámara)")
    parser.add_argument("--port", type=int, default=UDP_PORT_BASE, help="Puerto UDP base")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    receiver = None
    gui = None
    recorder = None

    try:
        receiver = VideoReceiver(sender_ip=args.ip, port_base=args.port)
        receiver.start()

        gui = GUI()
        recorder = VideoRecorder()

        print(f"Receptor conectando al emisor {args.ip}:{args.port}. "
              f"Presione 'R' para grabar, 'E' para detener, 'Q' para salir.")

        while _running:
            frames = receiver.get_frames()
            stats = receiver.get_stats()
            sync_info = receiver.get_sync_info()
            telemetry = receiver.get_telemetry()

            # Construir mosaico completo: panel telemetría + 2x2 (1540x960)
            mosaic = gui.build_mosaic(frames, stats, sync_info, telemetry)

            # Renderizar interfaz (escalado responsive)
            gui.render(
                mosaic=mosaic,
                recording=recorder.recording,
                rec_info=recorder.info,
            )

            # Escribir frame del mosaico en formato .mkv si se está grabando y el paquete síncrono está completo
            all_sync = all(frames.get(k) is not None for k in ['color', 'depth', 'ir_left', 'ir_right'])
            if recorder.recording and all_sync:
                recorder.write_frame(mosaic)

            # Capturar eventos de teclado
            action = gui.handle_input()

            if action == "start_rec" and not recorder.recording:
                info = gui.ask_recording_info()
                if info is not None:
                    base_dir, name = info
                    if recorder.start(base_dir, name):
                        print(f"[REC] Grabacion iniciada: {name}.mkv -> {base_dir}")
                    else:
                        print("[ERROR] No se pudo iniciar la grabacion", file=sys.stderr)

            elif action == "stop_rec" and recorder.recording:
                rec_name = recorder.record_name
                recorder.stop()
                print(f"[REC] Grabacion detenida: {rec_name}.mkv")

            elif action == "quit":
                break

    except Exception as e:
        print(f"Error en Receptor: {e}", file=sys.stderr)

    finally:
        if recorder and recorder.recording:
            recorder.stop()
        if receiver:
            receiver.close()
        if gui:
            gui.destroy()
        print("Receptor finalizado.")


if __name__ == "__main__":
    main()
