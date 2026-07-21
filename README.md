# Transmisión Multicanal RTP/UDP — Intel RealSense D435

Sistema modular Emisor-Receptor para la captura, transmisión síncrona por red UDP/RTP, visualización en tiempo real y grabación multicanal de una cámara **Intel RealSense D435** entre dos computadores con Ubuntu / Jetson Linux.

---

## 📌 Características

- **Conexión RealSense intacta**: Mantiene exactamente la inicialización original de streams (640×480 @ 30 FPS en BGR8, Z16 e Y8).
- **Transmisión síncrona de 4 canales**:
  1. Color (RGB)
  2. Profundidad (Depth Heatmap JET)
  3. Infrarrojo Izquierdo (IR Left)
  4. Infrarrojo Derecho (IR Right)
- **Metadatos de sincronización**: Cada paquete transporta `frame_id`, `timestamp_ns` y `channel_id` en una cabecera binaria de 32 bytes para evitar desfases entre canales.
- **Grabación exclusiva en el Receptor**:
  - Se activa con `R` e interrumpe con `E`.
  - Cuadro de diálogo para **personalizar el nombre de la grabación** y seleccionar la carpeta destino.
  - Guarda 4 archivos `.avi` independientes (codec MJPG) dentro de subcarpetas separadas (`Color/`, `Depth/`, `IR_Left/`, `IR_Right/`) junto con su archivo `metadata.csv`.
- **Indicador visual de grabación**: Muestra un aviso de borde rojo y un círculo **REC** parpadeante en tiempo real en la GUI del receptor.
- **Tolerancia a fallos de red**: Si ocurren pérdidas de paquetes, el receptor continúa sin detenerse y espera automáticamente si el emisor se desconecta o reinicia.
- **Salida limpia en Emisor**: Logging mínimo sin mensajes largos e innecesarios.

---

## 📁 Estructura del Proyecto

```
.
├── camera.py           # Conexión RealSense D435 (RealSenseCamera, sin modificar)
├── config.py           # Constantes del protocolo, red, cámara y grabación
├── utils.py            # Funciones auxiliares de red y formato de timestamps
├── sender_stream.py    # Clase VideoSender (compresión, cabeceras y sockets UDP)
├── sender.py           # Programa principal del Emisor
├── receiver_stream.py  # Clase VideoReceiver (recolección, ensamble UDP y decodificación)
├── recorder.py         # Clase VideoRecorder (escritura asíncrona multicanal en disco)
├── gui.py              # Clase GUI (mosaico 2x2, HUD, indicador REC y cuadros diálogo Tkinter)
├── receiver.py         # Programa principal del Receptor
├── requirements.txt    # Dependencias de Python
└── README.md           # Documentación del proyecto
```

---

## ⚙️ Requisitos e Instalación

### 1. Dependencias del Sistema (Ubuntu / Linux Jetson)

```bash
sudo apt update
sudo apt install -y python3-pip python3-tk libgl1-mesa-glx libglib2.0-0
```

### 2. Dependencias de Python

```bash
pip install -r requirements.txt
```

> **Nota**: `pyrealsense2` debe estar instalado en el equipo **Emisor** que tiene conectada la cámara física Intel RealSense D435.

---

## 🚀 Uso del Sistema

### 1. Ejecutar en el Computador Emisor (Jetson / PC con cámara)

Conecta la Intel RealSense D435 e inicia el servicio especificando la IP de la máquina receptora:

```bash
python3 sender.py --ip 192.168.1.50
```

*Opcional: cambiar el puerto base UDP (por defecto es 5000):*

```bash
python3 sender.py --ip 192.168.1.50 --port 5000
```

El emisor mostrará únicamente una línea limpia confirmando la transmisión:
```text
Emisor → 192.168.1.50:5000 | 640×480 @ 30fps
```

---

### 2. Ejecutar en el Computador Receptor (PC remoto / Antigravity Agent)

Inicia el receptor en la máquina que mostrará la interfaz y grabará el video:

```bash
python3 receiver.py
```

*Si cambiaste el puerto en el emisor, especifícalo aquí también:*

```bash
python3 receiver.py --port 5000
```

---

## 🎮 Controles de Teclado (Ventana Receptor)

| Tecla | Acción |
| :---: | --- |
| **`R`** | Abrir diálogo para **iniciar grabación** (permite editar nombre y carpeta). |
| **`E`** | **Detener grabación** actual. |
| **`Q`** / **`ESC`** | Salir y cerrar la aplicación de manera limpia. |

---

## 📂 Estructura de Salida de la Grabación

Al iniciar una grabación llamada `sesion_01`, se creará la siguiente estructura en la carpeta elegida:

```text
destino_seleccionado/
└── sesion_01/
    ├── Color/
    │   └── color.avi
    ├── Depth/
    │   └── depth.avi
    ├── IR_Left/
    │   └── ir_left.avi
    ├── IR_Right/
    │   └── ir_right.avi
    └── metadata.csv
```

El archivo `metadata.csv` registra por cada frame grabado: `frame_id`, `timestamp_ns` y `timestamp_utc`.

---

## 📡 Detalle del Protocolo UDP (Header de 32 Bytes)

Cada fragmento transmitido por la red incluye la siguiente estructura binaria:

| Offset | Campo | Tipo | Descripción |
| :---: | --- | :---: | --- |
| `0..3` | `magic` | 4 bytes | Identificador `RS4C` |
| `4..7` | `frame_id` | uint32 | ID secuencial del frame |
| `8..15` | `timestamp_ns` | uint64 | Timestamp del reloj emisor (ns) |
| `16` | `channel_id` | uint8 | Canal: `0`=Color, `1`=Depth, `2`=IR Left, `3`=IR Right |
| `17` | `frag_idx` | uint8 | Índice del fragmento |
| `18` | `frag_total` | uint8 | Cantidad total de fragmentos |
| `19..31` | `reserved` | 13 bytes | Reservado para uso futuro / alineación |
