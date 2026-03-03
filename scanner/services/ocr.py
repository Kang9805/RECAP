import cv2
import pytesseract
import re


def _deskew_image(gray_image):
    inverted = cv2.bitwise_not(gray_image)
    _, binary = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    coords = cv2.findNonZero(binary)
    if coords is None:
        return gray_image

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle

    if abs(angle) < 0.1:
        return gray_image

    height, width = gray_image.shape[:2]
    center = (width // 2, height // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

    return cv2.warpAffine(
        gray_image,
        rotation_matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def preprocess_receipt_image(image_path: str):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Failed to load image: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    deskewed = _deskew_image(gray)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(deskewed)
    denoised = cv2.GaussianBlur(contrast, (3, 3), 0)

    adaptive = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        15,
    )
    _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    opened = cv2.morphologyEx(otsu, cv2.MORPH_OPEN, kernel)
    closed = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel)

    scaled = cv2.resize(denoised, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_CUBIC)
    scaled_adaptive = cv2.adaptiveThreshold(
        scaled,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10,
    )

    return [adaptive, otsu, opened, closed, scaled_adaptive]


def _score_ocr_text(text: str) -> float:
    cleaned = text.strip()
    if not cleaned:
        return 0.0

    total = max(len(cleaned), 1)
    valid_chars = len(re.findall(r'[가-힣A-Za-z0-9\s.,:/()%-]', cleaned))
    hangul = len(re.findall(r'[가-힣]', cleaned))
    digits = len(re.findall(r'\d', cleaned))
    money_like = len(re.findall(r'\d{1,3}(?:[,\.]\d{3})+', cleaned))
    lines = len([line for line in cleaned.splitlines() if line.strip()])
    weird_chars = len(re.findall(r'[^가-힣A-Za-z0-9\s.,:/()%-]', cleaned))

    return (
        (valid_chars / total) * 100
        + hangul * 0.6
        + digits * 0.4
        + money_like * 0.8
        + lines * 0.3
        - weird_chars * 0.5
    )


def extract_text_from_receipt(image_path: str) -> str:
    preprocessed_candidates = preprocess_receipt_image(image_path)
    tesseract_configs = (
        '--oem 1 --psm 6 -c preserve_interword_spaces=1',
        '--oem 1 --psm 4 -c preserve_interword_spaces=1',
        '--oem 1 --psm 11 -c preserve_interword_spaces=1',
    )

    best_text = ''
    best_score = -1.0

    for image in preprocessed_candidates:
        for config in tesseract_configs:
            text = pytesseract.image_to_string(image, lang='kor+eng', config=config)
            score = _score_ocr_text(text)
            if score > best_score:
                best_score = score
                best_text = text

    return best_text
