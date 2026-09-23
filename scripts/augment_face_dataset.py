#!/usr/bin/env python3
"""Apply advanced augmentation to a directory of face images."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_services.advanced_augmentation import AdvancedAugmentation, get_augmentation_config


_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _collect_images(input_dir: Path) -> List[Path]:
    return [
        path for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_EXTS
    ]


def _load_config(config_path: Optional[str]) -> Dict[str, object]:
    if not config_path:
        return get_augmentation_config()
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_image(output_path: Path, image) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), image)


def _resolve_pair(images: List[Path], current: Path) -> Path:
    if len(images) < 2:
        return current
    candidates = [item for item in images if item != current]
    return random.choice(candidates) if candidates else current


def main() -> int:
    parser = argparse.ArgumentParser(description="Augment face image dataset")
    parser.add_argument("--input-dir", default="data/face_images", help="Directory with source images")
    parser.add_argument("--output-dir", default="data/face_images_augmented", help="Output directory")
    parser.add_argument("--max-images", type=int, default=0, help="Limit number of source images (0 = all)")
    parser.add_argument("--copies", type=int, default=1, help="Augmented copies per source image")
    parser.add_argument("--augmentations", default="rotate,flip,scale,jitter,erase", help="Comma-separated augmentations")
    parser.add_argument("--include-mixup", action="store_true", help="Include MixUp variants")
    parser.add_argument("--include-cutmix", action="store_true", help="Include CutMix variants")
    parser.add_argument("--config", default="", help="Optional JSON config for augmentation")
    parser.add_argument("--seed", type=int, default=0, help="Random seed (0 = random)")
    args = parser.parse_args()

    if args.seed:
        random.seed(args.seed)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    images = _collect_images(input_dir)
    if not images:
        print("No images found to augment.")
        return 0

    if args.max_images > 0:
        images = images[: args.max_images]

    config = _load_config(args.config)
    augmenter = AdvancedAugmentation(config=config)
    augmentations = [item.strip() for item in args.augmentations.split(",") if item.strip()]

    manifest: List[Dict[str, object]] = []
    for image_path in images:
        image = cv2.imread(str(image_path))
        if image is None:
            continue

        entry: Dict[str, object] = {
            "source": str(image_path),
            "augmented": [],
        }

        for copy_index in range(args.copies):
            augmented = augmenter.apply_augmentation_pipeline(image, augmentations)
            output_name = f"{image_path.stem}_aug{copy_index + 1}{image_path.suffix}"
            output_path = output_dir / output_name
            _save_image(output_path, augmented)
            entry["augmented"].append(str(output_path))

        if args.include_mixup:
            pair_path = _resolve_pair(images, image_path)
            pair_image = cv2.imread(str(pair_path))
            if pair_image is not None:
                mixed, lam = augmenter.mixup(image, pair_image)
                output_name = f"{image_path.stem}_mixup{image_path.suffix}"
                output_path = output_dir / output_name
                _save_image(output_path, mixed)
                entry["augmented"].append(str(output_path))
                entry["mixup_lambda"] = float(lam)

        if args.include_cutmix:
            pair_path = _resolve_pair(images, image_path)
            pair_image = cv2.imread(str(pair_path))
            if pair_image is not None:
                cutmixed = augmenter.cutmix(image, pair_image)
                output_name = f"{image_path.stem}_cutmix{image_path.suffix}"
                output_path = output_dir / output_name
                _save_image(output_path, cutmixed)
                entry["augmented"].append(str(output_path))

        manifest.append(entry)

    manifest_path = output_dir / "augmentation_manifest.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"items": manifest}, indent=2), encoding="utf-8")

    print(f"Augmented {len(manifest)} images. Manifest saved to {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
