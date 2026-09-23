import hashlib
import logging
from typing import Any, List, Optional

import numpy as np

try:
    import torch
    import timm
    _TIMM_AVAILABLE = True
except Exception:
    torch = None
    timm = None
    _TIMM_AVAILABLE = False

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "vit_base_patch16_384"
_DEFAULT_INPUT = 384
_DEFAULT_EMBEDDING = 768


class ViTEmbeddingService:
    """Lightweight Vision Transformer embedding service.

    Uses timm if available; otherwise provides deterministic fallback embeddings.
    """

    def __init__(
        self,
        model_type: str = _DEFAULT_MODEL,
        input_size: int = _DEFAULT_INPUT,
        embedding_dim: int = _DEFAULT_EMBEDDING,
    ):
        self.model_type = model_type
        self.input_size = input_size
        self.embedding_dim = embedding_dim
        self.device = "cuda" if torch and torch.cuda.is_available() else "cpu"
        self.model = None

    def load_model(self) -> bool:
        """Load timm model if available."""
        if not _TIMM_AVAILABLE:
            logger.warning("timm not available; ViT embeddings will use fallback")
            return False

        try:
            self.model = timm.create_model(
                self.model_type,
                pretrained=True,
                num_classes=self.embedding_dim,
            )
            self.model.to(self.device)
            self.model.eval()
            return True
        except Exception as exc:
            logger.error("ViT model load failed: %s", exc)
            self.model = None
            return False

    def extract_embedding(
        self,
        image_input: Any,
        normalize: bool = True,
        output_dim: Optional[int] = None,
    ) -> Optional[List[float]]:
        """Extract a ViT embedding from a face image."""
        if self.model is None:
            if not self.load_model():
                return self._fallback_embedding(image_input, output_dim, normalize)

        try:
            image_tensor = self._prepare_image(image_input)
            if image_tensor is None:
                return None

            with torch.no_grad():
                embedding = self.model(image_tensor)

            emb_np = embedding.detach().cpu().numpy().flatten()
            emb_np = self._resize_embedding(emb_np, output_dim)
            if normalize:
                emb_np = self._l2_normalize(emb_np)
            return emb_np.tolist()
        except Exception as exc:
            logger.error("ViT embedding extraction failed: %s", exc)
            return self._fallback_embedding(image_input, output_dim, normalize)

    def _prepare_image(self, image_input: Any) -> Optional["torch.Tensor"]:
        """Convert image input to a tensor ready for ViT."""
        if not torch:
            return None

        try:
            from PIL import Image
            import cv2

            if isinstance(image_input, str):
                image = Image.open(image_input).convert("RGB")
            elif isinstance(image_input, Image.Image):
                image = image_input.convert("RGB")
            elif isinstance(image_input, np.ndarray):
                if image_input.dtype == np.uint8:
                    image = Image.fromarray(cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB))
                else:
                    image = Image.fromarray((image_input * 255).astype(np.uint8))
            else:
                logger.warning("Unsupported image input type: %s", type(image_input))
                return None

            image = image.resize((self.input_size, self.input_size), Image.Resampling.LANCZOS)
            image_tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float()

            mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
            image_tensor = (image_tensor / 255.0 - mean) / std
            return image_tensor.unsqueeze(0).to(self.device)
        except Exception as exc:
            logger.error("ViT image preparation failed: %s", exc)
            return None

    def _fallback_embedding(
        self,
        image_input: Any,
        output_dim: Optional[int],
        normalize: bool,
    ) -> Optional[List[float]]:
        """DCT-based image feature fallback when timm/torch unavailable.

        Extracts real image signal via multi-scale DCT coefficients across Y, Cb, Cr
        channels, then tiles them to the target embedding dimension. Two identical
        images always produce the same embedding; different images produce distinct
        embeddings because the signal derives from actual pixel content.
        """
        arr = self._load_image_array(image_input)
        if arr is not None:
            emb = self._dct_embedding(arr, output_dim or self.embedding_dim)
        else:
            # Ultimate fallback: hash-seeded when image unreadable
            seed = self._seed_from_input(image_input)
            rng = np.random.default_rng(seed)
            emb = rng.normal(0.0, 1.0, output_dim or self.embedding_dim).astype(np.float32)

        emb = self._resize_embedding(emb, output_dim)
        if normalize:
            emb = self._l2_normalize(emb)
        return emb.tolist()

    def _load_image_array(self, image_input: Any) -> Optional[np.ndarray]:
        """Load image as float32 HxWx3 array in range [0,1]."""
        try:
            import cv2
            if isinstance(image_input, np.ndarray):
                arr = image_input.astype(np.float32)
                if arr.max() > 1.0:
                    arr = arr / 255.0
                if arr.ndim == 2:
                    arr = np.stack([arr, arr, arr], axis=-1)
                return arr
            if isinstance(image_input, str):
                raw = cv2.imread(image_input)
                if raw is None:
                    return None
                return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            try:
                from PIL import Image as PILImage
                if hasattr(image_input, "convert"):
                    pil = image_input.convert("RGB")
                    return np.array(pil, dtype=np.float32) / 255.0
            except Exception:
                pass
        except Exception as exc:
            logger.debug("Image load for fallback failed: %s", exc)
        return None

    def _dct_embedding(self, arr: np.ndarray, target_dim: int) -> np.ndarray:
        """Extract multi-scale DCT feature vector from an image array."""
        import cv2
        target_size = 64
        resized = cv2.resize(arr, (target_size, target_size))
        ycrcb = cv2.cvtColor((resized * 255).astype(np.uint8), cv2.COLOR_RGB2YCrCb).astype(np.float32)

        features = []
        scales = [64, 32, 16, 8]
        for scale in scales:
            scaled = cv2.resize(ycrcb, (scale, scale))
            for ch in range(3):
                channel = scaled[:, :, ch] - 128.0
                dct = cv2.dct(channel)
                # Zig-zag low-frequency coefficients capture structure
                coeff_count = min(scale * scale, 32)
                zigzag = self._zigzag(dct, coeff_count)
                features.append(zigzag)

        raw = np.concatenate(features).astype(np.float32)

        # Tile or truncate to target_dim
        if raw.size == 0:
            return np.zeros(target_dim, dtype=np.float32)
        if raw.size >= target_dim:
            return raw[:target_dim]
        repeats = (target_dim // raw.size) + 1
        return np.tile(raw, repeats)[:target_dim]

    @staticmethod
    def _zigzag(matrix: np.ndarray, n: int) -> np.ndarray:
        """Extract first n coefficients in zigzag order from a 2D array."""
        h, w = matrix.shape
        result = []
        for diag in range(h + w - 1):
            if diag % 2 == 0:
                r = min(diag, h - 1)
                c = diag - r
                while r >= 0 and c < w:
                    result.append(matrix[r, c])
                    if len(result) >= n:
                        return np.array(result, dtype=np.float32)
                    r -= 1
                    c += 1
            else:
                c = min(diag, w - 1)
                r = diag - c
                while c >= 0 and r < h:
                    result.append(matrix[r, c])
                    if len(result) >= n:
                        return np.array(result, dtype=np.float32)
                    r += 1
                    c -= 1
        return np.array(result, dtype=np.float32)

    def _seed_from_input(self, image_input: Any) -> int:
        payload = str(image_input)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def _resize_embedding(self, emb: np.ndarray, output_dim: Optional[int]) -> np.ndarray:
        if not output_dim:
            return emb
        if emb.shape[0] >= output_dim:
            return emb[:output_dim]
        return np.pad(emb, (0, output_dim - emb.shape[0]))

    def _l2_normalize(self, emb: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(emb)
        if norm <= 1e-12:
            return emb
        return emb / norm


_vit_service: Optional[ViTEmbeddingService] = None


def get_vit_service() -> ViTEmbeddingService:
    """Return a cached ViT embedding service instance."""
    global _vit_service
    if _vit_service is None:
        _vit_service = ViTEmbeddingService()
    return _vit_service
