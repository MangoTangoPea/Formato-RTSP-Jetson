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
- **Registro automático**: El Receptor se registra con el Emisor mediante heartbeats UDP. El Emisor no necesita conocer la IP del receptor de antemano.
- **Telemetría Jetson en tiempo real**: El emisor transmite las temperaturas de hardware de la Jetson (CPU, GPU, SOC, Board), temperatura ASIC de la cámara, fecha, hora y configuración de la cámara.
- **Panel lateral de información**: El receptor muestra un panel lateral izquierdo (260px) con toda la telemetría del emisor, replicando el estilo de `realsense_monitor_jetson.py`.
- **Interfaz responsive**: La ventana es completamente redimensionable y maximizable. El contenido se escala proporcionalmente sin espacios blancos, sin pérdida de calidad de imagen y con texto legible a cualquier tamaño.
- **Metadatos de sincronización**: Cada paquete transporta `frame_id`, `timestamp_ns` y `channel_id` en una cabecera binaria de 32 bytes para evitar desfases entre canales.
- **Grabación exclusiva en el Receptor**:
  - Se activa con `R` e interrumpe con `E`.
  - Cuadro de diálogo para **personalizar el nombre de la grabación** y seleccionar la carpeta destino.
  - Guarda **un solo archivo de grabación `.bag`** (ROS Bag v2.0) con el panel de telemetría + mosaico completo de las 4 cámaras integradas a resolución 1540×960 y metadatos de sincronización esteganografiados en la imagen.
- **Indicador visual de grabación**: Muestra un aviso de borde rojo y un círculo **REC** parpadeante en tiempo real en la GUI del receptor.
- **Tolerancia a fallos de red**: Si ocurren pérdidas de paquetes, el receptor continúa sin detenerse. Si el emisor se desconecta, el emisor pausa el envío y espera automáticamente reconexión.
- **Salida limpia en Emisor**: Logging mínimo sin mensajes largos e innecesarios.

---

## 📁 Estructura del Proyecto

```
.
├── camera.py                    # Conexión RealSense D435 (RealSenseCamera, sin modificar)
├── config.py                    # Constantes del protocolo, red, cámara, telemetría y grabación
├── steganography.py             # Esteganografía binaria en píxeles (fila 0) para metadatos de sincronización
├── utils.py                     # Funciones auxiliares de red y formato de timestamps
├── jetson_monitor.py            # Monitoreo de temperaturas Jetson (CPU, GPU, SOC, Board)
├── sender_stream.py             # Clase VideoSender (registro dinámico, compresión, cabeceras UDP)
├── sender.py                    # Programa principal del Emisor
├── receiver_stream.py           # Clase VideoReceiver (heartbeat, ensamble UDP, telemetría)
├── recorder.py                  # Clase VideoRecorder (escritura asíncrona del mosaico completo)
├── gui.py                       # Clase GUI (panel telemetría, mosaico 2x2, responsive, HUD, REC)
├── receiver.py                  # Programa principal del Receptor
├── realsense_monitor_jetson.py  # Monitor local original (referencia, no modificado)
├── requirements.txt             # Dependencias de Python
└── README.md                    # Documentación del proyecto
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

Conecta la Intel RealSense D435 e inicia el emisor. **No necesita IP del receptor**:

```bash
python3 sender.py
```

*Grabar transmisión nativa en formato `.bag` (ROS/RealSense):*

```bash
python3 sender.py --record-bag
# o indicando un nombre de archivo personalizado:
python3 sender.py --record-bag mi_grabacion.bag
```

*Opcional: cambiar el puerto base UDP (por defecto es 1043):*

```bash
python3 sender.py --port 1043
```

El emisor mostrará:
```text
Emisor escuchando en puerto 1043 (control: 1053) | 640×480 @ 30fps
Esperando receptor...
```

Cuando un receptor se conecte:
```text
Receptor registrado: 192.168.1.50
Emisor → 192.168.1.50:1043 | 640×480 @ 30fps
```

---

### 2. Ejecutar en el Computador Receptor (PC remoto)

Inicia el receptor **especificando la IP del emisor**:

```bash
python3 receiver.py --ip 192.168.1.XX
```

*Si cambiaste el puerto en el emisor, especifícalo aquí también:*

```bash
python3 receiver.py --ip 192.168.1.XX --port 1043
```

---

## 🎮 Controles de Teclado (Ventana Receptor)

| Tecla | Acción |
| :---: | --- |
| **`R`** | Abrir diálogo para **iniciar grabación** (permite editar nombre y carpeta). |
| **`E`** | **Detener grabación** actual. |
| **`Q`** / **`ESC`** | Salir y cerrar la aplicación de manera limpia. |

> **Nota**: La ventana es completamente redimensionable. Maximiza la ventana para ver todo el contenido en alta calidad.

---

## 🖥️ Interfaz del Receptor

La ventana del receptor muestra:

```
┌────────────────────────────┬──────────────────────┬──────────────────────┐
│  Intel RealSense D435      │                      │                      │
│  ─────────────────────     │        RGB           │       DEPTH          │
│  Fecha   21/07/2026        │                      │                      │
│  Hora    15:20:30          │                      │                      │
│  Resol.  640x480           ├──────────────────────┼──────────────────────┤
│  Config. 30 FPS            │                      │                      │
│  ASIC    42.5 C            │      IR LEFT         │      IR RIGHT        │
│                            │                      │                      │
│  Jetson                    │                      │                      │
│  CPU     45.2 C            │                      │                      │
│  GPU     43.1 C            │                      │                      │
│  SOC     44.0 C            │                      │                      │
│  Board   38.5 C            │                      │                      │
│                            │                      │                      │
│  Estado: Conectado ●       │                      │                      │
├────────────────────────────┴──────────────────────┴──────────────────────┤
│  Controles: [R] Iniciar Grabacion  |  [E] Detener Grabacion  |  [Q/ESC] │
└─────────────────────────────────────────────────────────────────────────┘
```

- **Panel lateral (260px)**: Muestra telemetría del emisor en tiempo real.
- **Mosaico 2x2 (1280px)**: Los 4 canales de la cámara con HUD (FPS, Frame ID, Timestamp).
- **Barra inferior**: Controles de teclado disponibles.

---

## 📂 Estructura de Salida de la Grabación

Al iniciar una grabación llamada `sesion_01`, se creará la siguiente estructura en la carpeta elegida:

```text
destino_seleccionado/
└── sesion_01/
    └── sesion_01.bag    <-- Archivo único ROS 1 Bag v2.0 (1540x960) con mosaico síncrono y metadatos esteganografiados
```

> **Nota**: El sistema graba directamente en formato **ROS 1 Bag (`.bag`)** en el tópico `/mosaic/compressed`. Cada frame incluye los metadatos de sincronización (`frame_id`, `timestamp_ns` y `channel_id`) **esteganografiados directamente dentro de los píxeles de la imagen**, sin necesidad de archivos `.csv` secundarios.

---

## 📡 Protocolo de Comunicación

### Flujo de Conexión

```
Receptor ──[REGISTER heartbeat]──> Emisor (puerto control = port_base + 10)
Emisor ──[UDP frames + telemetría]──> Receptor (IP aprendida del REGISTER)
```

1. El **Receptor** envía paquetes `REGISTER` (heartbeat) cada 2 segundos al Emisor.
2. El **Emisor** aprende la IP del receptor y comienza a enviar frames.
3. Si no recibe heartbeat por 6 segundos, el Emisor pausa el envío sin cerrarse.
4. Si el receptor se reconecta, la transmisión se reanuda automáticamente.

### Paquete de Registro (REGISTER)

| Offset | Campo | Tipo | Descripción |
| :---: | --- | :---: | --- |
| `0..3` | `magic` | 4 bytes | Identificador `RGRQ` |

### Header de Datos (32 bytes)

Cada fragmento de video o telemetría transmitido incluye la siguiente estructura binaria:

| Offset | Campo | Tipo | Descripción |
| :---: | --- | :---: | --- |
| `0..3` | `magic` | 4 bytes | Identificador `RS4C` |
| `4..7` | `frame_id` | uint32 | ID secuencial del frame |
| `8..15` | `timestamp_ns` | uint64 | Timestamp del reloj emisor (ns) |
| `16` | `channel_id` | uint8 | Canal: `0`=Color, `1`=Depth, `2`=IR Left, `3`=IR Right, `10`=Telemetría |
| `17` | `frag_idx` | uint8 | Índice del fragmento |
| `18` | `frag_total` | uint8 | Cantidad total de fragmentos |
| `19..31` | `reserved` | 13 bytes | Reservado para uso futuro / alineación |

### Canal de Telemetría (canal 10)

El emisor envía datos de telemetría cada ~1 segundo como un paquete JSON en el canal 10:

```json
{
  "jetson_temps": {"CPU": 45.2, "GPU": 43.1, "SOC": 44.0, "Board": 38.5},
  "asic_temp": 42.5,
  "date_str": "21/07/2026",
  "time_str": "15:20:30",
  "resolution": "640x480",
  "fps_config": 30,
  "timestamp": 1753127430.0
}
```

### Puertos UDP

| Puerto | Uso |
| :---: | --- |
| `port_base + 0` | Canal Color |
| `port_base + 1` | Canal Depth |
| `port_base + 2` | Canal IR Left |
| `port_base + 3` | Canal IR Right |
| `port_base + 10` | Canal Telemetría / Puerto de Control (REGISTER) |
