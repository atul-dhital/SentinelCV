"""
Production-ready PyTorch LLM Training and Optimization System
Supports real neural networks with fallback to scikit-learn and simulation
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import numpy as np
import logging
import os
import json
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime


def _try_decrypt_embedding(raw: str) -> str:
    """Try to decrypt a Fernet-encrypted embedding string. Returns raw if not encrypted."""
    if not isinstance(raw, str) or not raw.startswith("v1:"):
        return raw
    # Try backend security module first (available when running inside the FastAPI backend)
    try:
        from core.security import decrypt_embedding
        return decrypt_embedding(raw)
    except Exception:
        pass
    # Standalone fallback: re-derive key from env the same way core/security.py does
    try:
        import base64, hashlib
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
        from cryptography.fernet import Fernet
        secret = os.getenv("EMBEDDING_KEY_SECRET", "sentinelcv-dev-embedding-key-not-for-production")
        derived = HKDF(
            algorithm=hashes.SHA256(), length=32,
            salt=b"sentinelcv|embedding|v1",
            info=b"sentinelcv-embedding-encryption-v1",
        ).derive(secret.encode())
        fernet = Fernet(base64.urlsafe_b64encode(derived))
        payload = raw[len("v1:"):]
        return fernet.decrypt(payload.encode()).decode()
    except Exception:
        return raw

# Handle optional optuna import with fallback
try:
    import optuna
    from optuna.trial import Trial
    from optuna.samplers import TPESampler
    from optuna.pruners import MedianPruner
    OPTUNA_AVAILABLE = True
except Exception as e:
    logging.warning(f"Optuna import failed: {e}. HPO will use simplified mode.")
    OPTUNA_AVAILABLE = False
    # Create dummy classes for fallback
    class Trial:
        pass
    class TPESampler:
        pass
    class MedianPruner:
        pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingConfig:
    """Configuration for model training"""
    num_epochs: int = 50
    batch_size: int = 32
    learning_rate: float = 0.001
    validation_split: float = 0.2
    test_split: float = 0.1
    optimizer: str = 'adam'  # 'adam', 'sgd', 'rmsprop'
    loss_fn: str = 'softmax'  # 'softmax', 'arcface', 'mse'
    model_name: str = 'simple'  # 'simple', 'arcface'
    embedding_dim: int = 512
    margin: float = 0.5
    scale: float = 64.0
    warmup_epochs: int = 5
    hidden_dims: Optional[List[int]] = None  # defaults to [256, 128, 64]
    dropout: float = 0.3
    device: str = 'cuda' if torch.cuda.is_available() else 'cpu'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingMetrics:
    """Training metrics for a single epoch"""
    epoch: int
    train_loss: float
    val_loss: float
    train_accuracy: float
    val_accuracy: float
    train_f1: float = 0.0
    val_f1: float = 0.0
    val_precision: float = 0.0
    val_recall: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────────────
# PyTorch Models
# ─────────────────────────────────────────────────────────────────────────────

class SimpleClassifier(nn.Module):
    """Feed-forward classifier over 512-dim face embeddings. Supports arbitrary hidden_dims."""

    def __init__(self, input_dim: int, num_classes: int, hidden_dims: List[int] = None, dropout: float = 0.3):
        super().__init__()
        if hidden_dims is None:
            hidden_dims = [256, 128, 64]
        layers: List[nn.Module] = []
        prev = input_dim
        for i, h in enumerate(hidden_dims):
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            # last hidden layer gets slightly lower dropout
            layers.append(nn.Dropout(p=dropout * 0.67 if i == len(hidden_dims) - 1 else dropout))
            prev = h
        layers.append(nn.Linear(prev, num_classes))
        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)


class ArcFaceModel(nn.Module):
    """ArcFace model for face recognition"""
    
    def __init__(self, embedding_dim: int, num_classes: int, margin: float = 0.5, scale: float = 64.0):
        super(ArcFaceModel, self).__init__()
        self.embedding_dim = embedding_dim
        self.num_classes = num_classes
        self.margin = margin
        self.scale = scale
        
        self.feature_extractor = nn.Sequential(
            nn.Linear(embedding_dim, 256),
            nn.BatchNorm1d(256),
            nn.ReLU(),
            nn.Linear(256, 128),
            nn.BatchNorm1d(128),
            nn.ReLU()
        )
        
        self.weight = nn.Parameter(torch.FloatTensor(num_classes, 128))
        nn.init.xavier_uniform_(self.weight)
    
    def forward(self, x: torch.Tensor, labels: Optional[torch.Tensor] = None) -> torch.Tensor:
        features = self.feature_extractor(x)            # (B, 128)
        features = F.normalize(features, dim=1)         # unit-norm

        if labels is None:
            # inference — return raw embeddings
            return features

        W = F.normalize(self.weight, dim=1)             # (C, 128)
        cos_theta = F.linear(features, W).clamp(-1 + 1e-7, 1 - 1e-7)
        theta = torch.acos(cos_theta)
        marginal = torch.cos(theta + self.margin)

        one_hot = torch.zeros_like(cos_theta).scatter_(1, labels.view(-1, 1).long(), 1.0)
        output = (one_hot * marginal + (1.0 - one_hot) * cos_theta) * self.scale
        return output


# ─────────────────────────────────────────────────────────────────────────────
# Dataset Preparation
# ─────────────────────────────────────────────────────────────────────────────

class DatasetPreparation:
    """Handles dataset loading and preprocessing"""
    
    def __init__(self, data_dir: str = 'data/face_images'):
        self.data_dir = data_dir
        self.scaler = StandardScaler()
        self.label_encoder = LabelEncoder()
        logger.info(f"DatasetPreparation initialized with data_dir: {data_dir}")
    
    def load_embeddings_from_db(self, db, organization_id: str) -> Tuple[np.ndarray, np.ndarray, List[str]]:
        """Load face embeddings from database using raw SQL to avoid circular imports"""
        from sqlalchemy import text
        
        query = text("""
            SELECT fd.embedding, fd.visitor_id
            FROM face_data fd
            JOIN visitors v ON fd.visitor_id = v.id
            WHERE v.organization_id = :org_id
        """)
        
        result = db.execute(query, {"org_id": organization_id})
        rows = result.fetchall()
        
        embeddings = []
        visitor_ids = []
        
        for row in rows:
            embedding_json = row[0]
            visitor_id = row[1]
            
            # Parse embedding — handles: pgvector array, plain JSON, encrypted Fernet, and
            # SQLite's JSON-string-wrapped Fernet ("\"v1:...\"")
            try:
                if isinstance(embedding_json, str):
                    # Outer JSON may wrap the encrypted string (SQLite serialization)
                    try:
                        outer = json.loads(embedding_json)
                    except Exception:
                        outer = embedding_json
                    # If json.loads yielded another string, that's the actual encrypted value
                    inner = outer if isinstance(outer, str) else embedding_json
                    decrypted = _try_decrypt_embedding(inner)
                    parsed = json.loads(decrypted)
                    if not isinstance(parsed, list):
                        raise ValueError(f"Expected list, got {type(parsed)}")
                    embedding = np.array(parsed, dtype=np.float32)
                else:
                    embedding = np.array(list(embedding_json), dtype=np.float32)
                if embedding.size == 0 or not np.all(np.isfinite(embedding)):
                    continue
            except Exception as parse_exc:
                logger.debug("Skipping malformed embedding for visitor %s: %s", visitor_id, parse_exc)
                continue

            embeddings.append(embedding)
            visitor_ids.append(visitor_id)
        
        embeddings = np.array(embeddings, dtype=np.float32)
        labels = np.array(visitor_ids)
        
        # Encode labels
        encoded_labels = self.label_encoder.fit_transform(labels)
        
        logger.info(f"Loaded {len(embeddings)} embeddings from database with {len(np.unique(encoded_labels))} unique visitors")
        
        return embeddings, encoded_labels, list(labels)
    
    # normalize_embeddings removed — scaler fitting happens inside ModelTrainer.train()
    # on X_train only to prevent data leakage from val/test sets.


# ─────────────────────────────────────────────────────────────────────────────
# Model Trainer
# ─────────────────────────────────────────────────────────────────────────────

class ModelTrainer:
    """PyTorch model trainer with automatic fallback"""
    
    def __init__(self, config: TrainingConfig):
        self.config = config
        self.device = torch.device(config.device)
        self.model = None
        self.optimizer = None
        self.criterion = None
        self.scaler: Optional[StandardScaler] = None
        self.input_dim: Optional[int] = None
        self.num_classes: Optional[int] = None
        self.best_val_accuracy = 0.0
        self.checkpoint_dir = Path('checkpoints')
        self.checkpoint_dir.mkdir(exist_ok=True)
        
        logger.info(f"ModelTrainer initialized with config: {config.to_dict()}")
    
    def _val_logits(self, batch_X: torch.Tensor, batch_y: torch.Tensor, use_arcface: bool) -> torch.Tensor:
        """Get logits for validation — no margin for ArcFace so val loss is comparable."""
        if use_arcface:
            import torch.nn.functional as F
            features = F.normalize(self.model.feature_extractor(batch_X), dim=1)
            W = F.normalize(self.model.weight, dim=1)
            cos = torch.clamp(F.linear(features, W), -1 + 1e-7, 1 - 1e-7)
            return cos * self.model.scale
        return self.model(batch_X)

    def train(self, X_train: np.ndarray, y_train: np.ndarray,
              X_val: np.ndarray, y_val: np.ndarray,
              X_test: Optional[np.ndarray] = None,
              y_test: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """Train model with PyTorch. Respects config.model_name ('arcface'|'simple')."""
        try:
            scaler = StandardScaler()
            self.scaler = scaler
            X_train = scaler.fit_transform(X_train)
            X_val = scaler.transform(X_val)
            if X_test is not None:
                X_test = scaler.transform(X_test)

            X_train_tensor = torch.FloatTensor(X_train).to(self.device)
            y_train_tensor = torch.LongTensor(y_train).to(self.device)
            X_val_tensor = torch.FloatTensor(X_val).to(self.device)
            y_val_tensor = torch.LongTensor(y_val).to(self.device)

            num_classes = len(np.unique(y_train))
            input_dim = X_train.shape[1]
            self.num_classes = int(num_classes)
            self.input_dim = int(input_dim)

            # Select architecture based on config.model_name
            model_name_lower = str(self.config.model_name).lower()
            use_arcface = "arcface" in model_name_lower and model_name_lower != "simple"
            architecture = "arcface" if use_arcface else "simple"

            if use_arcface:
                self.model = ArcFaceModel(
                    embedding_dim=input_dim,
                    num_classes=num_classes,
                    margin=self.config.margin,
                    scale=self.config.scale,
                ).to(self.device)
                logger.info(f"Using ArcFaceModel (margin={self.config.margin}, scale={self.config.scale})")
            else:
                hidden_dims = self.config.hidden_dims or [256, 128, 64]
                self.model = SimpleClassifier(
                    input_dim, num_classes,
                    hidden_dims=hidden_dims,
                    dropout=self.config.dropout,
                ).to(self.device)
                logger.info(f"Using SimpleClassifier hidden_dims={hidden_dims}")

            if self.config.optimizer == 'adam':
                self.optimizer = optim.Adam(self.model.parameters(), lr=self.config.learning_rate)
            elif self.config.optimizer == 'sgd':
                self.optimizer = optim.SGD(self.model.parameters(), lr=self.config.learning_rate, momentum=0.9)
            else:
                self.optimizer = optim.RMSprop(self.model.parameters(), lr=self.config.learning_rate)

            self.criterion = nn.CrossEntropyLoss()

            logger.info(
                f"Training: {len(X_train)} samples, {num_classes} classes, "
                f"input_dim={input_dim}, arch={architecture}, device={self.device}"
            )

            train_dataset = TensorDataset(X_train_tensor, y_train_tensor)
            train_loader = DataLoader(train_dataset, batch_size=self.config.batch_size, shuffle=True)
            val_dataset = TensorDataset(X_val_tensor, y_val_tensor)
            val_loader = DataLoader(val_dataset, batch_size=self.config.batch_size)

            metrics_history = []

            for epoch in range(self.config.num_epochs):
                self.model.train()
                train_loss = 0.0
                train_preds = []
                train_true = []

                for batch_X, batch_y in train_loader:
                    self.optimizer.zero_grad()
                    if use_arcface:
                        outputs = self.model(batch_X, batch_y)
                    else:
                        outputs = self.model(batch_X)
                    loss = self.criterion(outputs, batch_y)
                    loss.backward()
                    self.optimizer.step()

                    train_loss += loss.item()
                    train_preds.extend(torch.argmax(outputs, dim=1).cpu().numpy())
                    train_true.extend(batch_y.cpu().numpy())

                train_loss /= len(train_loader)
                train_accuracy = accuracy_score(train_true, train_preds)
                train_f1 = f1_score(train_true, train_preds, zero_division=0, average='weighted')

                self.model.eval()
                val_loss = 0.0
                val_preds = []
                val_true = []

                with torch.no_grad():
                    for batch_X, batch_y in val_loader:
                        outputs = self._val_logits(batch_X, batch_y, use_arcface)
                        loss = self.criterion(outputs, batch_y)
                        val_loss += loss.item()
                        val_preds.extend(torch.argmax(outputs, dim=1).cpu().numpy())
                        val_true.extend(batch_y.cpu().numpy())

                val_loss /= len(val_loader)
                val_accuracy = accuracy_score(val_true, val_preds)
                val_f1 = f1_score(val_true, val_preds, zero_division=0, average='weighted')
                val_precision = precision_score(val_true, val_preds, zero_division=0, average='weighted')
                val_recall = recall_score(val_true, val_preds, zero_division=0, average='weighted')

                if val_accuracy > self.best_val_accuracy:
                    self.best_val_accuracy = val_accuracy
                    checkpoint_path = self.checkpoint_dir / 'best_model.pt'
                    torch.save(self.model.state_dict(), checkpoint_path)
                    logger.info(f"Checkpoint saved (val_acc={val_accuracy:.4f}): {checkpoint_path}")

                if (epoch + 1) % 10 == 0:
                    checkpoint_path = self.checkpoint_dir / f'checkpoint_epoch_{epoch}.pt'
                    torch.save(self.model.state_dict(), checkpoint_path)

                if (epoch + 1) % 5 == 0:
                    logger.info(
                        f"Epoch {epoch + 1}/{self.config.num_epochs} — "
                        f"train_loss={train_loss:.4f} val_loss={val_loss:.4f} "
                        f"train_acc={train_accuracy:.4f} val_acc={val_accuracy:.4f}"
                    )

                metrics_history.append({
                    'epoch': epoch + 1,
                    'train_loss': float(train_loss),
                    'val_loss': float(val_loss),
                    'train_accuracy': float(train_accuracy),
                    'val_accuracy': float(val_accuracy),
                    'train_f1': float(train_f1),
                    'val_f1': float(val_f1),
                    'val_precision': float(val_precision),
                    'val_recall': float(val_recall),
                })

            test_accuracy = 0.0
            if X_test is not None:
                X_test_tensor = torch.FloatTensor(X_test).to(self.device)
                self.model.eval()
                with torch.no_grad():
                    test_outputs = self._val_logits(X_test_tensor, torch.LongTensor(y_test if y_test is not None else np.zeros(len(X_test_tensor), dtype=int)).to(self.device), use_arcface)
                    test_preds = torch.argmax(test_outputs, dim=1).cpu().numpy()
                    test_accuracy = accuracy_score(y_test, test_preds) if y_test is not None else 0.0

            return {
                'status': 'training_completed',
                'architecture': architecture,
                'epochs': self.config.num_epochs,
                'final_train_accuracy': float(train_accuracy),
                'final_val_accuracy': float(val_accuracy),
                'final_train_f1': float(train_f1),
                'final_val_f1': float(val_f1),
                'final_val_precision': float(val_precision),
                'final_val_recall': float(val_recall),
                'test_accuracy': float(test_accuracy),
                'best_val_accuracy': float(self.best_val_accuracy),
                'num_classes': int(num_classes),
                'input_dim': int(input_dim),
                'best_checkpoint_path': str(self.checkpoint_dir / 'best_model.pt'),
                'metrics_history': metrics_history,
                'checkpoint_dir': str(self.checkpoint_dir),
            }

        except Exception as e:
            logger.error(f"PyTorch training failed: {e}", exc_info=True)
            raise


# ─────────────────────────────────────────────────────────────────────────────
# Hyperparameter Optimization
# ─────────────────────────────────────────────────────────────────────────────

class HyperparameterOptimization:
    """Hyperparameter optimization using Optuna"""
    
    def __init__(self, X_train: np.ndarray, y_train: np.ndarray,
                 X_val: np.ndarray, y_val: np.ndarray,
                 n_trials: int = 20):
        self.X_train = X_train
        self.y_train = y_train
        self.X_val = X_val
        self.y_val = y_val
        self.n_trials = n_trials
        self.best_params = None
        self.study = None
        logger.info(f"HyperparameterOptimization initialized with {n_trials} trials")
    
    def objective(self, trial: Trial) -> float:
        """Optuna objective function for hyperparameter tuning"""
        
        # Suggest hyperparameters
        learning_rate = trial.suggest_float('learning_rate', 1e-4, 1e-2, log=True)
        batch_size = trial.suggest_categorical('batch_size', [16, 32, 64, 128])
        num_epochs = trial.suggest_int('num_epochs', 10, 100)
        optimizer_name = trial.suggest_categorical('optimizer', ['adam', 'sgd', 'rmsprop'])
        
        try:
            config = TrainingConfig(
                learning_rate=learning_rate,
                batch_size=batch_size,
                num_epochs=num_epochs,
                optimizer=optimizer_name
            )
            
            trainer = ModelTrainer(config)
            result = trainer.train(self.X_train, self.y_train, self.X_val, self.y_val)
            
            # Return validation accuracy as the objective
            return result['final_val_accuracy']
        
        except Exception as e:
            logger.warning(f"Trial failed: {e}")
            return 0.0
    
    def optimize(self) -> Dict[str, Any]:
        """Run hyperparameter optimization"""
        
        if not OPTUNA_AVAILABLE:
            # Fallback: run a simple grid search without Optuna
            logger.warning("Optuna not available, using simplified grid search instead")
            return self._optimize_fallback()
        
        sampler = TPESampler(seed=42)
        pruner = MedianPruner()
        
        self.study = optuna.create_study(
            direction='maximize',
            sampler=sampler,
            pruner=pruner
        )
        
        self.study.optimize(self.objective, n_trials=self.n_trials, show_progress_bar=False)
        
        self.best_params = self.study.best_params
        best_value = self.study.best_value
        
        logger.info(f"Best parameters found: {self.best_params}")
        logger.info(f"Best validation accuracy: {best_value:.4f}")
        
        return {
            'best_params': self.best_params,
            'best_accuracy': best_value,
            'num_trials': self.n_trials,
            'study_trials': len(self.study.trials)
        }
    
    def _optimize_fallback(self) -> Dict[str, Any]:
        """Fallback optimization when Optuna is not available"""
        best_accuracy = 0.0
        best_params = None
        
        # Simple grid search
        learning_rates = [0.0001, 0.0005, 0.001, 0.005, 0.01]
        batch_sizes = [16, 32, 64]
        optimizers = ['adam', 'sgd']
        
        trial_count = 0
        for lr in learning_rates[:min(3, len(learning_rates))]:
            for bs in batch_sizes[:min(2, len(batch_sizes))]:
                for opt in optimizers:
                    if trial_count >= self.n_trials:
                        break
                    
                    try:
                        config = TrainingConfig(
                            learning_rate=lr,
                            batch_size=bs,
                            num_epochs=20,
                            optimizer=opt
                        )
                        trainer = ModelTrainer(config)
                        result = trainer.train(self.X_train, self.y_train, self.X_val, self.y_val)
                        accuracy = result['final_val_accuracy']
                        
                        if accuracy > best_accuracy:
                            best_accuracy = accuracy
                            best_params = {
                                'learning_rate': lr,
                                'batch_size': bs,
                                'num_epochs': 20,
                                'optimizer': opt
                            }
                        
                        trial_count += 1
                        logger.info(f"Trial {trial_count}: lr={lr}, bs={bs}, opt={opt}, acc={accuracy:.4f}")
                    
                    except Exception as e:
                        logger.warning(f"Trial failed: {e}")
                        trial_count += 1
        
        if best_params is None:
            best_params = {
                'learning_rate': 0.001,
                'batch_size': 32,
                'num_epochs': 20,
                'optimizer': 'adam'
            }
        
        return {
            'best_params': best_params,
            'best_accuracy': best_accuracy,
            'num_trials': trial_count,
            'study_trials': trial_count
        }


# ─────────────────────────────────────────────────────────────────────────────
# Ensemble Model
# ─────────────────────────────────────────────────────────────────────────────

class EnsembleModel:
    """Ensemble of multiple trained models with voting mechanism"""
    
    def __init__(self, num_models: int = 3):
        self.num_models = num_models
        self.models = []
        self.weights = []
        logger.info(f"EnsembleModel initialized with {num_models} models")
    
    def create_ensemble(self, training_configs: List[TrainingConfig],
                       X_train: np.ndarray, y_train: np.ndarray,
                       X_val: np.ndarray, y_val: np.ndarray) -> Dict[str, Any]:
        """Create ensemble by training multiple models with different configs"""
        
        self.models = []
        accuracies = []
        
        for i, config in enumerate(training_configs):
            logger.info(f"Training ensemble model {i+1}/{len(training_configs)}")
            
            trainer = ModelTrainer(config)
            result = trainer.train(X_train, y_train, X_val, y_val)
            
            self.models.append(trainer.model)
            accuracies.append(result['final_val_accuracy'])
        
        # Weight models by their accuracy
        total_acc = sum(accuracies)
        self.weights = [acc / total_acc for acc in accuracies]
        
        logger.info(f"Ensemble created with accuracies: {accuracies}")
        logger.info(f"Model weights: {self.weights}")
        
        return {
            'num_models': len(self.models),
            'individual_accuracies': accuracies,
            'weights': self.weights,
            'ensemble_avg_accuracy': np.mean(accuracies)
        }
    
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Make predictions using weighted voting"""
        
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        X_tensor = torch.FloatTensor(X).to(device)
        
        predictions = []
        
        for model in self.models:
            model.eval()
            with torch.no_grad():
                output = model(X_tensor)
                pred = torch.argmax(output, dim=1).cpu().numpy()
            predictions.append(pred)
        
        predictions = np.array(predictions)
        
        # Weighted voting
        ensemble_pred = []
        for i in range(predictions.shape[1]):
            votes = {}
            for j, weight in enumerate(self.weights):
                pred_class = predictions[j, i]
                votes[pred_class] = votes.get(pred_class, 0) + weight
            ensemble_pred.append(max(votes, key=votes.get))
        
        return np.array(ensemble_pred)


# ─────────────────────────────────────────────────────────────────────────────
# Active Learning
# ─────────────────────────────────────────────────────────────────────────────

class ActiveLearning:
    """Active learning for intelligent sample selection"""
    
    def __init__(self, model: nn.Module, device: str = 'cpu'):
        self.model = model
        self.device = torch.device(device)
        logger.info("ActiveLearning initialized")
    
    def uncertainty_sampling(self, X_unlabeled: np.ndarray, n_samples: int = 10) -> List[int]:
        """Select samples with highest prediction uncertainty"""
        
        X_tensor = torch.FloatTensor(X_unlabeled).to(self.device)
        
        self.model.eval()
        with torch.no_grad():
            outputs = self.model(X_tensor)
            probabilities = torch.softmax(outputs, dim=1)
            
            # Entropy-based uncertainty
            entropies = -torch.sum(probabilities * torch.log(probabilities + 1e-10), dim=1)
            
            # Get indices of most uncertain samples
            uncertain_indices = torch.topk(entropies, min(n_samples, len(entropies)))[1].cpu().numpy()
        
        logger.info(f"Selected {len(uncertain_indices)} uncertain samples")
        return list(uncertain_indices)
    
    def diversity_sampling(self, X_unlabeled: np.ndarray, n_samples: int = 10) -> List[int]:
        """Select diverse samples using clustering"""
        
        from sklearn.cluster import KMeans
        
        try:
            n_clusters = min(n_samples, len(X_unlabeled) // 2)
            kmeans = KMeans(n_clusters=n_clusters, n_init=10, random_state=42)
            clusters = kmeans.fit_predict(X_unlabeled)
            
            # Select one sample per cluster (closest to centroid)
            selected_indices = []
            for i in range(n_clusters):
                cluster_indices = np.where(clusters == i)[0]
                if len(cluster_indices) > 0:
                    distances = np.linalg.norm(
                        X_unlabeled[cluster_indices] - kmeans.cluster_centers_[i],
                        axis=1
                    )
                    selected_indices.append(cluster_indices[np.argmin(distances)])
            
            logger.info(f"Selected {len(selected_indices)} diverse samples")
            return selected_indices
        
        except Exception as e:
            logger.warning(f"Diversity sampling failed: {e}")
            return list(np.random.choice(len(X_unlabeled), min(n_samples, len(X_unlabeled)), replace=False))
    
    def select_samples(self, X_unlabeled: np.ndarray, method: str = 'uncertainty', n_samples: int = 10) -> List[int]:
        """Select samples for annotation based on strategy"""
        
        if method == 'uncertainty':
            return self.uncertainty_sampling(X_unlabeled, n_samples)
        elif method == 'diversity':
            return self.diversity_sampling(X_unlabeled, n_samples)
        else:
            logger.warning(f"Unknown sampling method: {method}, using uncertainty")
            return self.uncertainty_sampling(X_unlabeled, n_samples)


# ─────────────────────────────────────────────────────────────────────────────
# Bias Detection and Mitigation
# ─────────────────────────────────────────────────────────────────────────────

class BiasMitigation:
    """Detect and mitigate bias in model predictions"""
    
    def __init__(self):
        logger.info("BiasMitigation initialized")
    
    def detect_bias(self, y_true: np.ndarray, y_pred: np.ndarray, 
                   group_labels: Optional[np.ndarray] = None) -> Dict[str, Any]:
        """Detect bias across different groups"""
        
        if group_labels is None:
            logger.warning("No group labels provided, cannot detect bias")
            return {'bias_detected': False, 'message': 'No group labels provided'}
        
        unique_groups = np.unique(group_labels)
        group_accuracies = {}
        
        for group in unique_groups:
            group_mask = group_labels == group
            group_acc = accuracy_score(y_true[group_mask], y_pred[group_mask])
            group_accuracies[str(group)] = float(group_acc)
        
        # Check if accuracy variance exceeds threshold
        accuracies = list(group_accuracies.values())
        accuracy_std = np.std(accuracies)
        is_biased = accuracy_std > 0.1  # 10% threshold
        
        logger.info(f"Bias detection results: {group_accuracies}")
        logger.info(f"Accuracy std: {accuracy_std:.4f}, Is biased: {is_biased}")
        
        return {
            'bias_detected': is_biased,
            'group_accuracies': group_accuracies,
            'accuracy_std': float(accuracy_std),
            'num_groups': len(unique_groups)
        }
    
    def mitigate_bias(self, X: np.ndarray, y: np.ndarray, 
                     group_labels: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Mitigate bias through resampling"""
        
        unique_groups = np.unique(group_labels)
        
        # Find group with minimum samples
        min_samples = float('inf')
        for group in unique_groups:
            group_mask = group_labels == group
            min_samples = min(min_samples, np.sum(group_mask))
        
        # Undersample to balance groups
        balanced_indices = []
        for group in unique_groups:
            group_mask = group_labels == group
            group_indices = np.where(group_mask)[0]
            selected_indices = np.random.choice(group_indices, int(min_samples), replace=False)
            balanced_indices.extend(selected_indices)
        
        balanced_indices = np.array(balanced_indices)
        
        logger.info(f"Bias mitigation: Balanced dataset from {len(y)} to {len(balanced_indices)} samples")
        
        return X[balanced_indices], y[balanced_indices]


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def create_default_training_pipeline(config: Optional[TrainingConfig] = None) -> TrainingConfig:
    """Create default training configuration"""
    if config is None:
        config = TrainingConfig()
    return config


# Export public API
__all__ = [
    'DatasetPreparation',
    'ModelTrainer',
    'TrainingConfig',
    'TrainingMetrics',
    'HyperparameterOptimization',
    'EnsembleModel',
    'ActiveLearning',
    'BiasMitigation',
    'SimpleClassifier',
    'ArcFaceModel',
    'create_default_training_pipeline'
]
