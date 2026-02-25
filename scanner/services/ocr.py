import cv2
import pytesseract


def preprocess_receipt_image(image_path: str):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Failed to load image: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    denoised = cv2.GaussianBlur(gray, (3, 3), 0)
    thresholded = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        15,
    )
    return thresholded


def extract_text_from_receipt(image_path: str) -> str:
    preprocessed = preprocess_receipt_image(image_path)
    return pytesseract.image_to_string(preprocessed, lang='kor')
