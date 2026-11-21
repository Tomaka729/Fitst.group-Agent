"""图片预处理：压缩、模糊检测、CLAHE 增强与内容哈希去重。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import cv2
import numpy as np

MAX_SIDE = 1600
JPEG_QUALITY = 85
BLUR_THRESHOLD = 60.0  # Laplacian 方差阈值，低于此值视为过糊


@dataclass
class PreparedImage:
    ok: bool
    message: str
    data: bytes | None = None
    image_hash: str | None = None
    width: int = 0
    height: int = 0


def _decode(data: bytes) -> np.ndarray | None:
    array = np.frombuffer(data, np.uint8)
    return cv2.imdecode(array, cv2.IMREAD_COLOR)


def is_blurry(gray: np.ndarray, threshold: float = BLUR_THRESHOLD) -> tuple[bool, float]:
    """Laplacian 方差衡量清晰度，返回 (是否模糊, 方差)。"""
    score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return score < threshold, score


def prepare_image(data: bytes, *, allow_blurry: bool = False) -> PreparedImage:
    """压缩到 MAX_SIDE 内并转 JPEG；模糊图默认拒绝（不猜测内容）。"""
    if not data:
        return PreparedImage(False, "没有收到图片。")
    image = _decode(data)
    if image is None:
        return PreparedImage(False, "图片无法解码，请上传 PNG/JPG 格式。")

    height, width = image.shape[:2]
    scale = min(1.0, MAX_SIDE / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurry, score = is_blurry(gray)
    if blurry and not allow_blurry:
        return PreparedImage(
            False,
            f"图片太模糊（清晰度 {score:.1f} < {BLUR_THRESHOLD:.0f}），请重拍一张再上传，避免识别错金额。",
        )

    # 轻度 CLAHE 增强对比度，提升小票文字可辨识度
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    image = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    if not ok:
        return PreparedImage(False, "图片编码失败，请重试。")
    encoded = buffer.tobytes()
    digest = hashlib.sha256(encoded).hexdigest()
    return PreparedImage(
        True,
        f"图片已预处理（{width}x{height}，清晰度 {score:.1f}）。",
        encoded,
        digest,
        image.shape[1],
        image.shape[0],
    )
