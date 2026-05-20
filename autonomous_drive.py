from __future__ import annotations

import os
import queue
import select
import sys
import termios
import threading
import time
import tty
from pathlib import Path

import cv2
import mycamera
import numpy as np
import torch
from gpiozero import DigitalOutputDevice, PWMOutputDevice
from torch import nn


# =========================
# 紐⑤뜽 ?ㅼ젙
# =========================
MODEL_PATH = "/home/admin/AI_CAR/best_model_train7_retrain.pt"
DEVICE = "cpu"


# =========================
# 紐⑦꽣 ? ?ㅼ젙
# =========================
PWMA = PWMOutputDevice(18)
AIN1 = DigitalOutputDevice(22)
AIN2 = DigitalOutputDevice(27)

PWMB = PWMOutputDevice(23)
BIN1 = DigitalOutputDevice(25)
BIN2 = DigitalOutputDevice(24)


# =========================
# 二쇳뻾 ?ㅼ젙
# =========================
speedSet = 0.85
START_THROTTLE = 1.0
DEADZONE = 0.08
TURN_GAIN = 0.9
DRIVE_THRESHOLD = 0.15

SHOW_WINDOW = True
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240

# True: 而⑦듃濡ㅻ윭 ?몃━嫄곕뒗 ?띾룄留??대떦, 議고뼢? 紐⑤뜽???대떦
# False: 湲곗〈泥섎읆 而⑦듃濡ㅻ윭 議고뼢 ?ъ슜
AUTO_STEERING = True

# AI 議고뼢媛믪쓣 遺?쒕읇寃??욌뒗 ?뺣룄. 0?대㈃ 利됱떆 諛섏쁺, ?댁닔濡?遺?쒕윭?.
STEERING_SMOOTHING = 0.35

save_queue = queue.Queue(maxsize=10)


# =========================
# 怨듭쑀 ?곹깭
# =========================
running = True

state_lock = threading.Lock()
current_throttle = 0.0
current_steering = 0.0
button_stop_pressed = False


# =========================
# ?숈뒿 紐⑤뜽 援ъ“
# =========================
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


def load_model(model_path: str) -> SteeringCNN:
    device = torch.device(DEVICE)
    checkpoint = torch.load(model_path, map_location=device)

    model = SteeringCNN().to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()
    return model


def preprocess_for_model(image: np.ndarray) -> torch.Tensor:
    """
    ?숈뒿 ?곗씠?????肄붾뱶? 媛숈? ?꾩쿂由?
    flip???먮낯 -> ?꾨옒 ?덈컲 crop -> BGR2YUV -> blur -> resize(200,66).

    ?숈뒿 ?뚮뒗 ??諛곗뿴??cv2.imwrite濡???ν뻽怨? PIL濡??ㅼ떆 ?쎌뼱 RGB ?먯꽌?뷀뻽?듬땲??
    ?곕씪???ㅼ떆媛?異붾줎?먯꽌??留덉?留됱뿉 BGR2RGB瑜??곸슜????λ낯???쎌? 寃껉낵 媛숈? 梨꾨꼸 ?쒖꽌濡?留욎땅?덈떎.
    """
    height, _, _ = image.shape
    image = image[int(height / 2) :, :, :]
    image = cv2.cvtColor(image, cv2.COLOR_BGR2YUV)
    image = cv2.GaussianBlur(image, (3, 3), 0)
    image = cv2.resize(image, (200, 66), interpolation=cv2.INTER_AREA)
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    tensor = torch.from_numpy(image).float() / 255.0
    tensor = tensor.permute(2, 0, 1)

    mean = torch.tensor([0.418, 0.485, 0.390]).view(3, 1, 1)
    std = torch.tensor([0.230, 0.230, 0.230]).view(3, 1, 1)
    tensor = (tensor - mean) / std
    return tensor.unsqueeze(0)


@torch.inference_mode()
def predict_steering(model: SteeringCNN, image: np.ndarray) -> tuple[float, float]:
    x = preprocess_for_model(image).to(torch.device(DEVICE))
    steering = float(model(x).item())
    steering = clamp(steering, -1.0, 1.0)
    angle = clamp(90.0 + steering * 45.0, 45.0, 135.0)
    return steering, angle


# =========================
# 湲곕낯 ?⑥닔
# =========================
def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def apply_deadzone(value, deadzone=DEADZONE):
    if abs(value) < deadzone:
        return 0.0
    return value


# =========================
# 紐⑦꽣 ?쒖뼱 ?⑥닔
# =========================
def set_left_motor(speed):
    speed = clamp(speed, -1.0, 1.0)

    if speed > 0:
        AIN1.value = 0
        AIN2.value = 1
        PWMA.value = speed
    elif speed < 0:
        AIN1.value = 1
        AIN2.value = 0
        PWMA.value = -speed
    else:
        PWMA.value = 0.0


def set_right_motor(speed):
    speed = clamp(speed, -1.0, 1.0)

    if speed > 0:
        BIN1.value = 0
        BIN2.value = 1
        PWMB.value = speed
    elif speed < 0:
        BIN1.value = 1
        BIN2.value = 0
        PWMB.value = -speed
    else:
        PWMB.value = 0.0


def motor_stop():
    PWMA.value = 0.0
    PWMB.value = 0.0


def arcade_drive(throttle, steering):
    throttle = apply_deadzone(throttle)
    steering = apply_deadzone(steering)

    left_speed = throttle * (1.0 + steering * TURN_GAIN)
    right_speed = throttle * (1.0 - steering * TURN_GAIN)

    left_speed = clamp(left_speed, -1.0, 1.0)
    right_speed = clamp(right_speed, -1.0, 1.0)

    set_left_motor(speedSet * left_speed)
    set_right_motor(speedSet * right_speed)


# =========================
# Keyboard input thread
# =========================
def keyboard_input_thread():
    global button_stop_pressed
    global current_steering
    global current_throttle
    global running

    print("Keyboard control")
    print("UP: start / DOWN: stop / q: quit")

    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setcbreak(fd)

        while running:
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not r:
                continue

            ch = sys.stdin.read(1)

            if ch == "q":
                print("quit")
                running = False
                break

            if ch != "\x1b":
                continue

            seq = ch + sys.stdin.read(2)
            if seq == "\x1b[A":
                with state_lock:
                    current_throttle = START_THROTTLE
                    current_steering = 0.0
                    button_stop_pressed = False
                print("start")
            elif seq == "\x1b[B":
                with state_lock:
                    current_throttle = 0.0
                    current_steering = 0.0
                    button_stop_pressed = True
                motor_stop()
                print("stop")

    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        motor_stop()


# =========================
# 硫붿씤 肄붾뱶
# =========================
def main():
    global running

    if not Path(MODEL_PATH).exists():
        print("紐⑤뜽 ?뚯씪??李얠? 紐삵뻽?듬땲??", MODEL_PATH)
        motor_stop()
        return

    model = load_model(MODEL_PATH)
    print("紐⑤뜽 濡쒕뱶 ?꾨즺:", MODEL_PATH)

    input_thread = threading.Thread(
        target=keyboard_input_thread,
        daemon=True,
    )
    input_thread.start()

    camera = mycamera.MyPiCamera(CAMERA_WIDTH, CAMERA_HEIGHT)
    smoothed_ai_steering = 0.0
    last_print = 0.0

    print("移대찓???쒖옉")
    print("AI 議고뼢:", "ON" if AUTO_STEERING else "OFF")
    print("Speed control: UP=start, DOWN=stop")

    try:
        while running and camera.isOpened():
            ret, image = camera.read()

            if not ret:
                motor_stop()
                continue

            image = cv2.flip(image, -1)

            with state_lock:
                throttle = current_throttle
                manual_steering = current_steering
                stopped = button_stop_pressed

            if stopped or abs(throttle) <= DRIVE_THRESHOLD:
                motor_stop()
                continue

            ai_steering, ai_angle = predict_steering(model, image)
            smoothed_ai_steering = (
                STEERING_SMOOTHING * smoothed_ai_steering
                + (1.0 - STEERING_SMOOTHING) * ai_steering
            )

            steering = smoothed_ai_steering if AUTO_STEERING else manual_steering
            arcade_drive(throttle, steering)

            now = time.time()
            if now - last_print > 0.5:
                print(
                    "throttle=%.2f ai_angle=%.1f ai_steering=%.2f drive_steering=%.2f"
                    % (throttle, ai_angle, ai_steering, steering)
                )
                last_print = now

            if SHOW_WINDOW:
                preview = image.copy()
                cv2.putText(
                    preview,
                    "angle %.1f steering %.2f" % (ai_angle, steering),
                    (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )
                cv2.imshow("AI Drive", preview)
                key = cv2.waitKey(1)
                if key == ord("q"):
                    running = False
                    break

    except KeyboardInterrupt:
        print("Ctrl+C 醫낅즺")
        running = False

    finally:
        running = False
        motor_stop()
        cv2.destroyAllWindows()
        print("?꾨줈洹몃옩 醫낅즺")


if __name__ == "__main__":
    main()
