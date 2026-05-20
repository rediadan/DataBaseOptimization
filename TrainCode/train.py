from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset, Subset, WeightedRandomSampler
from torchvision import transforms as T

try:
    from tqdm import tqdm
except ImportError:
    class _PlainProgress:
        def __init__(self, iterable, **_: object) -> None:
            self.iterable = iterable

        def __iter__(self):
            return iter(self.iterable)

        def set_postfix(self, **_: object) -> None:
            return None

    def tqdm(iterable, **kwargs: object):
        return _PlainProgress(iterable, **kwargs)


DEFAULT_LABEL_MIN = 45.0
DEFAULT_LABEL_MAX = 135.0


@dataclass
class TrainConfig:
    data_dirs: list[str]
    out_dir: str
    epochs: int
    batch_size: int
    lr: float
    weight_decay: float
    seed: int
    val_ratio: float
    val_mode: str
    use_weighted_sampler: bool
    num_workers: int
    label_min: float | None
    label_max: float | None


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def parse_label(path: Path) -> int:
    label = int(path.stem[-3:])
    return label


def label_center_radius(label_min: float, label_max: float) -> tuple[float, float]:
    center = (label_min + label_max) / 2.0
    radius = (label_max - label_min) / 2.0
    if radius <= 0:
        raise ValueError(f"Invalid label range: {label_min}..{label_max}")
    return center, radius


def normalize_label(label: int | float, center: float, radius: float) -> float:
    return (float(label) - center) / radius


def denormalize_label(
    value: torch.Tensor,
    center: float = 90.0,
    radius: float = 45.0,
    label_min: float = DEFAULT_LABEL_MIN,
    label_max: float = DEFAULT_LABEL_MAX,
) -> torch.Tensor:
    return torch.clamp(value * radius + center, label_min, label_max)


class RandomHorizontalFlipWithLabel:
    def __init__(self, p: float = 0.5) -> None:
        self.p = p

    def __call__(self, image: Image.Image, label: float) -> tuple[Image.Image, float]:
        if random.random() < self.p:
            return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT), -label
        return image, label


class DrivingDataset(Dataset):
    def __init__(
        self,
        data_dirs: str | Path | list[str] | list[Path],
        train: bool,
        label_center: float = 90.0,
        label_radius: float = 45.0,
    ) -> None:
        if isinstance(data_dirs, (str, Path)):
            roots = [Path(data_dirs)]
        else:
            roots = [Path(root) for root in data_dirs]

        self.paths: list[Path] = []
        for root in roots:
            self.paths.extend(sorted(root.glob("*.png")))
        self.paths = sorted(self.paths)
        if not self.paths:
            raise FileNotFoundError(f"No PNG files found in {roots}")

        self.train = train
        self.label_center = label_center
        self.label_radius = label_radius
        self.flip = RandomHorizontalFlipWithLabel(p=0.5)
        self.image_transform = T.Compose(
            [
                T.ColorJitter(brightness=0.25, contrast=0.2, saturation=0.15)
                if train
                else T.Lambda(lambda x: x),
                T.ToTensor(),
                T.Normalize(mean=(0.418, 0.485, 0.390), std=(0.230, 0.230, 0.230)),
            ]
        )

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        path = self.paths[index]
        image = Image.open(path).convert("RGB")
        label = normalize_label(parse_label(path), self.label_center, self.label_radius)

        if self.train:
            image, label = self.flip(image, label)

        image_tensor = self.image_transform(image)
        label_tensor = torch.tensor([label], dtype=torch.float32)
        return image_tensor, label_tensor


class SteeringCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 24, kernel_size=5, stride=2),
            nn.BatchNorm2d(24),
            nn.ELU(inplace=True),
            nn.Conv2d(24, 36, kernel_size=5, stride=2),
            nn.BatchNorm2d(36),
            nn.ELU(inplace=True),
            nn.Conv2d(36, 48, kernel_size=5, stride=2),
            nn.BatchNorm2d(48),
            nn.ELU(inplace=True),
            nn.Conv2d(48, 64, kernel_size=3),
            nn.BatchNorm2d(64),
            nn.ELU(inplace=True),
            nn.Conv2d(64, 64, kernel_size=3),
            nn.BatchNorm2d(64),
            nn.ELU(inplace=True),
        )
        self.regressor = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64 * 1 * 18, 100),
            nn.ELU(inplace=True),
            nn.Dropout(p=0.2),
            nn.Linear(100, 50),
            nn.ELU(inplace=True),
            nn.Linear(50, 10),
            nn.ELU(inplace=True),
            nn.Linear(10, 1),
            nn.Tanh(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.regressor(self.features(x))


def split_indices(n: int, val_ratio: float, mode: str, seed: int) -> tuple[list[int], list[int]]:
    indices = list(range(n))
    val_count = max(1, int(round(n * val_ratio)))

    if mode == "tail":
        return indices[:-val_count], indices[-val_count:]

    rng = random.Random(seed)
    rng.shuffle(indices)
    return indices[val_count:], indices[:val_count]


def make_weighted_sampler(dataset: DrivingDataset, indices: list[int]) -> WeightedRandomSampler:
    labels = [parse_label(dataset.paths[i]) for i in indices]
    bin_width = max(1.0, dataset.label_radius / 9.0)
    label_min = dataset.label_center - dataset.label_radius
    bins = [int(math.floor((label - label_min) / bin_width)) for label in labels]
    counts = Counter(bins)
    weights = [1.0 / counts[bin_id] for bin_id in bins]
    return WeightedRandomSampler(weights=weights, num_samples=len(weights), replacement=True)


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
    label_center: float,
    label_radius: float,
    label_min: float,
    label_max: float,
) -> dict[str, float]:
    model.eval()
    criterion = nn.SmoothL1Loss(reduction="sum")
    total_loss = 0.0
    total_abs_deg = 0.0
    total = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        preds = model(images)

        total_loss += criterion(preds, labels).item()
        pred_deg = denormalize_label(preds, label_center, label_radius, label_min, label_max)
        label_deg = denormalize_label(labels, label_center, label_radius, label_min, label_max)
        total_abs_deg += torch.abs(pred_deg - label_deg).sum().item()
        total += images.size(0)

    return {
        "loss": total_loss / max(total, 1),
        "mae_deg": total_abs_deg / max(total, 1),
    }


def train(config: TrainConfig) -> None:
    seed_everything(config.seed)
    out_dir = Path(config.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_paths = []
    for data_dir in config.data_dirs:
        raw_paths.extend(sorted(Path(data_dir).glob("*.png")))
    if not raw_paths:
        raise FileNotFoundError(f"No PNG files found in {config.data_dirs}")

    raw_labels = [parse_label(path) for path in raw_paths]
    label_min = float(min(raw_labels) if config.label_min is None else config.label_min)
    label_max = float(max(raw_labels) if config.label_max is None else config.label_max)
    label_center, label_radius = label_center_radius(label_min, label_max)
    print(
        f"label_range={label_min:.0f}..{label_max:.0f} "
        f"center={label_center:.1f} radius={label_radius:.1f}"
    )

    full_train = DrivingDataset(config.data_dirs, train=True, label_center=label_center, label_radius=label_radius)
    full_val = DrivingDataset(config.data_dirs, train=False, label_center=label_center, label_radius=label_radius)
    train_indices, val_indices = split_indices(
        len(full_train), config.val_ratio, config.val_mode, config.seed
    )

    train_subset = Subset(full_train, train_indices)
    val_subset = Subset(full_val, val_indices)

    sampler = (
        make_weighted_sampler(full_train, train_indices)
        if config.use_weighted_sampler
        else None
    )
    train_loader = DataLoader(
        train_subset,
        batch_size=config.batch_size,
        shuffle=sampler is None,
        sampler=sampler,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
    )
    val_loader = DataLoader(
        val_subset,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=config.num_workers,
        pin_memory=torch.cuda.is_available(),
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = SteeringCNN().to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.lr, weight_decay=config.weight_decay
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=config.epochs)
    criterion = nn.SmoothL1Loss()

    best_mae = float("inf")
    history: list[dict[str, float]] = []

    for epoch in range(1, config.epochs + 1):
        model.train()
        running_loss = 0.0
        seen = 0

        progress = tqdm(train_loader, desc=f"epoch {epoch}/{config.epochs}", leave=False)
        for images, labels in progress:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad(set_to_none=True)
            preds = model(images)
            loss = criterion(preds, labels)
            loss.backward()
            optimizer.step()

            batch = images.size(0)
            running_loss += loss.item() * batch
            seen += batch
            progress.set_postfix(loss=running_loss / max(seen, 1))

        scheduler.step()
        val_metrics = evaluate(
            model, val_loader, device, label_center, label_radius, label_min, label_max
        )
        train_loss = running_loss / max(seen, 1)
        row = {
            "epoch": epoch,
            "train_loss": train_loss,
            "val_loss": val_metrics["loss"],
            "val_mae_deg": val_metrics["mae_deg"],
            "lr": scheduler.get_last_lr()[0],
        }
        history.append(row)
        print(
            f"epoch={epoch:03d} train_loss={train_loss:.5f} "
            f"val_loss={row['val_loss']:.5f} val_mae_deg={row['val_mae_deg']:.2f}"
        )

        if row["val_mae_deg"] < best_mae:
            best_mae = row["val_mae_deg"]
            torch.save(
                {
                    "model_state": model.state_dict(),
                    "config": asdict(config),
                    "label_min": label_min,
                    "label_max": label_max,
                    "label_center": label_center,
                    "label_radius": label_radius,
                    "input_size": [200, 66],
                    "val_mae_deg": best_mae,
                },
                out_dir / "best_model.pt",
            )

    (out_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    print(f"best validation MAE: {best_mae:.2f} degrees")
    print(f"saved: {out_dir / 'best_model.pt'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir",
        default=r"C:\Users\User\Desktop\video\train1",
        help="Single dataset folder. Kept for compatibility.",
    )
    parser.add_argument(
        "--data-dirs",
        nargs="+",
        default=None,
        help="One or more dataset folders. Example: --data-dirs train1 train2 train3 train4",
    )
    parser.add_argument("--out-dir", default=r"C:\Users\User\Desktop\video\TrainCode\runs")
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--val-mode", choices=["tail", "random"], default="tail")
    parser.add_argument("--no-weighted-sampler", action="store_true")
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--label-min", type=float, default=None)
    parser.add_argument("--label-max", type=float, default=None)
    args = parser.parse_args()

    data_dirs = args.data_dirs if args.data_dirs is not None else [args.data_dir]

    config = TrainConfig(
        data_dirs=data_dirs,
        out_dir=args.out_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        weight_decay=args.weight_decay,
        seed=args.seed,
        val_ratio=args.val_ratio,
        val_mode=args.val_mode,
        use_weighted_sampler=not args.no_weighted_sampler,
        num_workers=args.num_workers,
        label_min=args.label_min,
        label_max=args.label_max,
    )
    train(config)


if __name__ == "__main__":
    main()
