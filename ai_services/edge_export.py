"""
Edge AI Model Export Service (ENH-010)

Export models for edge deployment (ONNX, TFLite, TensorRT).
Supports quantization (INT8, FP16) and optimization.
"""

import os
import time
import logging
import json
from typing import Dict, List, Optional, Any
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

EXPORT_DIR = os.getenv("EDGE_EXPORT_DIR", "data/edge_models")
os.makedirs(EXPORT_DIR, exist_ok=True)

# Check available export backends
try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

try:
    import onnx
    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

try:
    import onnxruntime as ort
    HAS_ORT = True
except ImportError:
    HAS_ORT = False

try:
    import tensorflow as tf
    HAS_TF = True
except ImportError:
    HAS_TF = False

try:
    import tensorrt as trt
    HAS_TRT = True
except ImportError:
    HAS_TRT = False


class EdgeExportService:
    """Export and optimize models for edge device deployment."""

    def __init__(self):
        self._export_history: List[Dict] = []

    def export_to_onnx(
        self,
        model: Any,
        input_shape: tuple,
        output_path: str,
        model_name: str = "model",
        opset_version: int = 13,
    ) -> Dict:
        """Export a PyTorch model to ONNX format."""
        if not HAS_TORCH:
            return {"success": False, "error": "PyTorch not installed"}

        try:
            output_path = os.path.join(EXPORT_DIR, output_path)
            os.makedirs(os.path.dirname(output_path) or EXPORT_DIR, exist_ok=True)

            model.eval()
            dummy_input = torch.randn(*input_shape)

            start = time.perf_counter()
            torch.onnx.export(
                model,
                dummy_input,
                output_path,
                export_params=True,
                opset_version=opset_version,
                input_names=["input"],
                output_names=["output"],
                dynamic_axes={"input": {0: "batch_size"}, "output": {0: "batch_size"}},
            )
            elapsed = time.perf_counter() - start

            file_size = os.path.getsize(output_path)
            result = {
                "success": True,
                "format": "onnx",
                "output_path": output_path,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "export_time_ms": round(elapsed * 1000, 1),
                "opset_version": opset_version,
                "input_shape": list(input_shape),
            }
            self._export_history.append({**result, "model_name": model_name, "timestamp": time.time()})
            return result

        except Exception as e:
            logger.error(f"ONNX export failed: {e}")
            return {"success": False, "error": str(e)}

    def optimize_onnx(self, onnx_path: str, output_path: str) -> Dict:
        """Optimize an ONNX model (graph optimization, constant folding)."""
        if not HAS_ONNX:
            return {"success": False, "error": "onnx package not installed"}

        try:
            from onnx import optimizer

            model = onnx.load(onnx_path)
            original_size = os.path.getsize(onnx_path)

            passes = [
                "eliminate_identity",
                "eliminate_nop_pad",
                "fuse_consecutive_transposes",
                "fuse_bn_into_conv",
            ]
            optimized = optimizer.optimize(model, passes)

            output_path = os.path.join(EXPORT_DIR, output_path)
            onnx.save(optimized, output_path)
            optimized_size = os.path.getsize(output_path)

            return {
                "success": True,
                "original_size_mb": round(original_size / (1024 * 1024), 2),
                "optimized_size_mb": round(optimized_size / (1024 * 1024), 2),
                "size_reduction_pct": round((1 - optimized_size / original_size) * 100, 1),
                "output_path": output_path,
            }
        except Exception as e:
            logger.warning(f"ONNX optimization failed: {e}")
            return {"success": False, "error": str(e), "note": "ONNX optimizer may not be available"}

    def quantize_model(
        self,
        model_path: str,
        quantization_type: str = "dynamic",
        output_path: Optional[str] = None,
    ) -> Dict:
        """
        Quantize an ONNX model for reduced size and faster inference.

        quantization_type: 'dynamic' (INT8), 'static', or 'float16'
        """
        if not HAS_ORT:
            return {"success": False, "error": "onnxruntime not installed"}

        try:
            from onnxruntime.quantization import quantize_dynamic, QuantType

            if output_path is None:
                base, ext = os.path.splitext(model_path)
                output_path = f"{base}_quantized{ext}"

            original_size = os.path.getsize(model_path) if os.path.exists(model_path) else 0

            if quantization_type == "dynamic":
                quantize_dynamic(
                    model_path,
                    output_path,
                    weight_type=QuantType.QUInt8,
                )
            elif quantization_type == "float16":
                if not HAS_ONNX:
                    return {"success": False, "error": "float16 quantization requires onnx: pip install onnx"}
                import onnx
                from onnx import TensorProto
                from onnx.numpy_helper import to_array, from_array as _from_array
                model_fp32 = onnx.load(model_path)
                for init in model_fp32.graph.initializer:
                    if init.data_type == TensorProto.FLOAT:
                        arr_fp16 = to_array(init).astype(np.float16)
                        new_init = _from_array(arr_fp16, name=init.name)
                        init.CopyFrom(new_init)
                for vi in list(model_fp32.graph.input) + list(model_fp32.graph.output) + list(model_fp32.graph.value_info):
                    if vi.type.tensor_type.elem_type == TensorProto.FLOAT:
                        vi.type.tensor_type.elem_type = TensorProto.FLOAT16
                onnx.save(model_fp32, output_path)
            else:
                return {"success": False, "error": f"Unknown quantization_type '{quantization_type}'. Use 'dynamic' or 'float16'."}

            quantized_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0

            return {
                "success": True,
                "quantization_type": quantization_type,
                "original_size_mb": round(original_size / (1024 * 1024), 2),
                "quantized_size_mb": round(quantized_size / (1024 * 1024), 2),
                "compression_ratio": round(original_size / max(1, quantized_size), 2),
                "output_path": output_path,
            }
        except Exception as e:
            logger.error(f"Quantization failed: {e}")
            return {"success": False, "error": str(e)}

    def benchmark_edge_model(
        self,
        model_path: str,
        num_iterations: int = 100,
        input_shape: tuple = (1, 3, 224, 224),
    ) -> Dict:
        """Benchmark an ONNX model's inference performance."""
        if not HAS_ORT:
            # Simulate benchmark
            return self._simulated_benchmark(model_path, num_iterations, input_shape)

        try:
            session = ort.InferenceSession(model_path)
            input_name = session.get_inputs()[0].name
            dummy = np.random.randn(*input_shape).astype(np.float32)

            # Warmup
            for _ in range(5):
                session.run(None, {input_name: dummy})

            # Benchmark
            latencies = []
            for _ in range(num_iterations):
                start = time.perf_counter()
                session.run(None, {input_name: dummy})
                latencies.append((time.perf_counter() - start) * 1000)

            return {
                "model_path": model_path,
                "num_iterations": num_iterations,
                "latency_mean_ms": round(np.mean(latencies), 2),
                "latency_p50_ms": round(np.percentile(latencies, 50), 2),
                "latency_p95_ms": round(np.percentile(latencies, 95), 2),
                "latency_p99_ms": round(np.percentile(latencies, 99), 2),
                "throughput_fps": round(1000 / np.mean(latencies), 1),
                "input_shape": list(input_shape),
            }
        except Exception as e:
            logger.error(f"Benchmark failed: {e}")
            return {"error": str(e)}

    def _simulated_benchmark(
        self, model_path: str, num_iterations: int, input_shape: tuple
    ) -> Dict:
        """Simulate benchmark when ONNX Runtime is not available."""
        np.random.seed(42)
        base_latency = 15.0  # ms
        latencies = np.random.normal(base_latency, 3.0, num_iterations)
        latencies = np.maximum(latencies, 1.0)

        return {
            "model_path": model_path,
            "num_iterations": num_iterations,
            "latency_mean_ms": round(np.mean(latencies), 2),
            "latency_p50_ms": round(np.percentile(latencies, 50), 2),
            "latency_p95_ms": round(np.percentile(latencies, 95), 2),
            "latency_p99_ms": round(np.percentile(latencies, 99), 2),
            "throughput_fps": round(1000 / np.mean(latencies), 1),
            "input_shape": list(input_shape),
            "simulated": True,
            "note": "ONNX Runtime not available; results are simulated estimates",
        }

    def export_to_tflite(
        self,
        onnx_path: str,
        output_path: str,
        quantize: bool = False,
    ) -> Dict:
        """Convert an ONNX model to TensorFlow Lite format.

        Requires tensorflow and onnx-tf (or tf2onnx) installed.
        Falls back to simulation if dependencies are missing.
        """
        output_path = os.path.join(EXPORT_DIR, output_path)
        os.makedirs(os.path.dirname(output_path) or EXPORT_DIR, exist_ok=True)

        if not HAS_TF:
            return self._simulated_tflite_export(onnx_path, output_path, quantize)

        try:
            import onnx as _onnx
            from onnx_tf.backend import prepare  # type: ignore[import-untyped]

            start = time.perf_counter()
            onnx_model = _onnx.load(onnx_path)
            tf_rep = prepare(onnx_model)

            # Save as SavedModel then convert
            saved_model_dir = output_path + "_savedmodel"
            tf_rep.export_graph(saved_model_dir)

            converter = tf.lite.TFLiteConverter.from_saved_model(saved_model_dir)
            if quantize:
                converter.optimizations = [tf.lite.Optimize.DEFAULT]
                converter.target_spec.supported_types = [tf.float16]

            tflite_model = converter.convert()
            with open(output_path, "wb") as f:
                f.write(tflite_model)

            elapsed = time.perf_counter() - start
            file_size = os.path.getsize(output_path)

            result = {
                "success": True,
                "format": "tflite",
                "output_path": output_path,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "export_time_ms": round(elapsed * 1000, 1),
                "quantized": quantize,
            }
            self._export_history.append({**result, "timestamp": time.time()})
            return result

        except ImportError:
            logger.warning("onnx-tf not installed; using simulated TFLite export")
            return self._simulated_tflite_export(onnx_path, output_path, quantize)
        except Exception as e:
            logger.error(f"TFLite export failed: {e}")
            return {"success": False, "error": str(e)}

    def _simulated_tflite_export(
        self, onnx_path: str, output_path: str, quantize: bool
    ) -> Dict:
        """Simulate TFLite export when TensorFlow is not available."""
        source_size = os.path.getsize(onnx_path) if os.path.exists(onnx_path) else 50_000_000
        estimated_size = int(source_size * (0.4 if quantize else 0.85))

        result = {
            "success": True,
            "format": "tflite",
            "output_path": output_path,
            "file_size_mb": round(estimated_size / (1024 * 1024), 2),
            "quantized": quantize,
            "simulated": True,
            "note": "TensorFlow not available; export is simulated",
        }
        self._export_history.append({**result, "timestamp": time.time()})
        return result

    def export_to_tensorrt(
        self,
        onnx_path: str,
        output_path: str,
        precision: str = "fp16",
        max_batch_size: int = 1,
        workspace_mb: int = 1024,
    ) -> Dict:
        """Convert an ONNX model to TensorRT engine.

        Requires tensorrt and pycuda installed (NVIDIA GPU required).
        Falls back to simulation if dependencies are missing.
        """
        output_path = os.path.join(EXPORT_DIR, output_path)
        os.makedirs(os.path.dirname(output_path) or EXPORT_DIR, exist_ok=True)

        if not HAS_TRT:
            return self._simulated_tensorrt_export(
                onnx_path, output_path, precision, max_batch_size
            )

        try:
            TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
            start = time.perf_counter()

            builder = trt.Builder(TRT_LOGGER)
            network = builder.create_network(
                1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
            )
            parser = trt.OnnxParser(network, TRT_LOGGER)

            with open(onnx_path, "rb") as f:
                if not parser.parse(f.read()):
                    errors = [parser.get_error(i) for i in range(parser.num_errors)]
                    return {"success": False, "error": f"ONNX parse errors: {errors}"}

            config = builder.create_builder_config()
            config.set_memory_pool_limit(
                trt.MemoryPoolType.WORKSPACE, workspace_mb * (1 << 20)
            )

            if precision == "fp16" and builder.platform_has_fast_fp16:
                config.set_flag(trt.BuilderFlag.FP16)
            elif precision == "int8" and builder.platform_has_fast_int8:
                config.set_flag(trt.BuilderFlag.INT8)

            engine_bytes = builder.build_serialized_network(network, config)
            if engine_bytes is None:
                return {"success": False, "error": "TensorRT engine build failed"}

            with open(output_path, "wb") as f:
                f.write(engine_bytes)

            elapsed = time.perf_counter() - start
            file_size = os.path.getsize(output_path)

            result = {
                "success": True,
                "format": "tensorrt",
                "output_path": output_path,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "export_time_ms": round(elapsed * 1000, 1),
                "precision": precision,
                "max_batch_size": max_batch_size,
            }
            self._export_history.append({**result, "timestamp": time.time()})
            return result

        except Exception as e:
            logger.error(f"TensorRT export failed: {e}")
            return {"success": False, "error": str(e)}

    def _simulated_tensorrt_export(
        self,
        onnx_path: str,
        output_path: str,
        precision: str,
        max_batch_size: int,
    ) -> Dict:
        """Simulate TensorRT export when TensorRT is not available."""
        source_size = os.path.getsize(onnx_path) if os.path.exists(onnx_path) else 50_000_000
        ratio = {"fp32": 1.0, "fp16": 0.55, "int8": 0.3}.get(precision, 0.55)
        estimated_size = int(source_size * ratio)

        result = {
            "success": True,
            "format": "tensorrt",
            "output_path": output_path,
            "file_size_mb": round(estimated_size / (1024 * 1024), 2),
            "precision": precision,
            "max_batch_size": max_batch_size,
            "simulated": True,
            "note": "TensorRT not available; export is simulated",
        }
        self._export_history.append({**result, "timestamp": time.time()})
        return result

    def get_model_info(self, model_path: str) -> Dict:
        """Get model metadata (size, format, architecture info)."""
        if not os.path.exists(model_path):
            return {"error": "Model file not found"}

        file_size = os.path.getsize(model_path)
        ext = os.path.splitext(model_path)[1].lower()

        info = {
            "path": model_path,
            "format": ext.replace(".", ""),
            "file_size_mb": round(file_size / (1024 * 1024), 2),
            "file_size_bytes": file_size,
        }

        if ext == ".onnx" and HAS_ONNX:
            try:
                model = onnx.load(model_path)
                info["opset_version"] = model.opset_import[0].version if model.opset_import else None
                info["ir_version"] = model.ir_version
                info["graph_name"] = model.graph.name
                info["num_nodes"] = len(model.graph.node)
                info["inputs"] = [
                    {"name": inp.name, "shape": [d.dim_value for d in inp.type.tensor_type.shape.dim]}
                    for inp in model.graph.input
                ]
                info["outputs"] = [
                    {"name": out.name, "shape": [d.dim_value for d in out.type.tensor_type.shape.dim]}
                    for out in model.graph.output
                ]
            except Exception as e:
                info["onnx_parse_error"] = str(e)

        return info

    def list_exported_models(self) -> List[Dict]:
        """List all exported edge models."""
        models = []
        if os.path.exists(EXPORT_DIR):
            for f in os.listdir(EXPORT_DIR):
                path = os.path.join(EXPORT_DIR, f)
                if os.path.isfile(path):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in (".onnx", ".tflite", ".pt", ".pth"):
                        models.append({
                            "name": f,
                            "path": path,
                            "format": ext.replace(".", ""),
                            "size_mb": round(os.path.getsize(path) / (1024 * 1024), 2),
                        })
        models.extend(self._export_history)
        return models

    def get_export_history(self) -> List[Dict]:
        return self._export_history


edge_export_service = EdgeExportService()
