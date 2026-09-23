import cv2
import numpy as np
import os
from typing import Dict, Any, List, Optional
from runtime_registry import get_runtime_component

try:
    import torch
    import torch.nn.functional as torch_fn
    from torchvision import models as tv_models
    from torchvision.models import ResNet18_Weights
    _TORCH_AVAILABLE = True
except Exception:
    torch = None
    torch_fn = None
    tv_models = None
    ResNet18_Weights = None
    _TORCH_AVAILABLE = False

try:
    import tensorflow as tf
    from deepface import DeepFace
    _TF_DEEPFACE_AVAILABLE = True
except Exception:
    tf = None
    DeepFace = None
    _TF_DEEPFACE_AVAILABLE = False

class ExplainabilityManager:
    """US-FUT-015: Explainable AI manager.

    Priority order:
    1) TensorFlow/DeepFace gradient CAM on active recognition model
    2) PyTorch Grad-CAM surrogate model
    3) Region-attention fallback map (deterministic)
    """

    def __init__(self):
        self.output_dir = "data/xai_outputs"
        os.makedirs(self.output_dir, exist_ok=True)

        recognition_component = get_runtime_component("face_recognition")
        self.active_model_name = str(recognition_component.get("current_model", "ArcFace") or "ArcFace")

        self.last_method = "region_attention_fallback"
        self.last_feature_importance = self._default_feature_importance()

        self._tf_model = None
        self._tf_grad_model = None

        self._torch_model = None
        self._torch_activations = None
        self._torch_gradients = None
        self._torch_hooks = []

        self._init_tf_gradcam_backend()
        if self._tf_grad_model is None:
            self._init_torch_gradcam_backend()

    def _default_feature_importance(self) -> Dict[str, float]:
        return {
            "eye_region": 0.35,
            "nose_bridge": 0.22,
            "jawline": 0.15,
            "mouth_region": 0.12,
            "forehead": 0.08,
            "cheekbones": 0.08,
        }

    def _init_tf_gradcam_backend(self) -> None:
        if not _TF_DEEPFACE_AVAILABLE:
            return

        model_candidates = [self.active_model_name, "ArcFace"]
        model = None
        selected_name = None

        for candidate in model_candidates:
            try:
                model = DeepFace.build_model(candidate)
                selected_name = candidate
                break
            except Exception:
                continue

        if model is None:
            return

        last_conv_layer = self._find_last_conv_layer_name(model)
        if not last_conv_layer:
            return

        try:
            conv_output = model.get_layer(last_conv_layer).output
            self._tf_model = model
            self._tf_grad_model = tf.keras.models.Model(
                [model.inputs],
                [conv_output, model.output],
            )
            self.active_model_name = selected_name or self.active_model_name
        except Exception:
            self._tf_model = None
            self._tf_grad_model = None

    def _init_torch_gradcam_backend(self) -> None:
        if not _TORCH_AVAILABLE:
            return

        try:
            model = tv_models.resnet18(weights=ResNet18_Weights.DEFAULT)
            model.eval()
            target_layer = model.layer4[-1].conv2

            def _forward_hook(_module, _inputs, output):
                self._torch_activations = output

            def _backward_hook(_module, _grad_input, grad_output):
                if grad_output:
                    self._torch_gradients = grad_output[0]

            self._torch_hooks = [
                target_layer.register_forward_hook(_forward_hook),
                target_layer.register_full_backward_hook(_backward_hook),
            ]
            self._torch_model = model
        except Exception:
            self._torch_model = None
            self._torch_hooks = []

    @staticmethod
    def _find_last_conv_layer_name(model) -> Optional[str]:
        for layer in reversed(getattr(model, "layers", [])):
            output_shape = getattr(layer, "output_shape", None)
            if output_shape is None:
                continue
            if isinstance(output_shape, list):
                output_shape = output_shape[0] if output_shape else None
            if isinstance(output_shape, tuple) and len(output_shape) >= 4:
                return getattr(layer, "name", None)
        return None

    @staticmethod
    def _normalize_heatmap(heatmap: np.ndarray) -> np.ndarray:
        safe = np.nan_to_num(heatmap.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        safe = np.maximum(safe, 0.0)
        max_value = float(np.max(safe)) if safe.size else 0.0
        if max_value > 0:
            safe = safe / max_value
        return np.clip(safe, 0.0, 1.0)

    @staticmethod
    def _overlay_heatmap(face_img: np.ndarray, normalized_heatmap: np.ndarray) -> np.ndarray:
        h, w = face_img.shape[:2]
        heatmap_resized = cv2.resize(normalized_heatmap, (w, h))
        heatmap_uint8 = (heatmap_resized * 255).astype(np.uint8)
        color_heatmap = cv2.applyColorMap(heatmap_uint8, cv2.COLORMAP_JET)
        return cv2.addWeighted(face_img, 0.6, color_heatmap, 0.4, 0)

    def _feature_importance_from_heatmap(self, normalized_heatmap: np.ndarray) -> Dict[str, float]:
        if normalized_heatmap is None or normalized_heatmap.size == 0:
            return self._default_feature_importance()

        h, w = normalized_heatmap.shape[:2]
        regions = {
            "eye_region": (int(h * 0.24), int(h * 0.48), int(w * 0.20), int(w * 0.80)),
            "nose_bridge": (int(h * 0.40), int(h * 0.66), int(w * 0.38), int(w * 0.62)),
            "jawline": (int(h * 0.70), int(h * 0.96), int(w * 0.12), int(w * 0.88)),
            "mouth_region": (int(h * 0.62), int(h * 0.84), int(w * 0.30), int(w * 0.70)),
            "forehead": (int(h * 0.04), int(h * 0.24), int(w * 0.22), int(w * 0.78)),
            "cheekbones": (int(h * 0.45), int(h * 0.75), int(w * 0.08), int(w * 0.92)),
        }

        raw_scores: Dict[str, float] = {}
        for name, (y0, y1, x0, x1) in regions.items():
            block = normalized_heatmap[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
            raw_scores[name] = float(np.mean(block)) if block.size else 0.0

        total = sum(raw_scores.values())
        if total <= 0:
            return self._default_feature_importance()

        return {key: float(value / total) for key, value in raw_scores.items()}

    def _generate_tf_gradcam_map(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        if self._tf_grad_model is None or tf is None or self._tf_model is None:
            return None

        try:
            rgb_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)

            input_shape = getattr(self._tf_model, "input_shape", None)
            if isinstance(input_shape, list):
                input_shape = input_shape[0] if input_shape else None
            target_h = int(input_shape[1]) if isinstance(input_shape, tuple) and len(input_shape) > 2 and input_shape[1] else 160
            target_w = int(input_shape[2]) if isinstance(input_shape, tuple) and len(input_shape) > 2 and input_shape[2] else 160

            resized = cv2.resize(rgb_img, (target_w, target_h)).astype(np.float32) / 255.0
            input_tensor = np.expand_dims(resized, axis=0)

            with tf.GradientTape() as tape:
                conv_outputs, predictions = self._tf_grad_model(input_tensor, training=False)
                if isinstance(predictions, (list, tuple)):
                    predictions = predictions[0]
                embedding_energy = tf.reduce_sum(tf.square(predictions), axis=1)

            gradients = tape.gradient(embedding_energy, conv_outputs)
            if gradients is None:
                return None

            pooled_gradients = tf.reduce_mean(gradients, axis=(0, 1, 2))
            conv_outputs = conv_outputs[0]
            weighted = conv_outputs * pooled_gradients
            heatmap = tf.reduce_sum(weighted, axis=-1)
            heatmap = tf.nn.relu(heatmap).numpy()
            heatmap = self._normalize_heatmap(heatmap)
            return cv2.resize(heatmap, (face_img.shape[1], face_img.shape[0]))
        except Exception:
            return None

    def _generate_torch_gradcam_map(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        if self._torch_model is None or torch is None or torch_fn is None:
            return None

        try:
            rgb_img = cv2.cvtColor(face_img, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb_img, (224, 224)).astype(np.float32) / 255.0
            tensor = torch.from_numpy(resized).permute(2, 0, 1).unsqueeze(0)

            mean = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)
            tensor = (tensor - mean) / std
            tensor.requires_grad_(True)

            self._torch_activations = None
            self._torch_gradients = None
            self._torch_model.zero_grad(set_to_none=True)

            outputs = self._torch_model(tensor)
            score = outputs.max(dim=1).values
            score.backward(torch.ones_like(score))

            if self._torch_activations is None or self._torch_gradients is None:
                return None

            gradients = self._torch_gradients.detach()
            activations = self._torch_activations.detach()
            weights = gradients.mean(dim=(2, 3), keepdim=True)
            cam = (weights * activations).sum(dim=1, keepdim=True)
            cam = torch.relu(cam)
            cam = torch_fn.interpolate(
                cam,
                size=(face_img.shape[0], face_img.shape[1]),
                mode="bilinear",
                align_corners=False,
            )
            heatmap = cam.squeeze().cpu().numpy()
            return self._normalize_heatmap(heatmap)
        except Exception:
            return None

    def _generate_region_attention_map(self, face_img: np.ndarray) -> np.ndarray:
        if face_img is None:
            return None

        h, w = face_img.shape[:2]
        heatmap = np.zeros((h, w), dtype=np.float32)

        cv2.circle(heatmap, (int(w*0.35), int(h*0.4)), int(w*0.15), 0.8, -1)
        cv2.circle(heatmap, (int(w*0.65), int(h*0.4)), int(w*0.15), 0.8, -1)
        cv2.ellipse(heatmap, (int(w*0.5), int(h*0.55)), (int(w*0.1), int(h*0.15)), 0, 0, 360, 0.9, -1)
        cv2.ellipse(heatmap, (int(w*0.5), int(h*0.75)), (int(w*0.2), int(h*0.08)), 0, 0, 360, 0.6, -1)

        # Deterministic smoothing fallback map
        heatmap = cv2.GaussianBlur(heatmap, (int(w*0.25)|1, int(w*0.25)|1), 0)
        return self._normalize_heatmap(heatmap)

    def generate_heatmap(self, face_img: np.ndarray) -> np.ndarray:
        if face_img is None or face_img.size == 0:
            return None

        normalized_heatmap = self._generate_tf_gradcam_map(face_img)
        method = "tensorflow_deepface_gradcam"

        if normalized_heatmap is None:
            normalized_heatmap = self._generate_torch_gradcam_map(face_img)
            method = "pytorch_gradcam_surrogate"

        if normalized_heatmap is None:
            normalized_heatmap = self._generate_region_attention_map(face_img)
            method = "region_attention_fallback"

        self.last_method = method
        self.last_feature_importance = self._feature_importance_from_heatmap(normalized_heatmap)
        return self._overlay_heatmap(face_img, normalized_heatmap)

    def get_feature_importance(self) -> Dict[str, float]:
        return self.last_feature_importance or self._default_feature_importance()

    def explain_decision(self, confidence: float, threshold: float) -> List[Dict[str, Any]]:
        margin = float(confidence - threshold)
        top_regions = sorted(
            self.get_feature_importance().items(),
            key=lambda item: item[1],
            reverse=True,
        )[:2]
        region_text = ", ".join([f"{name} ({weight:.2f})" for name, weight in top_regions])

        factors = [
            {
                "factor": "Similarity Margin",
                "contribution": 0.70,
                "description": f"Recognition confidence {confidence:.3f} with threshold {threshold:.3f} (margin {margin:.3f}).",
            },
            {
                "factor": "Attribution Pipeline",
                "contribution": 0.15,
                "description": f"Heatmap generated via {self.last_method.replace('_', ' ')}.",
            },
            {
                "factor": "Most Influential Regions",
                "contribution": 0.15,
                "description": f"Top activated facial zones: {region_text}.",
            },
        ]
        return factors

if __name__ == "__main__":
    xai = ExplainabilityManager()
    print("XAI Manager initialized.")
