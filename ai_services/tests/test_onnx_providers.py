from types import SimpleNamespace
from unittest.mock import patch

from ai_services.onnx_providers import runtime_providers


def _ort(tmp_path, providers):
    package = tmp_path / "onnxruntime"
    package.mkdir()
    init_file = package / "__init__.py"
    init_file.write_text("")
    return SimpleNamespace(
        __file__=str(init_file),
        get_available_providers=lambda: providers,
    )


def test_uses_cpu_when_cuda_is_not_advertised(tmp_path):
    ort = _ort(tmp_path, ["CPUExecutionProvider"])

    assert runtime_providers(ort) == ["CPUExecutionProvider"]


def test_uses_cpu_when_cuda_provider_library_cannot_load(tmp_path):
    ort = _ort(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    loader_name = "WinDLL" if __import__("os").name == "nt" else "CDLL"

    with patch(f"ai_services.onnx_providers.ctypes.{loader_name}", side_effect=OSError):
        assert runtime_providers(ort) == ["CPUExecutionProvider"]


def test_enables_cuda_when_provider_library_loads(tmp_path):
    ort = _ort(tmp_path, ["CUDAExecutionProvider", "CPUExecutionProvider"])
    loader_name = "WinDLL" if __import__("os").name == "nt" else "CDLL"

    with patch(f"ai_services.onnx_providers.ctypes.{loader_name}", return_value=object()):
        assert runtime_providers(ort) == [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
