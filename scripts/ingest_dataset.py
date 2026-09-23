"""
Dataset Ingestion Script for SentinelCV
========================================
Extracts face embeddings from LFW / CFP / Multi-pose zip files
and inserts them into the SentinelCV database as Visitor + FaceData records.

Usage:
    python scripts/ingest_dataset.py \
        --zip path/to/lfw.zip \
        --dataset lfw \
        --org-id <your-organization-uuid> \
        --max-people 100 \
        --max-per-person 10

Dataset types: lfw | cfp | multipose
"""

import sys
import os
import argparse
import zipfile
import tempfile
import shutil
import logging
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

# -- Path setup ----------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPT_DIR.parent / "backend"
sys.path.insert(0, str(_BACKEND_DIR))
sys.path.insert(0, str(_SCRIPT_DIR.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ingest")


# -- Embedding extraction ------------------------------------------------------

def extract_embedding(image_path: str, model_name: str = "ArcFace") -> Optional[List[float]]:
    """Run DeepFace to get a 512-d embedding from a face image."""
    try:
        from deepface import DeepFace
        result = DeepFace.represent(
            img_path=image_path,
            model_name=model_name,
            detector_backend="opencv",
            enforce_detection=False,
            align=True,
        )
        if result and isinstance(result, list):
            embedding = result[0].get("embedding")
            if embedding and len(embedding) > 0:
                return [float(v) for v in embedding]
    except Exception as exc:
        logger.debug("Embedding failed for %s: %s", image_path, exc)
    return None


# -- Dataset parsers -----------------------------------------------------------

def _discover_lfw(root: Path, max_people: int, max_per_person: int) -> List[Tuple[str, List[Path]]]:
    """LFW: root/Person_Name/Person_Name_XXXX.jpg"""
    people = []
    for person_dir in sorted(root.iterdir()):
        if not person_dir.is_dir():
            continue
        images = sorted(person_dir.glob("*.jpg")) + sorted(person_dir.glob("*.png"))
        if len(images) < 2:
            continue  # skip singletons ? not useful for training
        people.append((person_dir.name.replace("_", " "), images[:max_per_person]))
        if len(people) >= max_people:
            break
    return people


def _discover_cfp(root: Path, max_people: int, max_per_person: int) -> List[Tuple[str, List[Path]]]:
    """CFP: root/Data/Images/NNN/frontal/*.jpg + /profile/*.jpg"""
    images_root = root / "Data" / "Images"
    if not images_root.exists():
        # Try alternate layout
        images_root = root / "images"
    if not images_root.exists():
        images_root = root

    people = []
    for person_dir in sorted(images_root.iterdir()):
        if not person_dir.is_dir():
            continue
        frontal = sorted((person_dir / "frontal").glob("*.jpg")) if (person_dir / "frontal").exists() else []
        profile = sorted((person_dir / "profile").glob("*.jpg")) if (person_dir / "profile").exists() else []
        # Interleave frontal and profile for angle diversity
        combined: List[Path] = []
        for f, p in zip(frontal, profile):
            combined += [f, p]
        combined += frontal[len(profile):] + profile[len(frontal):]
        if not combined:
            all_imgs = sorted(person_dir.rglob("*.jpg"))
            if not all_imgs:
                continue
            combined = all_imgs
        people.append((f"CFP_{person_dir.name}", combined[:max_per_person]))
        if len(people) >= max_people:
            break
    return people


def _discover_multipose(root: Path, max_people: int, max_per_person: int) -> List[Tuple[str, List[Path]]]:
    """Multi-pose: root/subject_id/angle_or_image.jpg (flexible)"""
    people = []
    for subject_dir in sorted(root.iterdir()):
        if not subject_dir.is_dir():
            continue
        images = sorted(subject_dir.rglob("*.jpg")) + sorted(subject_dir.rglob("*.png"))
        if not images:
            continue
        people.append((f"Subject_{subject_dir.name}", images[:max_per_person]))
        if len(people) >= max_people:
            break
    return people


DATASET_PARSERS = {
    "lfw": _discover_lfw,
    "cfp": _discover_cfp,
    "multipose": _discover_multipose,
}


# -- DB ingestion --------------------------------------------------------------

def ingest_person(
    db,
    org_id: uuid.UUID,
    name: str,
    images: List[Path],
    model_name: str,
    dry_run: bool,
) -> Tuple[int, int]:
    """Create Visitor + FaceData records. Returns (stored, skipped)."""
    from models import models as db_models
    from services.visitor_service import create_face_data

    stored = 0
    skipped = 0

    if dry_run:
        logger.info("  [DRY RUN] Would create visitor: %s (%d images)", name, len(images))
        return len(images), 0

    # Create or reuse visitor
    visitor = (
        db.query(db_models.Visitor)
        .filter(
            db_models.Visitor.organization_id == org_id,
            db_models.Visitor.name == name,
        )
        .first()
    )
    if visitor is None:
        visitor = db_models.Visitor(
            organization_id=org_id,
            name=name,
            visitor_type="employee",
        )
        db.add(visitor)
        db.commit()
        db.refresh(visitor)

    for idx, img_path in enumerate(images):
        embedding = extract_embedding(str(img_path), model_name)
        if embedding is None:
            skipped += 1
            continue

        # Determine face angle from path hint
        path_str = str(img_path).lower()
        if "frontal" in path_str or "front" in path_str:
            angle = "frontal"
        elif "profile" in path_str:
            angle = "profile"
        elif "45" in path_str:
            angle = "45_left"
        else:
            angle = "frontal"

        try:
            create_face_data(
                db,
                visitor_id=visitor.id,
                embedding=embedding,
                image_url=None,
                quality_score=0.8,
                face_angle=angle,
                is_primary=(idx == 0),
            )
            stored += 1
        except Exception as exc:
            logger.warning("  FaceData insert failed for %s / %s: %s", name, img_path.name, exc)
            skipped += 1

    return stored, skipped


# -- Auto-detect dataset type from filename ------------------------------------

def _detect_dataset_type(zip_path: Path) -> Optional[str]:
    name = zip_path.stem.lower()
    if "lfw" in name:
        return "lfw"
    if "cfp" in name:
        return "cfp"
    if "multipose" in name or "multi_pose" in name or "multi-pose" in name:
        return "multipose"
    return None


# -- Single zip ingestion ------------------------------------------------------

def ingest_zip(
    zip_path: Path,
    dataset_type: str,
    org_id: uuid.UUID,
    max_people: int,
    max_per_person: int,
    model_name: str,
    dry_run: bool,
    db=None,
) -> dict:
    """Extract one zip, discover identities, ingest into DB. Returns summary dict."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="sentinelcv_ingest_"))
    logger.info("-- %s (%s) ------------------", zip_path.name, dataset_type.upper())
    logger.info("Extracting -> %s", tmp_dir)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)
    except Exception as exc:
        logger.error("Extraction failed: %s", exc)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"zip": zip_path.name, "error": str(exc), "stored": 0, "skipped": 0, "people": 0}

    # Unwrap single top-level folder
    dataset_root = tmp_dir
    children = [c for c in tmp_dir.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        dataset_root = children[0]

    logger.info("Dataset root: %s", dataset_root)

    parser_fn = DATASET_PARSERS[dataset_type]
    people = parser_fn(dataset_root, max_people, max_per_person)
    total_images = sum(len(imgs) for _, imgs in people)
    logger.info("Discovered %d identities, %d total images", len(people), total_images)

    if dry_run:
        logger.info("[DRY RUN] Sample identities:")
        for name, imgs in people[:5]:
            logger.info("  %-40s %d images", name, len(imgs))
        if len(people) > 5:
            logger.info("  ... and %d more", len(people) - 5)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return {"zip": zip_path.name, "dataset": dataset_type, "people": len(people),
                "images": total_images, "stored": 0, "skipped": 0, "dry_run": True}

    total_stored = 0
    total_skipped = 0
    try:
        for i, (name, images) in enumerate(people):
            logger.info("[%d/%d] %-40s %d images", i + 1, len(people), name, len(images))
            stored, skipped = ingest_person(db, org_id, name, images, model_name, dry_run)
            total_stored += stored
            total_skipped += skipped
            if (i + 1) % 10 == 0:
                logger.info("  Progress: %d/%d people | %d embeddings stored", i + 1, len(people), total_stored)
    except KeyboardInterrupt:
        logger.warning("Interrupted after %d people.", total_stored)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return {
        "zip": zip_path.name,
        "dataset": dataset_type,
        "people": len(people),
        "stored": total_stored,
        "skipped": total_skipped,
    }


# -- Main ----------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest face dataset zip(s) into SentinelCV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single dataset
  python scripts/ingest_dataset.py --zip lfw.zip --dataset lfw --org-id <UUID>

  # All three datasets at once (auto-detects type from filename)
  python scripts/ingest_dataset.py --org-id <UUID> \\
      --zip lfw.zip --zip cfp-dataset.zip --zip multipose.zip

  # Override type for a specific zip
  python scripts/ingest_dataset.py --org-id <UUID> \\
      --zip archive.zip --dataset cfp
        """,
    )
    parser.add_argument(
        "--zip", action="append", dest="zips", metavar="PATH",
        required=True, help="Zip file path (repeat for multiple datasets)",
    )
    parser.add_argument(
        "--dataset", choices=["lfw", "cfp", "multipose"],
        help="Dataset type (auto-detected from filename if omitted)",
    )
    parser.add_argument("--org-id", required=True, help="Organization UUID")
    parser.add_argument("--max-people", type=int, default=100,
                        help="Max identities per dataset (default 100)")
    parser.add_argument("--max-per-person", type=int, default=10,
                        help="Max images per identity (default 10)")
    parser.add_argument("--model", default="ArcFace",
                        choices=["ArcFace", "Facenet512"],
                        help="DeepFace embedding model (default ArcFace)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover without writing to DB")
    args = parser.parse_args()

    try:
        org_id = uuid.UUID(args.org_id)
    except ValueError:
        logger.error("Invalid --org-id: %s", args.org_id)
        sys.exit(1)

    # Build list of (zip_path, dataset_type) pairs
    jobs = []
    for zip_str in args.zips:
        zip_path = Path(zip_str)
        if not zip_path.exists():
            logger.error("Zip not found: %s", zip_path)
            sys.exit(1)
        dtype = args.dataset or _detect_dataset_type(zip_path)
        if dtype is None:
            logger.error(
                "Cannot auto-detect dataset type for '%s'. "
                "Name it so it contains 'lfw', 'cfp', or 'multipose', "
                "or pass --dataset explicitly.", zip_path.name
            )
            sys.exit(1)
        jobs.append((zip_path, dtype))
        logger.info("Queued: %-40s -> %s", zip_path.name, dtype.upper())

    logger.info("")
    logger.info("Config: org=%s  max_people=%d  max_per_person=%d  model=%s  dry_run=%s",
                org_id, args.max_people, args.max_per_person, args.model, args.dry_run)
    logger.info("")

    db = None
    if not args.dry_run:
        from db.base import SessionLocal
        db = SessionLocal()

    summaries = []
    try:
        for zip_path, dtype in jobs:
            summary = ingest_zip(
                zip_path=zip_path,
                dataset_type=dtype,
                org_id=org_id,
                max_people=args.max_people,
                max_per_person=args.max_per_person,
                model_name=args.model,
                dry_run=args.dry_run,
                db=db,
            )
            summaries.append(summary)
            logger.info("")
    finally:
        if db is not None:
            db.close()

    # Final report
    logger.info("=" * 60)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 60)
    total_people = sum(s["people"] for s in summaries)
    total_stored = sum(s.get("stored", 0) for s in summaries)
    total_skipped = sum(s.get("skipped", 0) for s in summaries)
    for s in summaries:
        if s.get("error"):
            logger.info("  %-30s  ERROR: %s", s["zip"], s["error"])
        else:
            logger.info("  %-30s  people=%-5d stored=%-6d skipped=%d",
                        s["zip"], s["people"], s.get("stored", 0), s.get("skipped", 0))
    logger.info("-" * 60)
    logger.info("  TOTAL                          people=%-5d stored=%-6d skipped=%d",
                total_people, total_stored, total_skipped)
    logger.info("")
    if not args.dry_run:
        logger.info("Next steps:")
        logger.info("  1. POST /api/v1/training/dataset/validate")
        logger.info("  2. POST /api/v1/training/start")
        logger.info("  3. GET  /api/v1/training/jobs/{job_id}   ? poll until completed")
        logger.info("  4. POST /api/v1/training/jobs/{job_id}/activate")


if __name__ == "__main__":
    main()
