from __future__ import annotations

import os
import queue
import select
import threading
import time
from pathlib import Path

import cv2
import mycamera
import numpy as np
import torch
from evdev import InputDevice, ecodes, list_devices
from gpiozero import DigitalOutputDevice, PWMOutputDevice
from torch import nn


# =========================
# 모델 설정
# =========================
MODEL_PATH = "/home/admin/AI_CAR/best_model.pt"
DEVICE = "cpu"

# train7은 0~180 라벨로 학습되었습니다. 체크포인트 안에 이 값들이
# 저장되어 있으면 그 값을 우선 사용하고, 없으면 아래 기본값을 씁니다.
DEFAULT_LABEL_MIN = 0.0
DEFAULT_LABEL_MAX = 180.0


# =========================
# 모터 핀 설정
# =========================
PWMA = PWMOutputDevice(18)
AIN1 = DigitalOutputDevice(22)
AIN2 = DigitalOutputDevice(27)

PWMB = PWMOutputDevice(23)
BIN1 = DigitalOutputDevice(25)
BIN2 = DigitalOutputDevice(24)


# =========================
# 주행 설정
# =========================
speedSet = 0.45
DEADZONE = 0.08
TURN_GAIN = 0.7
DRIVE_THRESHOLD = 0.15

SHOW_WINDOW = False
CAMERA_WIDTH = 320
CAMERA_HEIGHT = 240

# True: 컨트롤러 트리거는 속도만 담당, 조향은 모델이 담당
# False: 기존처럼 컨트롤러 조향 사용
AUTO_STEERING = True

# AI 조향값을 부드럽게 섞는 정도. 0이면 즉시 반영, 클수록 부드러움.
STEERING_SMOOTHING = 0.35

save_queue = queue.Queue(maxsize=10)


# =========================
# 공유 상태
# =========================
running = True

state_lock = threading.Lock()
current_throttle = 0.0
current_steering = 0.0
button_stop_pressed = False


# =========================
# 학습 모델 구조
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


def load_model(model_path: str) -> tuple[SteeringCNN, float, float, float, float]:
    device = torch.device(DEVICE)
    checkpoint = torch.load(model_path, map_location=device)

    model = SteeringCNN().to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    label_min = float(checkpoint.get("label_min", DEFAULT_LABEL_MIN))
    label_max = float(checkpoint.get("label_max", DEFAULT_LABEL_MAX))
    label_center = float(checkpoint.get("label_center", (label_min + label_max) / 2.0))
    label_radius = float(checkpoint.get("label_radius", (label_max - label_min) / 2.0))
    return model, label_center, label_radius, label_min, label_max


def preprocess_for_model(image: np.ndarray) -> torch.Tensor:
    """
    학습 데이터 저장 코드와 같은 전처리:
    flip된 원본 -> 아래 절반 crop -> BGR2YUV -> blur -> resize(200,66).

    학습 때는 이 배열을 cv2.imwrite로 저장했고, PIL로 다시 읽어 RGB 텐서화했습니다.
    따라서 실시간 추론에서도 마지막에 BGR2RGB를 적용해 저장본을 읽은 것과 같은 채널 순서로 맞춥니다.
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
def predict_steering(
    model: SteeringCNN,
    image: np.ndarray,
    label_center: float,
    label_radius: float,
    label_min: float,
    label_max: float,
) -> tuple[float, float]:
    x = preprocess_for_model(image).to(torch.device(DEVICE))
    steering = float(model(x).item())
    steering = clamp(steering, -1.0, 1.0)
    angle = clamp(label_center + steering * label_radius, label_min, label_max)
    return steering, angle


# =========================
# 기본 함수
# =========================
def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def apply_deadzone(value, deadzone=DEADZONE):
    if abs(value) < deadzone:
        return 0.0
    return value


# =========================
# 모터 제어 함수
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
# 컨트롤러 찾기
# =========================
def find_xbox_controller():
    devices = [InputDevice(path) for path in list_devices()]

    print("입력 장치 목록:")
    for dev in devices:
        print(dev.path, dev.name)

    for dev in devices:
        name = dev.name.lower()
        if "xbox" in name or "controller" in name or "gamepad" in name:
            print("컨트롤러 선택:", dev.path, dev.name)
            return dev

    print("Xbox 컨트롤러를 찾지 못했습니다.")
    return None


def get_abs_range(device, code):
    info = device.absinfo(code)
    return info.min, info.max


def normalize_stick(value, min_value, max_value):
    center = (min_value + max_value) / 2.0
    half = (max_value - min_value) / 2.0

    if half == 0:
        return 0.0

    result = (value - center) / half
    return clamp(result, -1.0, 1.0)


def normalize_trigger(value, min_value, max_value):
    if max_value == min_value:
        return 0.0

    result = (value - min_value) / (max_value - min_value)
    return clamp(result, 0.0, 1.0)


# =========================
# 컨트롤러 입력 스레드
# =========================
def controller_input_thread(controller):
    global button_stop_pressed
    global current_steering
    global current_throttle
    global running

    AXIS_STEER = ecodes.ABS_X
    AXIS_GAS = ecodes.ABS_GAS
    AXIS_BRAKE = ecodes.ABS_BRAKE

    BUTTON_STOP = ecodes.BTN_SOUTH
    BUTTON_EXIT = ecodes.BTN_START

    steer_min, steer_max = get_abs_range(controller, AXIS_STEER)
    gas_min, gas_max = get_abs_range(controller, AXIS_GAS)
    brake_min, brake_max = get_abs_range(controller, AXIS_BRAKE)

    print("STEER range:", steer_min, steer_max)
    print("GAS range:", gas_min, gas_max)
    print("BRAKE range:", brake_min, brake_max)

    steer_raw = int((steer_min + steer_max) / 2)
    gas_raw = gas_min
    brake_raw = brake_min

    print("조작 시작")
    print("ABS_GAS: 전진 속도 / ABS_BRAKE: 후진 / ABS_X: 수동 조향 / A: 정지 / START: 종료")

    while running:
        r, _, _ = select.select([controller.fd], [], [], 0.001)

        if r:
            for event in controller.read():
                if event.type == ecodes.EV_ABS:
                    if event.code == AXIS_STEER:
                        steer_raw = event.value
                    elif event.code == AXIS_GAS:
                        gas_raw = event.value
                    elif event.code == AXIS_BRAKE:
                        brake_raw = event.value

                elif event.type == ecodes.EV_KEY:
                    if event.code == BUTTON_STOP:
                        button_stop_pressed = event.value == 1
                    elif event.code == BUTTON_EXIT and event.value == 1:
                        print("START 버튼 종료")
                        running = False
                        break

        steering = normalize_stick(steer_raw, steer_min, steer_max)
        steering = apply_deadzone(steering)

        gas = normalize_trigger(gas_raw, gas_min, gas_max)
        brake = normalize_trigger(brake_raw, brake_min, brake_max)
        throttle = apply_deadzone(gas - brake)

        with state_lock:
            current_throttle = throttle
            current_steering = steering

        time.sleep(0.002)

    motor_stop()


# =========================
# 메인 코드
# =========================
def main():
    global running

    if not Path(MODEL_PATH).exists():
        print("모델 파일을 찾지 못했습니다:", MODEL_PATH)
        motor_stop()
        return

    model, label_center, label_radius, label_min, label_max = load_model(MODEL_PATH)
    print("모델 로드 완료:", MODEL_PATH)
    print(
        "라벨 범위: %.0f~%.0f / center=%.1f radius=%.1f"
        % (label_min, label_max, label_center, label_radius)
    )

    controller = find_xbox_controller()
    if controller is None:
        motor_stop()
        return

    controller_thread = threading.Thread(
        target=controller_input_thread,
        args=(controller,),
        daemon=True,
    )
    controller_thread.start()

    camera = mycamera.MyPiCamera(CAMERA_WIDTH, CAMERA_HEIGHT)
    smoothed_ai_steering = 0.0
    last_print = 0.0

    print("카메라 시작")
    print("AI 조향:", "ON" if AUTO_STEERING else "OFF")

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

            ai_steering, ai_angle = predict_steering(
                model, image, label_center, label_radius, label_min, label_max
            )
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
        print("Ctrl+C 종료")
        running = False

    finally:
        running = False
        motor_stop()
        cv2.destroyAllWindows()
        print("프로그램 종료")


if __name__ == "__main__":
    main()
