"""Safe ONNX Runtime execution-provider selection."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


def runtime_providers(ort_module, logger=None) -> list[str]:
    """Return CUDA+CPU only when the CUDA provider DLL can actually load."""
    cpu = ["CPUExecutionProvider"]
    if "CUDAExecutionProvider" not in ort_module.get_available_providers():
        return cpu

    if os.name == "nt":
        library_name = "onnxruntime_providers_cuda.dll"
        loader = ctypes.WinDLL
    elif os.name == "posix":
        library_name = "libonnxruntime_providers_cuda.so"
        loader = ctypes.CDLL
    else:
        return cpu

    provider_library = Path(ort_module.__file__).resolve().parent / "capi" / library_name
    try:
        loader(str(provider_library))
    except (OSError, FileNotFoundError) as exc:
        if logger:
            logger.info("ONNX CUDA provider unavailable; using CPU: %s", exc)
        return cpu

    return ["CUDAExecutionProvider", "CPUExecutionProvider"]
