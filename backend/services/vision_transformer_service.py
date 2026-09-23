"""
Vision Transformer (ViT) Face Recognition Service

Implements high-accuracy face recognition using Vision Transformer models.
Includes:
- ViT-Base and ViT-Large pre-trained model support
- Fine-tuning on organization-specific visitor data
- Performance comparison with ArcFace baseline
- Seamless integration with existing recognition pipeline

References:
- Vision Transformer: https://arxiv.org/abs/2010.11929
- Timm library: https://github.com/rwightman/pytorch-image-models
"""

import logging
import os
import numpy as np
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path
import json
from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib
import pickle

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.utils.data import Dataset, DataLoader
from PIL import Image
import cv2

try:
    import timm
    TIMM_AVAILABLE = True
except ImportError:
    TIMM_AVAILABLE = False
    logging.warning("timm library not installed. Install with: pip install timm")

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION & DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ViTConfig:
    """Vision Transformer configuration."""
    model_type: str = "vit_base_patch16_384"  # timm model name
    embedding_dim: int = 768
    input_size: int = 384
    num_classes: int = 1000  # ImageNet classes
    pretrained: bool = True
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
    fine_tune_layers: int = 3  # Fine-tune last N transformer blocks


@dataclass
class FinetuneConfig:
    """Fine-tuning configuration."""
    num_epochs: int = 5
    batch_size: int = 16
    learning_rate: float = 1e-5
    weight_decay: float = 1e-4
    warmup_epochs: int = 1
    use_cosine_scheduler: bool = True
    save_checkpoint_every_n_epochs: int = 1
    early_stopping_patience: int = 3


# ═══════════════════════════════════════════════════════════════════════════════
# VISION TRANSFORMER SERVICE
# ═══════════════════════════════════════════════════════════════════════════════

class VisionTransformerService:
    """
    High-performance face recognition using Vision Transformers.
    
    Provides:
    - Pre-trained ViT model loading
    - Fine-tuning on organization data
    - Fast embedding extraction
    - Similarity comparison
    """
    
    def __init__(self, config: Optional[ViTConfig] = None):
        """Initialize Vision Transformer service.
        
        Args:
            config: ViT configuration (uses defaults if None)
        """
        self.config = config or ViTConfig()
        self.model = None
        self.device = torch.device(self.config.device)
        self.fine_tune_config = FinetuneConfig()
        self.loaded_model_info = None
        
        logger.info(
            f"VisionTransformerService initialized: "
            f"model={self.config.model_type}, device={self.device}"
        )
    
    def load_model(self) -> bool:
        """
        Load pre-trained Vision Transformer model.
        
        Returns:
            True if loaded successfully, False otherwise
        """
        if not TIMM_AVAILABLE:
            logger.error("timm library not available")
            return False
        
        try:
            logger.info(f"Loading model: {self.config.model_type}")
            
            # Load pre-trained model from timm
            self.model = timm.create_model(
                self.config.model_type,
                pretrained=self.config.pretrained,
                num_classes=self.config.embedding_dim,  # Output embedding dimension
            )
            
            # Move to device
            self.model = self.model.to(self.device)
            self.model.eval()
            
            self.loaded_model_info = {
                "model_type": self.config.model_type,
                "embedding_dim": self.config.embedding_dim,
                "input_size": self.config.input_size,
                "loaded_at": datetime.utcnow().isoformat(),
            }
            
            # Count parameters
            total_params = sum(p.numel() for p in self.model.parameters())
            trainable_params = sum(
                p.numel() for p in self.model.parameters() if p.requires_grad
            )
            
            logger.info(
                f"Model loaded successfully: "
                f"{total_params:,} total parameters, "
                f"{trainable_params:,} trainable"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}", exc_info=True)
            return False
    
    def extract_embedding(
        self,
        face_image: Any,
        normalize: bool = True,
    ) -> Optional[List[float]]:
        """
        Extract face embedding using Vision Transformer.
        
        Args:
            face_image: Face image (PIL Image, numpy array, or file path)
            normalize: Whether to L2-normalize the embedding
            
        Returns:
            Embedding vector (768 dims for ViT-Base), or None if failed
        """
        if self.model is None:
            logger.error("Model not loaded. Call load_model() first.")
            return None
        
        try:
            # Prepare image
            image_tensor = self._prepare_image(face_image)
            if image_tensor is None:
                return None
            
            # Extract embedding
            with torch.no_grad():
                embedding = self.model(image_tensor)
            
            # Convert to numpy
            embedding_np = embedding.cpu().numpy().flatten()
            
            # L2 normalization
            if normalize:
                embedding_np = embedding_np / (
                    np.linalg.norm(embedding_np) + 1e-8
                )
            
            return embedding_np.tolist()
            
        except Exception as e:
            logger.error(f"Failed to extract embedding: {e}", exc_info=True)
            return None
    
    def compare_embeddings(
        self,
        emb1: List[float],
        emb2: List[float],
    ) -> float:
        """
        Compare two embeddings, return cosine similarity.
        
        Args:
            emb1: First embedding vector
            emb2: Second embedding vector
            
        Returns:
            Similarity score (0.0-1.0)
        """
        try:
            emb1_arr = np.array(emb1, dtype=np.float32)
            emb2_arr = np.array(emb2, dtype=np.float32)
            
            # Cosine similarity
            similarity = np.dot(emb1_arr, emb2_arr) / (
                np.linalg.norm(emb1_arr) * np.linalg.norm(emb2_arr) + 1e-8
            )
            
            return float(np.clip(similarity, 0.0, 1.0))
            
        except Exception as e:
            logger.error(f"Failed to compare embeddings: {e}")
            return 0.0
    
    def compare_embeddings_batch(
        self,
        probe_embedding: List[float],
        gallery_embeddings: List[List[float]],
    ) -> List[float]:
        """
        Compare one embedding against a gallery (vectorized).
        
        Args:
            probe_embedding: Query embedding
            gallery_embeddings: List of gallery embeddings
            
        Returns:
            List of similarity scores
        """
        probe_arr = np.array(probe_embedding, dtype=np.float32)
        gallery_arr = np.array(gallery_embeddings, dtype=np.float32)
        
        # Normalize
        probe_arr = probe_arr / (np.linalg.norm(probe_arr) + 1e-8)
        gallery_arr = gallery_arr / (
            np.linalg.norm(gallery_arr, axis=1, keepdims=True) + 1e-8
        )
        
        # Batch cosine similarity
        similarities = np.dot(gallery_arr, probe_arr)
        return similarities.tolist()
    
    def fine_tune_on_org_data(
        self,
        organization_id: str,
        visitor_face_images: Dict[str, List[str]],
        num_epochs: Optional[int] = None,
        learning_rate: Optional[float] = None,
        output_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        Fine-tune Vision Transformer on organization-specific visitor data.
        
        Args:
            organization_id: Organization ID for which to fine-tune
            visitor_face_images: {visitor_id: [image_paths]} mapping
            num_epochs: Number of fine-tuning epochs (override default)
            learning_rate: Learning rate (override default)
            output_dir: Directory to save fine-tuned model
            
        Returns:
            Dictionary with fine-tuning results and metrics
        """
        if self.model is None:
            return {"status": "error", "message": "Model not loaded"}
        
        if not visitor_face_images or sum(
            len(imgs) for imgs in visitor_face_images.values()
        ) < 10:
            return {
                "status": "skipped",
                "message": "Insufficient training data (need 10+ images)",
            }
        
        try:
            logger.info(
                f"Starting fine-tuning for org {organization_id} "
                f"with {len(visitor_face_images)} visitors"
            )
            
            # Prepare configuration
            ft_config = self.fine_tune_config
            if num_epochs:
                ft_config.num_epochs = num_epochs
            if learning_rate:
                ft_config.learning_rate = learning_rate
            
            # Output directory
            if output_dir is None:
                output_dir = Path(f"models/vit_finetuned/{organization_id}")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Create dataset
            dataset = VisitorFaceDataset(
                visitor_face_images,
                input_size=self.config.input_size,
            )
            dataloader = DataLoader(
                dataset,
                batch_size=ft_config.batch_size,
                shuffle=True,
                num_workers=0,
            )
            
            # Fine-tuning loop
            results = self._fine_tune_loop(
                dataloader,
                ft_config,
                output_dir,
            )
            
            # Save fine-tuned model
            model_path = output_dir / "model.pt"
            torch.save(self.model.state_dict(), model_path)
            
            results["model_path"] = str(model_path)
            results["status"] = "completed"
            
            logger.info(f"Fine-tuning completed: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Fine-tuning failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    def load_finetuned_model(
        self,
        organization_id: str,
        model_path: Optional[Path] = None,
    ) -> bool:
        """
        Load organization-specific fine-tuned model.
        
        Args:
            organization_id: Organization ID
            model_path: Path to fine-tuned model (auto-detected if None)
            
        Returns:
            True if loaded successfully
        """
        if model_path is None:
            model_path = Path(f"models/vit_finetuned/{organization_id}/model.pt")
        
        if not model_path.exists():
            logger.warning(f"Fine-tuned model not found: {model_path}")
            return False
        
        try:
            logger.info(f"Loading fine-tuned model from {model_path}")
            state_dict = torch.load(model_path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(state_dict)
            self.model.eval()
            logger.info("Fine-tuned model loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to load fine-tuned model: {e}")
            return False
    
    def benchmark_against_arcface(
        self,
        test_pairs: List[Tuple[str, str, bool]],
    ) -> Dict[str, Any]:
        """
        Benchmark Vision Transformer against ArcFace.
        
        Args:
            test_pairs: List of (image1_path, image2_path, is_same) tuples
            
        Returns:
            Benchmark results with accuracy, speed, etc.
        """
        try:
            logger.info(f"Benchmarking against {len(test_pairs)} image pairs")
            
            from services.liveness_service import get_face_app
            
            face_app = get_face_app()
            
            vit_scores = []
            arcface_scores = []
            inference_times_vit = []
            inference_times_arcface = []
            
            for idx, (img1_path, img2_path, is_same) in enumerate(test_pairs):
                try:
                    img1 = cv2.imread(img1_path)
                    img2 = cv2.imread(img2_path)
                    
                    if img1 is None or img2 is None:
                        logger.warning(f"Failed to read images: {img1_path}, {img2_path}")
                        continue
                    
                    # ArcFace extraction
                    import time
                    
                    t0 = time.time()
                    face_data1 = face_app.get(img1)
                    face_data2 = face_app.get(img2)
                    t_arcface = time.time() - t0
                    
                    if face_data1 and face_data2:
                        arcface_sim = float(
                            np.dot(face_data1[0].embedding, face_data2[0].embedding) / (
                                np.linalg.norm(face_data1[0].embedding) *
                                np.linalg.norm(face_data2[0].embedding) + 1e-8
                            )
                        )
                        arcface_scores.append(arcface_sim)
                        inference_times_arcface.append(t_arcface)
                    
                    # ViT extraction
                    t0 = time.time()
                    vit_emb1 = self.extract_embedding(img1)
                    vit_emb2 = self.extract_embedding(img2)
                    t_vit = time.time() - t0
                    
                    if vit_emb1 and vit_emb2:
                        vit_sim = self.compare_embeddings(vit_emb1, vit_emb2)
                        vit_scores.append(vit_sim)
                        inference_times_vit.append(t_vit)
                    
                except Exception as e:
                    logger.warning(f"Failed to process pair {idx}: {e}")
                    continue
            
            # Calculate metrics
            metrics = {
                "total_pairs": len(test_pairs),
                "processed_pairs": len(vit_scores),
                "vit_accuracy": self._compute_accuracy(vit_scores, [
                    int(pair[2]) for pair in test_pairs[:len(vit_scores)]
                ]),
                "arcface_accuracy": self._compute_accuracy(arcface_scores, [
                    int(pair[2]) for pair in test_pairs[:len(arcface_scores)]
                ]),
                "vit_avg_inference_ms": np.mean(inference_times_vit) * 1000,
                "arcface_avg_inference_ms": np.mean(inference_times_arcface) * 1000,
                "improvement_pct": (
                    (self._compute_accuracy(vit_scores, [
                        int(pair[2]) for pair in test_pairs[:len(vit_scores)]
                    ]) - self._compute_accuracy(arcface_scores, [
                        int(pair[2]) for pair in test_pairs[:len(arcface_scores)]
                    ])) * 100
                ) if arcface_scores else None,
            }
            
            logger.info(f"Benchmark results: {metrics}")
            return metrics
            
        except Exception as e:
            logger.error(f"Benchmark failed: {e}")
            return {"status": "error", "message": str(e)}
    
    # ─── Private Methods ─────────────────────────────────────────────────────
    
    def _prepare_image(self, image_input: Any) -> Optional[torch.Tensor]:
        """Convert various image formats to tensor."""
        try:
            # Load image if it's a path
            if isinstance(image_input, str):
                image = Image.open(image_input).convert("RGB")
            elif isinstance(image_input, Image.Image):
                image = image_input.convert("RGB")
            elif isinstance(image_input, np.ndarray):
                if image_input.dtype == np.uint8:
                    image = Image.fromarray(
                        cv2.cvtColor(image_input, cv2.COLOR_BGR2RGB)
                    )
                else:
                    image = Image.fromarray((image_input * 255).astype(np.uint8))
            else:
                logger.error(f"Unsupported image type: {type(image_input)}")
                return None
            
            # Resize to input size
            image = image.resize(
                (self.config.input_size, self.config.input_size),
                Image.Resampling.LANCZOS,
            )
            
            # Convert to tensor
            image_tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float()
            
            # Normalize (ImageNet stats)
            mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
            std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
            image_tensor = (image_tensor / 255.0 - mean) / std
            
            return image_tensor.unsqueeze(0).to(self.device)
            
        except Exception as e:
            logger.error(f"Image preparation failed: {e}")
            return None
    
    def _fine_tune_loop(
        self,
        dataloader: DataLoader,
        config: FinetuneConfig,
        output_dir: Path,
    ) -> Dict[str, Any]:
        """Execute fine-tuning loop."""
        optimizer = AdamW(
            self.model.parameters(),
            lr=config.learning_rate,
            weight_decay=config.weight_decay,
        )
        
        loss_fn = nn.CrossEntropyLoss()
        
        results = {
            "epochs": [],
            "train_losses": [],
            "best_loss": float("inf"),
        }
        
        for epoch in range(config.num_epochs):
            total_loss = 0.0
            num_batches = 0
            
            for batch_images, batch_labels in dataloader:
                optimizer.zero_grad()
                
                outputs = self.model(batch_images)
                loss = loss_fn(outputs, batch_labels)
                
                loss.backward()
                optimizer.step()
                
                total_loss += loss.item()
                num_batches += 1
            
            avg_loss = total_loss / max(num_batches, 1)
            results["train_losses"].append(avg_loss)
            
            if avg_loss < results["best_loss"]:
                results["best_loss"] = avg_loss
            
            logger.info(f"Epoch {epoch + 1}/{config.num_epochs} - Loss: {avg_loss:.4f}")
            
            # Save checkpoint
            if (epoch + 1) % config.save_checkpoint_every_n_epochs == 0:
                checkpoint_path = output_dir / f"checkpoint_epoch_{epoch + 1}.pt"
                torch.save(self.model.state_dict(), checkpoint_path)
        
        results["final_loss"] = results["train_losses"][-1]
        return results
    
    def _compute_accuracy(
        self,
        similarities: List[float],
        labels: List[int],
        threshold: float = 0.5,
    ) -> float:
        """Compute accuracy at given threshold."""
        if not similarities or not labels:
            return 0.0
        
        predictions = [1 if s > threshold else 0 for s in similarities]
        correct = sum(p == l for p, l in zip(predictions, labels))
        return correct / len(labels)


# ═══════════════════════════════════════════════════════════════════════════════
# DATASET FOR FINE-TUNING
# ═══════════════════════════════════════════════════════════════════════════════

class VisitorFaceDataset(Dataset):
    """Dataset of visitor face images for fine-tuning."""
    
    def __init__(
        self,
        visitor_face_images: Dict[str, List[str]],
        input_size: int = 384,
    ):
        """Initialize dataset.
        
        Args:
            visitor_face_images: {visitor_id: [image_paths]}
            input_size: Input image size for ViT
        """
        self.input_size = input_size
        self.samples = []
        self.label_map = {}
        
        # Create samples and labels
        for label, (visitor_id, image_paths) in enumerate(visitor_face_images.items()):
            self.label_map[visitor_id] = label
            for image_path in image_paths:
                if Path(image_path).exists():
                    self.samples.append((image_path, label))
    
    def __len__(self) -> int:
        return len(self.samples)
    
    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, int]:
        image_path, label = self.samples[idx]
        
        # Load and preprocess image
        image = Image.open(image_path).convert("RGB")
        image = image.resize(
            (self.input_size, self.input_size),
            Image.Resampling.LANCZOS,
        )
        
        # Convert to tensor
        image_tensor = torch.from_numpy(np.array(image)).permute(2, 0, 1).float()
        
        # Normalize
        mean = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
        std = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)
        image_tensor = (image_tensor / 255.0 - mean) / std
        
        return image_tensor, label
