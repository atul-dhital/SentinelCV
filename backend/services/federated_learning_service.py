"""
Federated Learning Coordinator Service (ENH-016)

Implements Federated Averaging (FedAvg) for privacy-preserving
model training across distributed organizations.
"""

import logging
import numpy as np
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class FederatedLearningService:
    """Coordinates federated learning rounds using FedAvg."""

    def _get_round(self, db: Session, organization_id: str, round_id: str) -> Any:
        from models.models import FederatedRound

        fl_round = db.query(FederatedRound).filter(
            FederatedRound.id == round_id,
            FederatedRound.organization_id == organization_id,
        ).first()
        if not fl_round:
            raise ValueError("Round not found")
        return fl_round

    def initialize_round(
        self,
        db: Session,
        organization_id: str,
        model_type: str,
        num_participants: int,
        config: Optional[Dict] = None,
    ) -> Any:
        """Create a new federated learning round."""
        from models.models import FederatedRound

        fl_round = FederatedRound(
            organization_id=organization_id,
            model_type=model_type,
            num_participants=num_participants,
            status="initialized",
            round_number=self._get_next_round_number(db, organization_id, model_type),
            config=config or {
                "learning_rate": 0.01,
                "local_epochs": 5,
                "batch_size": 32,
                "aggregation_strategy": "fedavg",
                "min_participants": max(1, num_participants // 2),
                "differential_privacy": {"enabled": False, "epsilon": 1.0, "delta": 1e-5},
            },
        )
        db.add(fl_round)
        db.commit()
        db.refresh(fl_round)
        logger.info(f"Initialized FL round {fl_round.round_number} for {model_type}")
        return fl_round

    def _get_next_round_number(self, db: Session, org_id: str, model_type: str) -> int:
        from models.models import FederatedRound
        from sqlalchemy import func

        result = db.query(func.max(FederatedRound.round_number)).filter(
            FederatedRound.organization_id == org_id,
            FederatedRound.model_type == model_type,
        ).scalar()
        return (result or 0) + 1

    def submit_local_update(
        self,
        db: Session,
        organization_id: str,
        round_id: str,
        participant_id: str,
        weight_deltas: List[float],
        local_accuracy: float,
        local_loss: float = 0.0,
        num_samples: int = 0,
    ) -> Any:
        """Record a local training update from a participant."""
        from models.models import FederatedUpdate

        fl_round = self._get_round(db, organization_id, round_id)
        if fl_round.status == "aggregated":
            raise ValueError("Round already aggregated")

        update = db.query(FederatedUpdate).filter(
            FederatedUpdate.round_id == round_id,
            FederatedUpdate.participant_id == participant_id,
        ).first()

        if update is None:
            update = FederatedUpdate(
                round_id=round_id,
                participant_id=participant_id,
            )
            db.add(update)

        update.local_accuracy = local_accuracy
        update.local_loss = local_loss
        update.num_samples = num_samples
        update.weight_deltas = weight_deltas
        if fl_round.status == "initialized":
            fl_round.status = "collecting"
        db.commit()
        db.refresh(update)
        logger.info(f"Received update from participant {participant_id} for round {round_id}")
        return update

    def aggregate_updates(self, db: Session, organization_id: str, round_id: str) -> Dict:
        """
        Aggregate local updates using Federated Averaging (FedAvg).

        Weighted average of model deltas proportional to local dataset size.
        """
        from models.models import FederatedRound, FederatedUpdate

        fl_round = self._get_round(db, organization_id, round_id)

        updates = db.query(FederatedUpdate).filter(
            FederatedUpdate.round_id == round_id
        ).all()

        if not updates:
            raise ValueError("No updates to aggregate")

        config = fl_round.config or {}
        min_participants = config.get("min_participants", 1)

        if len(updates) < min_participants:
            return {
                "status": "waiting",
                "received": len(updates),
                "required": min_participants,
                "round_id": str(fl_round.id),
            }

        # FedAvg: weighted average by number of samples
        total_samples = sum(u.num_samples or 1 for u in updates)
        all_deltas = []
        weights = []

        for update in updates:
            deltas = update.weight_deltas
            if isinstance(deltas, list):
                all_deltas.append(np.array(deltas, dtype=np.float64))
                weights.append((update.num_samples or 1) / total_samples)

        if not all_deltas:
            raise ValueError("No valid weight deltas found")

        # Weighted average
        aggregated = np.zeros_like(all_deltas[0])
        for delta, weight in zip(all_deltas, weights):
            if delta.shape == aggregated.shape:
                aggregated += weight * delta

        # Apply differential privacy if configured
        dp_config = config.get("differential_privacy", {})
        if dp_config.get("enabled"):
            epsilon = dp_config.get("epsilon", 1.0)
            sensitivity = np.linalg.norm(aggregated)
            noise_scale = sensitivity / epsilon
            noise = np.random.laplace(0, noise_scale, aggregated.shape)
            aggregated += noise
            logger.info(f"Applied differential privacy (epsilon={epsilon})")

        # Update round
        avg_accuracy = np.mean([u.local_accuracy for u in updates])
        fl_round.status = "aggregated"
        fl_round.global_accuracy_after = float(avg_accuracy)
        if fl_round.global_accuracy_before is None:
            fl_round.global_accuracy_before = float(np.mean([u.local_accuracy for u in updates]))
        fl_round.aggregated_weights = aggregated.tolist()
        db.commit()

        logger.info(f"Aggregated {len(updates)} updates for round {round_id}")
        return {
            "status": "aggregated",
            "num_participants": len(updates),
            "global_accuracy": float(avg_accuracy),
            "aggregated_delta_norm": float(np.linalg.norm(aggregated)),
            "dp_applied": dp_config.get("enabled", False),
        }

    def get_round_status(self, db: Session, organization_id: str, round_id: str) -> Dict:
        """Get status of a federated learning round."""
        from models.models import FederatedRound, FederatedUpdate

        fl_round = self._get_round(db, organization_id, round_id)

        updates = db.query(FederatedUpdate).filter(
            FederatedUpdate.round_id == round_id
        ).all()

        return {
            "round_id": str(fl_round.id),
            "round_number": fl_round.round_number,
            "model_type": fl_round.model_type,
            "status": fl_round.status,
            "num_participants_expected": fl_round.num_participants,
            "num_participants_submitted": len(updates),
            "can_aggregate": len(updates) >= int((fl_round.config or {}).get("min_participants", 1)),
            "global_accuracy_before": fl_round.global_accuracy_before,
            "global_accuracy_after": fl_round.global_accuracy_after,
            "config": fl_round.config,
            "participants": [
                {
                    "participant_id": u.participant_id,
                    "local_accuracy": u.local_accuracy,
                    "num_samples": u.num_samples,
                    "submitted_at": u.submitted_at.isoformat() if u.submitted_at else None,
                }
                for u in updates
            ],
        }

    def list_rounds(
        self, db: Session, organization_id: str, limit: int = 20
    ) -> List[Dict]:
        """List federated learning rounds."""
        from models.models import FederatedRound

        rounds = db.query(FederatedRound).filter(
            FederatedRound.organization_id == organization_id
        ).order_by(FederatedRound.created_at.desc()).limit(limit).all()

        return [
            {
                "id": str(r.id),
                "round_number": r.round_number,
                "model_type": r.model_type,
                "status": r.status,
                "num_participants": r.num_participants,
                "global_accuracy_after": r.global_accuracy_after,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rounds
        ]


federated_learning_service = FederatedLearningService()
