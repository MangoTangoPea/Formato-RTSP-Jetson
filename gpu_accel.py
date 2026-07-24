#!/usr/bin/env python3
"""
gpu_accel.py — Aceleración GPU centralizada para Emisor y Receptor.

Detecta automáticamente qué backends GPU están disponibles y expone
funciones optimizadas con fallback transparente a CPU:

  Backend A — OpenCV CUDA  (cv2.cuda)
    · Disponible en: Jetson con JetPack, PC con OpenCV compilado con CUDA
    · Operaciones: imdecode, resize, applyColorMap, cvtColor
    · Requerimiento: OpenCV compilado con soporte CUDA (-DWITH_CUDA=ON)
                     y al menos 1 dispositivo CUDA en el sistema.

  Backend B — CuPy
    · Disponible en: cualquier sistema con GPU NVIDIA y CuPy instalado
    · Operaciones: empaquetado/desempaquetado canal Depth (arrays numéricos)
    · Instalación:
        pip install cupy-cuda12x   # CUDA 12.x  (PC con RTX, Jetson JetPack 6)
        pip install cupy-cuda11x   # CUDA 11.x  (Jetson JetPack 5)

Los dos backends son independientes: puede haber uno, ambos o ninguno.
En ausencia de GPU se usan NumPy / OpenCV CPU sin ningún cambio de API.

Uso típico:
    from gpu_accel import GpuAccel
    accel = GpuAccel()            # detecta backends al instanciar
    frame = accel.imdecode(buf)   # GPU si hay CUDA, CPU si no
    resized = accel.resize(frame, (w, h))
"""

from __future__ import annotations

import numpy as np
import cv2
from typing import Optional, Tuple


# ---------------------------------------------------------------------------
# Detección silenciosa de backends — no lanza excepciones al importar
# ---------------------------------------------------------------------------

def _detect_opencv_cuda() -> bool:
    """True si OpenCV fue compilado con CUDA y hay al menos 1 GPU disponible."""
    try:
        return cv2.cuda.getCudaEnabledDeviceCount() > 0
    except Exception:
        return False


def _detect_cupy() -> bool:
    """True si CuPy está instalado y hay dispositivo CUDA disponible."""
    try:
        import cupy as cp
        cp.cuda.runtime.getDeviceCount()
        cp.array([1])  # Prueba básica de asignación
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Clase principal
# ---------------------------------------------------------------------------

class GpuAccel:
    """
    Aceleradora GPU unificada para operaciones de imagen en la pipeline RTP.

    Detecta automáticamente los backends disponibles al instanciarse.
    Todas las entradas y salidas son siempre np.ndarray en CPU (host memory)
    para compatibilidad directa con el resto del código.

    Parameters
    ----------
    verbose : bool
        Si True, imprime el resumen de backends al instanciar.
    """

    def __init__(self, verbose: bool = True) -> None:
        self._cv_cuda: bool = _detect_opencv_cuda()
        self._cupy: bool = _detect_cupy()

        if self._cupy:
            import cupy as cp
            self._cp = cp
        else:
            self._cp = None

        if verbose:
            self._print_status()

    # ------------------------------------------------------------------
    # Información del estado del backend
    # ------------------------------------------------------------------

    @property
    def opencv_cuda_available(self) -> bool:
        """True si OpenCV CUDA está activo."""
        return self._cv_cuda

    @property
    def cupy_available(self) -> bool:
        """True si CuPy está activo."""
        return self._cupy

    @property
    def any_gpu(self) -> bool:
        """True si al menos un backend GPU está activo."""
        return self._cv_cuda or self._cupy

    def summary(self) -> dict[str, str]:
        """
        Resumen de backends activos.

        Returns
        -------
        dict
            {'opencv_cuda': 'GPU ✓' | 'CPU', 'cupy': 'GPU ✓' | 'CPU'}
        """
        return {
            'opencv_cuda': 'GPU (cv2.cuda) ✓' if self._cv_cuda else 'CPU (cv2)',
            'cupy':        'GPU (CuPy) ✓'     if self._cupy     else 'CPU (NumPy)',
        }

    def _print_status(self) -> None:
        s = self.summary()
        print(f"[GPU] Decodificación de imagen : {s['opencv_cuda']}")
        print(f"[GPU] Operaciones numéricas    : {s['cupy']}")

    # ------------------------------------------------------------------
    # A. Operaciones de imagen — OpenCV CUDA con fallback a CPU
    # ------------------------------------------------------------------

    def imdecode(self, buf: bytes | np.ndarray, flags: int = cv2.IMREAD_COLOR) -> Optional[np.ndarray]:
        """
        Decodifica un buffer JPEG/PNG a np.ndarray BGR.

        Usa cv2.cuda.imdecode si OpenCV CUDA está disponible; si no,
        usa cv2.imdecode en CPU.

        Parameters
        ----------
        buf : bytes | np.ndarray
            Datos comprimidos del frame (JPEG, PNG, etc.).
        flags : int
            Flags de decodificación OpenCV (por defecto IMREAD_COLOR).

        Returns
        -------
        np.ndarray | None
            Imagen BGR (H x W x 3) uint8, o None si falla la decodificación.
        """
        if not isinstance(buf, np.ndarray):
            arr = np.frombuffer(buf, dtype=np.uint8)
        else:
            arr = buf

        if self._cv_cuda:
            try:
                gpu_mat = cv2.cuda_GpuMat()
                gpu_mat.upload(arr.reshape(1, -1))
                result_gpu = cv2.cuda.imdecode(gpu_mat, flags)
                return result_gpu.download()
            except Exception:
                pass  # Fallback silencioso a CPU

        return cv2.imdecode(arr, flags)

    def resize(
        self,
        img: np.ndarray,
        dsize: Tuple[int, int],
        interpolation: int = cv2.INTER_AREA,
    ) -> np.ndarray:
        """
        Redimensiona una imagen.

        Usa cv2.cuda.resize si OpenCV CUDA está disponible; si no, cv2.resize.

        Parameters
        ----------
        img : np.ndarray
            Imagen de entrada (H x W x C) uint8.
        dsize : (width, height)
            Tamaño destino en píxeles.
        interpolation : int
            Método de interpolación OpenCV.

        Returns
        -------
        np.ndarray
            Imagen redimensionada.
        """
        if self._cv_cuda:
            try:
                gpu_src = cv2.cuda_GpuMat()
                gpu_src.upload(img)
                gpu_dst = cv2.cuda.resize(gpu_src, dsize, interpolation=interpolation)
                return gpu_dst.download()
            except Exception:
                pass

        return cv2.resize(img, dsize, interpolation=interpolation)

    def apply_colormap(self, gray: np.ndarray, colormap: int = cv2.COLORMAP_JET) -> np.ndarray:
        """
        Aplica un mapa de color a una imagen de 8 bits.

        Usa cv2.cuda.applyColorMap si OpenCV CUDA está disponible; si no, cv2.applyColorMap.

        Parameters
        ----------
        gray : np.ndarray
            Imagen de 1 canal uint8 (H x W).
        colormap : int
            Código de mapa de color OpenCV (por defecto COLORMAP_JET).

        Returns
        -------
        np.ndarray
            Imagen BGR (H x W x 3) uint8 con el mapa de color aplicado.
        """
        if self._cv_cuda:
            try:
                gpu_src = cv2.cuda_GpuMat()
                gpu_src.upload(gray)
                gpu_dst = cv2.cuda_GpuMat()
                cv2.cuda.applyColorMap(gpu_src, colormap, gpu_dst)
                return gpu_dst.download()
            except Exception:
                pass

        return cv2.applyColorMap(gray, colormap)

    def cvt_color(self, img: np.ndarray, code: int) -> np.ndarray:
        """
        Convierte el espacio de color de una imagen.

        Usa cv2.cuda.cvtColor si OpenCV CUDA está disponible; si no, cv2.cvtColor.

        Parameters
        ----------
        img : np.ndarray
            Imagen de entrada.
        code : int
            Código de conversión OpenCV (p. ej. cv2.COLOR_GRAY2BGR).

        Returns
        -------
        np.ndarray
            Imagen convertida.
        """
        if self._cv_cuda:
            try:
                gpu_src = cv2.cuda_GpuMat()
                gpu_src.upload(img)
                gpu_dst = cv2.cuda.cvtColor(gpu_src, code)
                return gpu_dst.download()
            except Exception:
                pass

        return cv2.cvtColor(img, code)

    def convert_scale_abs(self, src: np.ndarray, alpha: float = 1.0, beta: float = 0.0) -> np.ndarray:
        """
        Escala y convierte a uint8 absoluto (equivale a cv2.convertScaleAbs).

        Usa CuPy en GPU si está disponible; si no, NumPy en CPU.

        Parameters
        ----------
        src : np.ndarray
            Array de entrada (cualquier tipo numérico).
        alpha : float
            Factor de escala.
        beta : float
            Offset opcional.

        Returns
        -------
        np.ndarray
            Array uint8 (H x W) con la conversión aplicada.
        """
        if self._cupy:
            try:
                cp = self._cp
                gpu = cp.asarray(src)
                scaled = cp.abs(gpu.astype(cp.float32) * alpha + beta)
                result = cp.clip(scaled, 0, 255).astype(cp.uint8)
                return cp.asnumpy(result)
            except Exception:
                pass

        return cv2.convertScaleAbs(src, alpha=alpha, beta=beta)

    # ------------------------------------------------------------------
    # B. Operaciones numéricas — CuPy con fallback a NumPy
    # ------------------------------------------------------------------

    def pack_z16_to_bgr(self, depth_z16: np.ndarray) -> np.ndarray:
        """
        Empaqueta una matriz uint16 de profundidad (Z16) en imagen BGR sin pérdidas.

        Canal B: Byte bajo (bits 0-7)
        Canal G: Byte alto (bits 8-15)
        Canal R: 0

        Usa CuPy (GPU) si está disponible; si no, NumPy (CPU).

        Parameters
        ----------
        depth_z16 : np.ndarray
            Matriz uint16 (H x W) de profundidad en milímetros.

        Returns
        -------
        np.ndarray
            Imagen BGR uint8 (H x W x 3) con profundidad empaquetada.
        """
        if self._cupy:
            try:
                cp = self._cp
                d = cp.asarray(depth_z16)
                low_byte  = (d & 0xFF).astype(cp.uint8)
                high_byte = ((d >> 8) & 0xFF).astype(cp.uint8)
                zero      = cp.zeros_like(low_byte)
                return cp.asnumpy(cp.dstack((low_byte, high_byte, zero)))
            except Exception:
                pass

        low_byte  = (depth_z16 & 0xFF).astype(np.uint8)
        high_byte = ((depth_z16 >> 8) & 0xFF).astype(np.uint8)
        zero      = np.zeros_like(low_byte)
        return np.dstack((low_byte, high_byte, zero))

    def unpack_bgr_to_z16(self, bgr_packed: np.ndarray) -> np.ndarray:
        """
        Desempaqueta una imagen BGR a la matriz original uint16 de profundidad (Z16 en mm).

        Usa CuPy (GPU) si está disponible; si no, NumPy (CPU).

        Parameters
        ----------
        bgr_packed : np.ndarray
            Imagen BGR uint8 (H x W x 3) con profundidad empaquetada.

        Returns
        -------
        np.ndarray
            Matriz uint16 (H x W) de profundidad en milímetros.
        """
        if self._cupy:
            try:
                cp = self._cp
                b = cp.asarray(bgr_packed)
                low_byte  = b[:, :, 0].astype(cp.uint16)
                high_byte = b[:, :, 1].astype(cp.uint16)
                return cp.asnumpy((high_byte << 8) | low_byte)
            except Exception:
                pass

        low_byte  = bgr_packed[:, :, 0].astype(np.uint16)
        high_byte = bgr_packed[:, :, 1].astype(np.uint16)
        return (high_byte << 8) | low_byte


# ---------------------------------------------------------------------------
# Instancia global compartida (singleton ligero)
# Importar con: from gpu_accel import GPU
# ---------------------------------------------------------------------------
GPU: GpuAccel = GpuAccel(verbose=False)
