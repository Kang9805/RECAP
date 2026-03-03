import cv2
import pytesseract
import re

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None


_paddle_ocr_engine = None


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

    scaled = cv2.resize(denoised, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_CUBIC)
    scaled_adaptive = cv2.adaptiveThreshold(
        scaled,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        10,
    )

    return [adaptive, scaled_adaptive, otsu]


def _extract_text_line_by_line(binary_image) -> str:
    if len(binary_image.shape) != 2:
        return ''

    inverted = cv2.bitwise_not(binary_image)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 3))
    connected = cv2.morphologyEx(inverted, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return ''

    boxes = []
    for contour in contours:
        x, y, width, height = cv2.boundingRect(contour)
        if width < 80 or height < 10:
            continue
        if height > binary_image.shape[0] * 0.2:
            continue
        boxes.append((x, y, width, height))

    boxes.sort(key=lambda box: box[1])

    lines = []
    for x, y, width, height in boxes:
        margin = 4
        y0 = max(0, y - margin)
        y1 = min(binary_image.shape[0], y + height + margin)
        x0 = max(0, x - margin)
        x1 = min(binary_image.shape[1], x + width + margin)
        roi = binary_image[y0:y1, x0:x1]

        line_text = pytesseract.image_to_string(
            roi,
            lang='kor+eng',
            config='--oem 1 --psm 7 -c preserve_interword_spaces=1',
        )
        cleaned = line_text.strip()
        if cleaned:
            lines.append(cleaned)

    return '\n'.join(lines)


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
    item_like_lines = len(
        re.findall(r'\d[\d,\.]*\s+\d{1,2}\s+\d[\d,\.]*', cleaned)
    )
    single_char_lines = len(re.findall(r'^\s*[^\s]\s*$', cleaned, flags=re.MULTILINE))

    return (
        (valid_chars / total) * 100
        + hangul * 0.6
        + digits * 0.4
        + money_like * 0.8
        + item_like_lines * 2.0
        + lines * 0.3
        - weird_chars * 0.5
        - single_char_lines * 0.8
    )


def _get_paddle_ocr_engine():
    global _paddle_ocr_engine

    if PaddleOCR is None:
        return None

    if _paddle_ocr_engine is not None:
        return _paddle_ocr_engine

    try:
        _paddle_ocr_engine = PaddleOCR(
            use_angle_cls=False,
            lang='korean',
            show_log=False,
        )
    except Exception:
        _paddle_ocr_engine = None

    return _paddle_ocr_engine


def _extract_text_with_paddle(image_path: str, preprocessed_candidates) -> str:
    engine = _get_paddle_ocr_engine()
    if engine is None:
        return ''

    source = cv2.imread(image_path)
    images = []
    if source is not None:
        images.append(source)
    elif preprocessed_candidates:
        selected = preprocessed_candidates[1] if len(preprocessed_candidates) > 1 else preprocessed_candidates[0]
        if len(selected.shape) == 2:
            images.append(cv2.cvtColor(selected, cv2.COLOR_GRAY2BGR))
        else:
            images.append(selected)

    best_text = ''
    best_score = -1.0

    for image in images:
        try:
            result = engine.ocr(image, cls=False)
        except Exception:
            continue

        lines = []
        if not result:
            continue

        for block in result:
            if not block:
                continue
            for row in block:
                if len(row) < 2:
                    continue
                text_info = row[1]
                if not text_info or len(text_info) < 2:
                    continue
                text = str(text_info[0]).strip()
                confidence = float(text_info[1])
                if text and confidence >= 0.35:
                    lines.append(text)

        candidate_text = '\n'.join(lines).strip()
        if not candidate_text:
            continue

        score = _score_ocr_text(candidate_text)
        if score > best_score:
            best_score = score
            best_text = candidate_text

    return best_text


def extract_text_from_receipt(image_path: str) -> str:
    preprocessed_candidates = preprocess_receipt_image(image_path)
    tesseract_configs = (
        '--oem 1 --psm 6 -c preserve_interword_spaces=1',
        '--oem 1 --psm 11 -c preserve_interword_spaces=1',
    )

    best_text = ''
    best_score = -1.0
    ranked_candidates = []

    paddle_text = _extract_text_with_paddle(image_path, preprocessed_candidates)
    if paddle_text:
        paddle_score = _score_ocr_text(paddle_text)
        ranked_candidates.append((paddle_score, paddle_text))
        if paddle_score > best_score:
            best_score = paddle_score
            best_text = paddle_text

        if paddle_score >= 120:
            return best_text

    for image in preprocessed_candidates[:2]:
        line_text = _extract_text_line_by_line(image)
        if line_text:
            line_score = _score_ocr_text(line_text)
            ranked_candidates.append((line_score, line_text))
            if line_score > best_score:
                best_score = line_score
                best_text = line_text

        for config in tesseract_configs:
            text = pytesseract.image_to_string(image, lang='kor+eng', config=config)
            score = _score_ocr_text(text)
            ranked_candidates.append((score, text))
            if score > best_score:
                best_score = score
                best_text = text

    non_empty_candidates = [
        (score, text)
        for score, text in ranked_candidates
        if text and text.strip()
    ]
    non_empty_candidates.sort(key=lambda item: item[0], reverse=True)

    if len(non_empty_candidates) >= 2:
        first_text = non_empty_candidates[0][1]
        second_text = non_empty_candidates[1][1]

        merged_lines = []
        seen = set()
        for source_text in (first_text, second_text):
            for line in source_text.splitlines():
                normalized = re.sub(r'\s+', ' ', line).strip()
                if not normalized:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                merged_lines.append(normalized)

        merged_text = '\n'.join(merged_lines)
        merged_score = _score_ocr_text(merged_text)
        if merged_score > best_score:
            best_score = merged_score
            best_text = merged_text

    return best_text
