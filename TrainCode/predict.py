from __future__ import annotations

import argparse
from pathlib import Path

import torch
from PIL import Image
from torchvision import transforms as T

from train import SteeringCNN, denormalize_label


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=r"C:\Users\User\Desktop\video\TrainCode\runs\best_model.pt")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(args.model, map_location=device)

    model = SteeringCNN().to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    transform = T.Compose(
        [
            T.ToTensor(),
            T.Normalize(mean=(0.418, 0.485, 0.390), std=(0.230, 0.230, 0.230)),
        ]
    )

    image = Image.open(Path(args.image)).convert("RGB")
    x = transform(image).unsqueeze(0).to(device)

    with torch.no_grad():
        normalized = model(x)
        degrees = denormalize_label(normalized).item()

    print(f"{degrees:.2f}")


if __name__ == "__main__":
    main()
