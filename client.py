#!/usr/bin/env python3
"""
Cliente RTP — Intel RealSense D435.

Recibe los 4 canales de video transmitidos por el Servidor mediante RTP/UDP,
muestra una interfaz responsive con vista simultánea 2x2 + panel de telemetría
y gestiona la grabación local del mosaico completo como un solo archivo MKV organizados por etiquetas.

Uso:
    python3 client.py --ip 192.168.1.XX
    python3 client.py --ip 192.168.1.XX --port 1043
"""

import os
import sys
import signal
import shutil
import datetime
import threading
import argparse
import cv2

from stego_decoder_receiver import VideoReceiver as VideoClient
from recorder import VideoRecorder
from gui import GUI
from config import UDP_PORT_BASE
from telemetry_history import TelemetryHistoryManager
from telemetry_charts import TelemetryChartRenderer

_running: bool = True


def _handle_signal(signum, frame) -> None:
    global _running
    _running = False


def main() -> None:
    global _running

    parser = argparse.ArgumentParser(description="Cliente RTP - RealSense D435")
    parser.add_argument("--ip", required=True, help="IP del servidor (Jetson / PC con cámara)")
    parser.add_argument("--port", type=int, default=UDP_PORT_BASE, help="Puerto UDP base")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    client = None
    gui = None
    recorder = None
    history_manager = None
    chart_renderer = None
    show_dashboard = False

    try:
        client = VideoClient(sender_ip=args.ip, port_base=args.port)
        client.start()

        gui = GUI()
        recorder = VideoRecorder()
        history_manager = TelemetryHistoryManager()
        chart_renderer = TelemetryChartRenderer()

        print(f"Cliente conectando al servidor {args.ip}:{args.port}. "
              f"Presione 'R' para iniciar grabación, 'E' para detener y guardar por etiquetas, 'D' para Dashboard de consumo, 'Q' para salir.")

        while _running:
            frames = client.get_frames()
            stats = client.get_stats()
            sync_info = client.get_sync_info()
            telemetry = client.get_telemetry()

            # Guardar telemetría y consumo de potencia en el historial
            if telemetry:
                history_manager.add_record(telemetry)

            # Construir mosaico completo: panel telemetría + 2x2 (1540x960)
            mosaic = gui.build_mosaic(frames, stats, sync_info, telemetry)

            # Renderizar interfaz (escalado responsive)
            gui.render(
                mosaic=mosaic,
                recording=recorder.recording,
                rec_info=recorder.info,
            )

            # Si el Dashboard está activo, renderizar diagramas de líneas en ventana flotante redimensionable
            if show_dashboard:
                cv2.namedWindow(
                    chart_renderer.window_name,
                    cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO | cv2.WINDOW_GUI_NORMAL
                )
                dash_canvas = chart_renderer.render_dashboard(history_manager)
                cv2.imshow(chart_renderer.window_name, dash_canvas)

            # Escribir frame del mosaico en formato .mkv si se está grabando y el paquete síncrono está completo
            all_sync = all(frames.get(k) is not None for k in ['color', 'depth', 'ir_left', 'ir_right'])
            if recorder.recording and all_sync:
                recorder.write_frame(mosaic)

            # Capturar eventos de teclado
            action = gui.handle_input()

            if action == "start_rec" and not recorder.recording:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                auto_name = f"temp_rec_{timestamp}"
                auto_dir = os.path.abspath("./grabaciones")
                if recorder.start(auto_dir, auto_name):
                    print(f"[REC] Grabación iniciada...")
                else:
                    print("[ERROR] No se pudo iniciar la grabación", file=sys.stderr)

            elif action == "stop_rec" and recorder.recording:
                temp_path = recorder.video_path
                total_frames = recorder.frames_recorded
                recorder.stop()
                print(f"[REC] Grabación finalizada ({total_frames} frames). Ingrese la etiqueta para guardar...")

                def _save_task(t_path: str) -> None:
                    tag_info = gui.ask_recording_tag(base_dir="./grabaciones")
                    if tag_info is not None:
                        target_dir, final_name, tag_clean = tag_info
                        target_path = os.path.join(target_dir, f"{final_name}.mkv")
                        try:
                            os.makedirs(target_dir, exist_ok=True)
                            if os.path.abspath(t_path) != os.path.abspath(target_path):
                                shutil.move(t_path, target_path)
                            print(f"\n[REC] Grabación guardada exitosamente en carpeta '{tag_clean}': {target_path}")
                        except Exception as err:
                            print(f"\n[ERROR] No se pudo mover el archivo de grabación a {target_path}: {err}", file=sys.stderr)
                    else:
                        print(f"\n[REC] Guardado cancelado. La grabación se conserva en: {t_path}")

                save_thread = threading.Thread(
                    target=_save_task,
                    args=(temp_path,),
                    name="SaveRecordingDialog",
                    daemon=True,
                )
                save_thread.start()

            elif action == "toggle_dashboard":
                show_dashboard = not show_dashboard
                if not show_dashboard:
                    try:
                        cv2.destroyWindow(chart_renderer.window_name)
                    except Exception:
                        pass
                else:
                    print("[DASHBOARD] Mostrando diagramas de consumo de energía y telemetría.")

            elif action == "save_dashboard" and show_dashboard:
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                save_dir = os.path.abspath("./grabaciones")
                os.makedirs(save_dir, exist_ok=True)
                save_path = os.path.join(save_dir, f"dashboard_potencia_{timestamp}.png")
                dash_canvas = chart_renderer.render_dashboard(history_manager)
                cv2.imwrite(save_path, dash_canvas)
                chart_renderer.notify_saved(save_path)
                print(f"[DASHBOARD] Imagen del gráfico guardada exitosamente en: {save_path}")

            elif action == "prev_date" and show_dashboard:
                chart_renderer.selected_date_index = max(0, chart_renderer.selected_date_index - 1)

            elif action == "quit":
                break

    except Exception as e:
        print(f"Error en Cliente: {e}", file=sys.stderr)

    finally:
        if history_manager:
            history_manager.save_to_file()
        if recorder and recorder.recording:
            recorder.stop()
        if client:
            client.close()
        if gui:
            gui.destroy()
        print("Cliente finalizado.")


if __name__ == "__main__":
    main()
