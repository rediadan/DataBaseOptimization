from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageStat


def parse_label(path: Path) -> int:
    return int(path.stem[-3:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=r"C:\Users\User\Desktop\video\train1")
    parser.add_argument("--out", default="dataset_summary.json")
    args = parser.parse_args()

    paths = sorted(Path(args.data_dir).glob("*.png"))
    if not paths:
        raise FileNotFoundError(f"No PNG files found in {args.data_dir}")

    labels: list[int] = []
    sizes: Counter[str] = Counter()
    rgb_means: list[list[float]] = []
    bottom_rgb_means: list[list[float]] = []

    for path in paths:
        label = parse_label(path)
        labels.append(label)

        image = Image.open(path).convert("RGB")
        sizes[f"{image.width}x{image.height}"] += 1
        rgb_means.append(ImageStat.Stat(image).mean)

        crop_top = int(image.height * 0.35)
        bottom = image.crop((0, crop_top, image.width, image.height))
        bottom_rgb_means.append(ImageStat.Stat(bottom).mean)

    label_counts = Counter(labels)
    summary = {
        "count": len(paths),
        "sizes": dict(sizes),
        "label_min": min(labels),
        "label_max": max(labels),
        "label_unique": len(label_counts),
        "label_mean": float(np.mean(labels)),
        "label_std": float(np.std(labels)),
        "label_counts": {str(k): label_counts[k] for k in sorted(label_counts)},
        "rgb_mean": np.mean(np.asarray(rgb_means), axis=0).round(3).tolist(),
        "bottom_rgb_mean": np.mean(np.asarray(bottom_rgb_means), axis=0).round(3).tolist(),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
