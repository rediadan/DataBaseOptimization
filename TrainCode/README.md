# Steering Training Code

This code is tuned for `C:\Users\User\Desktop\video\train1`.

Dataset summary from the current folder:

- Images: 485 PNG files
- Size: 200x66 for every image
- Labels: filename suffix, continuous 45 to 135
- Normalization: `(label - 90) / 45`, so 45=-1, 90=0, 135=1
- Important imbalance: labels 45, 90, 134, and 135 appear much more often than most middle values

Recommended setup:

```powershell
cd C:\Users\User\Desktop\video\TrainCode
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Analyze again:

```powershell
python analyze_dataset.py --data-dir C:\Users\User\Desktop\video\train1 --out dataset_summary.json
```

Train:

```powershell
python train.py --data-dir C:\Users\User\Desktop\video\train1 --epochs 60 --batch-size 32
```

The best checkpoint is saved to:

```text
C:\Users\User\Desktop\video\TrainCode\runs\best_model.pt
```

Predict one image:

```powershell
python predict.py --image C:\Users\User\Desktop\video\train1\train_00000_090.png
```

Notes:

- The task is regression, not classification, because labels are continuous from 45 to 135.
- The model outputs one normalized steering value and converts it back to 45..135 degrees.
- `WeightedRandomSampler` is enabled by default to reduce bias from the imbalanced label distribution.
- Validation uses the last 20 percent of frames by default. Use `--val-mode random` only when you want a quick sanity check.
