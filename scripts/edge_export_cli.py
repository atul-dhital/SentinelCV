#!/usr/bin/env python3
"""CLI for edge model export and optimization workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_services.edge_export import (
    edge_export_service,
    HAS_ONNX,
    HAS_ORT,
    HAS_TORCH,
)


def _parse_shape(value: str) -> Tuple[int, ...]:
    parts = [int(piece.strip()) for piece in value.split(",") if piece.strip()]
    if not parts:
        raise ValueError("input_shape must be a comma-separated list of integers")
    return tuple(parts)


def _load_torch_model(model_path: str):
    if not HAS_TORCH:
        raise RuntimeError("PyTorch not installed; cannot load model")
    import torch

    model = torch.load(model_path, map_location="cpu", weights_only=True)
    if hasattr(model, "eval"):
        model.eval()
    return model


def _write_output(result: dict, output_json: str | None) -> None:
    output = json.dumps(result, indent=2, default=str)
    if output_json:
        output_path = Path(output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output)


def _export_onnx(args: argparse.Namespace) -> dict:
    model_path = Path(args.model_path)
    if not model_path.exists():
        return {"success": False, "error": f"Model not found: {model_path}"}
    model = _load_torch_model(str(model_path))
    input_shape = _parse_shape(args.input_shape)
    return edge_export_service.export_to_onnx(
        model,
        input_shape=input_shape,
        output_path=args.output,
        model_name=args.model_name or model_path.stem,
        opset_version=args.opset,
    )


def _optimize_onnx(args: argparse.Namespace) -> dict:
    if not HAS_ONNX:
        return {"success": False, "error": "onnx not installed"}
    return edge_export_service.optimize_onnx(args.model_path, args.output)


def _quantize_onnx(args: argparse.Namespace) -> dict:
    if not HAS_ORT:
        return {"success": False, "error": "onnxruntime not installed"}
    return edge_export_service.quantize_model(
        args.model_path,
        quantization_type=args.quantization_type,
        output_path=args.output,
    )


def _benchmark(args: argparse.Namespace) -> dict:
    input_shape = _parse_shape(args.input_shape)
    return edge_export_service.benchmark_edge_model(
        args.model_path,
        num_iterations=args.iterations,
        input_shape=input_shape,
    )


def _info(args: argparse.Namespace) -> dict:
    return edge_export_service.get_model_info(args.model_path)


def _list_exports(_args: argparse.Namespace) -> dict:
    return {"exports": edge_export_service.list_exported_models()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Edge model export CLI")
    parser.add_argument("--output-json", default="", help="Write JSON output to a file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("onnx", help="Export a torch model to ONNX")
    export_parser.add_argument("--model-path", required=True, help="Path to a torch model")
    export_parser.add_argument("--input-shape", default="1,3,224,224", help="Comma-separated input shape")
    export_parser.add_argument("--output", default="edge_model.onnx", help="Output ONNX filename")
    export_parser.add_argument("--model-name", default="", help="Optional model name override")
    export_parser.add_argument("--opset", type=int, default=13, help="ONNX opset version")
    export_parser.set_defaults(func=_export_onnx)

    optimize_parser = subparsers.add_parser("optimize", help="Optimize an ONNX model")
    optimize_parser.add_argument("--model-path", required=True, help="Path to ONNX model")
    optimize_parser.add_argument("--output", default="edge_model_optimized.onnx", help="Output ONNX filename")
    optimize_parser.set_defaults(func=_optimize_onnx)

    quantize_parser = subparsers.add_parser("quantize", help="Quantize an ONNX model")
    quantize_parser.add_argument("--model-path", required=True, help="Path to ONNX model")
    quantize_parser.add_argument("--output", default="edge_model_quantized.onnx", help="Output ONNX filename")
    quantize_parser.add_argument("--quantization-type", default="dynamic", help="dynamic or float16")
    quantize_parser.set_defaults(func=_quantize_onnx)

    bench_parser = subparsers.add_parser("benchmark", help="Benchmark an ONNX model")
    bench_parser.add_argument("--model-path", required=True, help="Path to ONNX model")
    bench_parser.add_argument("--iterations", type=int, default=100, help="Iterations for benchmarking")
    bench_parser.add_argument("--input-shape", default="1,3,224,224", help="Comma-separated input shape")
    bench_parser.set_defaults(func=_benchmark)

    info_parser = subparsers.add_parser("info", help="Show model metadata")
    info_parser.add_argument("--model-path", required=True, help="Path to ONNX model")
    info_parser.set_defaults(func=_info)

    list_parser = subparsers.add_parser("list", help="List exported models")
    list_parser.set_defaults(func=_list_exports)

    args = parser.parse_args()
    result = args.func(args)
    output_json = args.output_json or None
    _write_output(result, output_json)
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
