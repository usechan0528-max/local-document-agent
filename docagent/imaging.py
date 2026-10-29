"""Conservative image diagnosis and candidate generation. Never overwrite source."""
import cv2
import numpy as np
from PIL import Image, ImageOps

MAX_PIXELS = 60_000_000


def rgb_image(image):
    if image.width * image.height > MAX_PIXELS:
        raise ValueError("이미지가 6천만 픽셀 제한을 초과합니다.")
    image = ImageOps.exif_transpose(image)
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    return Image.alpha_composite(background, rgba).convert("RGB")


def diagnose(image):
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    # Uniform background can have low variance without being a poor image.
    contrast = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return {"width": image.width, "height": image.height,
            "contrast_span": round(contrast, 2), "laplacian_variance": round(blur, 2),
            "low_contrast_candidate": contrast < 45, "blur_candidate": blur < 70,
            "note": "해상도·배경에 민감한 휴리스틱이며 품질 확정 판정이 아닙니다."}


def candidates(image, quality):
    yield "original", image, []
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    actions = []
    if quality["low_contrast_candidate"]:
        gray = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(gray)
        actions.append("clahe")
    # Mild denoising and local thresholding are evaluated, never blindly accepted.
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 31, 11)
    actions += ["gaussian_blur_3", "adaptive_threshold"]
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 80,
                            minLineLength=max(60, image.width // 6), maxLineGap=20)
    if lines is not None:
        angles = [float(np.degrees(np.arctan2(y2-y1, x2-x1)))
                  for x1, y1, x2, y2 in lines[:, 0]]
        angles = [a for a in angles if abs(a) < 10]
        if len(angles) >= 3:
            angle = float(np.median(angles))
            if 0.4 < abs(angle) < 8:
                matrix = cv2.getRotationMatrix2D((image.width/2, image.height/2), angle, 1)
                gray = cv2.warpAffine(gray, matrix, image.size, borderValue=255)
                actions.append(f"deskew:{angle:.2f}deg")
    yield "adaptive", Image.fromarray(gray).convert("RGB"), actions


def visual_regions(image):
    """Detect ruled structures only; do not claim semantic understanding."""
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, image.width//25), 1)))
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(25, image.height//25))))
    mask = cv2.bitwise_or(horizontal, vertical)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w > image.width*.15 and h > image.height*.06:
            regions.append({"type": "ruled_region_candidate", "bbox": [x, y, x+w, y+h],
                            "coordinate_space": "original_image_pixels", "verified": False})
    return regions


def document_regions(image, limit=3):
    """Bright, low-saturation paper candidates; no semantic or perspective claims.

    Detect at bounded resolution and map back to the original image. Keep a
    generous rectangular margin so imperfect contours do not clip edge text.
    """
    preview = image.copy()
    preview.thumbnail((1400, 1400))
    array = np.asarray(preview)
    hsv = cv2.cvtColor(array, cv2.COLOR_RGB2HSV)
    h, w = array.shape[:2]
    proposals = []
    for value in (110, 140, 170, 200):
        mask = ((hsv[:, :, 1] < 65) & (hsv[:, :, 2] > value)).astype(np.uint8)*255
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if not .025*w*h < area < .85*w*h:
                continue
            hull = cv2.convexHull(contour)
            solidity = area / max(cv2.contourArea(hull), 1)
            polygon = cv2.approxPolyDP(contour, .02*cv2.arcLength(contour, True), True)
            if solidity < .88 or not 4 <= len(polygon) <= 6:
                continue
            x, y, rw, rh = cv2.boundingRect(contour)
            if min(rw, rh) < 100 or not .18 < rw/rh < 5:
                continue
            proposals.append((area*solidity, [x, y, x+rw, y+rh], polygon.reshape(-1, 2)))
    kept = []
    for rank, box, polygon in sorted(proposals, key=lambda v: v[0], reverse=True):
        def overlap(other):
            x0, y0, x1, y1 = box
            a0, b0, a1, b1 = other
            intersection = max(0, min(x1, a1)-max(x0, a0))*max(0, min(y1, b1)-max(y0, b0))
            return intersection / max(1, min((x1-x0)*(y1-y0), (a1-a0)*(b1-b0)))
        if any(overlap(item[1]) > .65 for item in kept):
            continue
        kept.append((rank, box, polygon))
        if len(kept) >= limit:
            break
    result = []
    sx, sy = image.width/w, image.height/h
    for i, (_, (x0, y0, x1, y1), polygon) in enumerate(sorted(kept, key=lambda v: (v[1][1], v[1][0])), 1):
        margin = max(5, round(min(x1-x0, y1-y0)*.035))
        result.append({"id": f"region-{i}", "bbox": [max(0, int((x0-margin)*sx)),
            max(0, int((y0-margin)*sy)), min(image.width, int((x1+margin)*sx)),
            min(image.height, int((y1+margin)*sy))],
            "polygon": [[round(float(x)*sx), round(float(y)*sy)] for x, y in polygon],
            "coordinate_space": "original_image_pixels", "method": "bright_paper_contour",
            "touches_image_edge": x0 <= 1 or y0 <= 1 or x1 >= w-1 or y1 >= h-1,
            "verified": False})
    return result
