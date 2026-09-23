#!/usr/bin/env python
"""Calibrate FACE_SEARCH_THRESHOLD against the REAL enrolled gallery.

Unlike benchmark_accuracy.py (which uses random synthetic embeddings for a
self-test), this sweeps the recognition threshold against the actual face
embeddings stored for an organization and reports precision / recall / F1 /
accuracy + the Equal Error Rate, then recommends a threshold.

Method (standard biometric verification eval):
  - genuine pairs  : two embeddings of the SAME visitor   -> should match
  - impostor pairs : embeddings of DIFFERENT visitors      -> should NOT match
  - cosine similarity is computed for each pair (same metric the matcher uses)
  - for each candidate threshold T: a pair "matches" if sim >= T
      TP = genuine matched, FN = genuine missed
      FP = impostor matched, TN = impostor rejected
  - report metrics per T; recommend the T with the highest F1 (and show EER)

Requirements: the org must have several visitors, each with >= 2 enrolled faces,
for meaningful genuine pairs. Garbage in (few faces) -> low-confidence advice.

Usage:
    python backend/scripts/calibrate_threshold.py --org <ORG_UUID>
    python backend/scripts/calibrate_threshold.py --org <ORG_UUID> --json
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Make the backend package importable when run from the repo root.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

MAX_GENUINE_PER_VISITOR = 50   # cap within-visitor pair explosion
MAX_IMPOSTOR_PAIRS = 5000      # cap cross-visitor pair sampling


def _cosine(a: List[float], b: List[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(a[i] * a[i] for i in range(n)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(n)))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_embeddings(org_id: str) -> Dict[str, List[List[float]]]:
    """Return {visitor_id: [embedding, ...]} for the org, decoding stored vectors."""
    from db.base import SessionLocal
    from models import models
    from services import visitor_service

    # Set tenant context so the global filter (if enabled) admits the rows.
    try:
        from core.authz import set_current_tenant  # type: ignore
        set_current_tenant(org_id)
    except Exception:
        try:
            from db.base import set_current_tenant  # type: ignore
            set_current_tenant(org_id)
        except Exception:
            pass  # filter may be off in this environment

    by_visitor: Dict[str, List[List[float]]] = {}
    db = SessionLocal()
    try:
        rows = (
            db.query(models.FaceData, models.Visitor)
            .join(models.Visitor, models.FaceData.visitor_id == models.Visitor.id)
            .filter(models.Visitor.organization_id == org_id)
            .filter(models.FaceData.embedding.isnot(None))
            .all()
        )
        for face, visitor in rows:
            emb = visitor_service.parse_embedding_payload(face.embedding)
            if emb:
                by_visitor.setdefault(str(visitor.id), []).append(emb)
    finally:
        db.close()
    return by_visitor


def _build_pairs(by_visitor: Dict[str, List[List[float]]]) -> Tuple[List[float], List[float]]:
    """Return (genuine_similarities, impostor_similarities)."""
    genuine: List[float] = []
    impostor: List[float] = []

    # Genuine: same-visitor combinations.
    for embs in by_visitor.values():
        combos = list(itertools.combinations(range(len(embs)), 2))
        random.shuffle(combos)
        for i, j in combos[:MAX_GENUINE_PER_VISITOR]:
            genuine.append(_cosine(embs[i], embs[j]))

    # Impostor: sampled cross-visitor pairs.
    visitor_ids = list(by_visitor.keys())
    rng = random.Random(0)
    attempts = 0
    while len(impostor) < MAX_IMPOSTOR_PAIRS and attempts < MAX_IMPOSTOR_PAIRS * 4 and len(visitor_ids) > 1:
        attempts += 1
        va, vb = rng.sample(visitor_ids, 2)
        ea = rng.choice(by_visitor[va])
        eb = rng.choice(by_visitor[vb])
        impostor.append(_cosine(ea, eb))

    return genuine, impostor


def _sweep(genuine: List[float], impostor: List[float]) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    t = 0.30
    while t <= 0.901:
        tp = sum(1 for s in genuine if s >= t)
        fn = len(genuine) - tp
        fp = sum(1 for s in impostor if s >= t)
        tn = len(impostor) - fp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        accuracy = (tp + tn) / (tp + tn + fp + fn) if (tp + tn + fp + fn) else 0.0
        far = fp / (fp + tn) if (fp + tn) else 0.0   # false accept rate (impostor matched)
        frr = fn / (fn + tp) if (fn + tp) else 0.0   # false reject rate (genuine missed)
        rows.append({
            "threshold": round(t, 3), "precision": round(precision, 4),
            "recall": round(recall, 4), "f1": round(f1, 4),
            "accuracy": round(accuracy, 4), "far": round(far, 4), "frr": round(frr, 4),
        })
        t += 0.02
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate face threshold on the real gallery.")
    parser.add_argument("--org", required=True, help="Organization UUID to calibrate against.")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    args = parser.parse_args()

    by_visitor = _load_embeddings(args.org)
    multi = {v: e for v, e in by_visitor.items() if len(e) >= 2}
    genuine, impostor = _build_pairs(by_visitor)

    if not genuine or not impostor:
        msg = (
            "Not enough data to calibrate: need multiple visitors and visitors with "
            ">= 2 enrolled faces.\n"
            f"  visitors={len(by_visitor)}  visitors_with_2+_faces={len(multi)}  "
            f"genuine_pairs={len(genuine)}  impostor_pairs={len(impostor)}"
        )
        print(msg)
        return 1

    rows = _sweep(genuine, impostor)
    best = max(rows, key=lambda r: (r["f1"], r["accuracy"]))
    # EER: threshold where FAR ~= FRR.
    eer_row = min(rows, key=lambda r: abs(r["far"] - r["frr"]))

    if args.json:
        print(json.dumps({
            "stats": {"visitors": len(by_visitor), "visitors_with_2plus_faces": len(multi),
                       "genuine_pairs": len(genuine), "impostor_pairs": len(impostor)},
            "recommended_threshold": best["threshold"],
            "eer_threshold": eer_row["threshold"],
            "sweep": rows,
        }, indent=2))
        return 0

    print("=" * 78)
    print("Face Threshold Calibration (real gallery)")
    print("=" * 78)
    print(f"visitors={len(by_visitor)}  with 2+ faces={len(multi)}  "
          f"genuine_pairs={len(genuine)}  impostor_pairs={len(impostor)}")
    print("-" * 78)
    print(f"{'thresh':>7} {'precision':>10} {'recall':>8} {'f1':>7} {'acc':>7} {'FAR':>7} {'FRR':>7}")
    for r in rows:
        mark = "  <= best F1" if r["threshold"] == best["threshold"] else (
            "  <= EER" if r["threshold"] == eer_row["threshold"] else "")
        print(f"{r['threshold']:>7} {r['precision']:>10} {r['recall']:>8} "
              f"{r['f1']:>7} {r['accuracy']:>7} {r['far']:>7} {r['frr']:>7}{mark}")
    print("-" * 78)
    print(f"Recommended FACE_SEARCH_THRESHOLD / FACE_CONFIDENCE_THRESHOLD = {best['threshold']} "
          f"(max F1={best['f1']}, accuracy={best['accuracy']})")
    print(f"Equal Error Rate near threshold {eer_row['threshold']} "
          f"(FAR={eer_row['far']}, FRR={eer_row['frr']})")
    print("Note: for a SECURITY system, prefer a slightly HIGHER threshold than max-F1")
    print("to cut false accepts (misidentifying a stranger as a known visitor).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
