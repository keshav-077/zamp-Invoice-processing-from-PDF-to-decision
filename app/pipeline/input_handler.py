"""
InvoiceFlow AI — Input Handler

Responsible for:
1. File validation (type, size, corruption checks)
2. PDF rendering to page images (via PyMuPDF)
3. Image validation and normalization (via Pillow)
4. Light preprocessing (deskew, rotation, contrast via OpenCV)

Output: A list of preprocessed page images (PNG bytes) ready for the vision model.
Regardless of input format, the output is always a uniform list of image bytes.
"""

import io
import logging
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

from app.config import settings

logger = logging.getLogger(__name__)


class InputValidationError(Exception):
    """Raised when an input file fails validation."""
    pass


class InputHandler:
    """Validates, renders, and preprocesses invoice documents."""

    SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
    PDF_RENDER_DPI = 200  # Resolution for PDF page rendering

    def validate_and_preprocess(self, file_path: Path) -> list[bytes]:
        """
        Full input pipeline: validate → render → preprocess.

        Args:
            file_path: Path to the uploaded invoice file.

        Returns:
            List of preprocessed page images as PNG bytes.

        Raises:
            InputValidationError: If the file fails any validation check.
        """
        logger.info(f"Processing input: {file_path.name}")

        # Step 1: Basic file validation
        self._validate_file(file_path)

        # Step 2: Render to page images
        extension = file_path.suffix.lower()
        if extension == ".pdf":
            raw_images = self._render_pdf(file_path)
        else:
            raw_images = self._load_image(file_path)

        logger.info(f"Rendered {len(raw_images)} page(s)")

        # Step 3: Light preprocessing
        processed = []
        for i, img_bytes in enumerate(raw_images):
            preprocessed = self._preprocess_image(img_bytes, page_num=i + 1)
            processed.append(preprocessed)

        logger.info(f"Preprocessing complete: {len(processed)} page(s) ready")
        return processed

    def _validate_file(self, file_path: Path) -> None:
        """Run basic file validation checks."""
        # File exists
        if not file_path.exists():
            raise InputValidationError(f"File not found: {file_path}")

        # File is not empty
        if file_path.stat().st_size == 0:
            raise InputValidationError(f"File is empty: {file_path.name}")

        # File size within limit
        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > settings.max_file_size_mb:
            raise InputValidationError(
                f"File too large: {size_mb:.1f}MB (max {settings.max_file_size_mb}MB)"
            )

        # Supported extension
        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise InputValidationError(
                f"Unsupported file type: {ext}. Supported: {', '.join(self.SUPPORTED_EXTENSIONS)}"
            )

        logger.info(f"File validation passed: {file_path.name} ({size_mb:.2f}MB)")

    def _render_pdf(self, file_path: Path) -> list[bytes]:
        """
        Render each page of a PDF to a PNG image.
        Uses PyMuPDF (fitz) for both validation and rendering.
        """
        try:
            doc = fitz.open(str(file_path))
        except Exception as e:
            raise InputValidationError(f"Cannot open PDF (possibly corrupted): {e}")

        page_count = doc.page_count

        if page_count == 0:
            doc.close()
            raise InputValidationError("PDF has no pages")

        if page_count > settings.max_pages:
            doc.close()
            raise InputValidationError(
                f"PDF has {page_count} pages (max {settings.max_pages})"
            )

        logger.info(f"PDF opened: {page_count} page(s)")
        images = []

        for page_num in range(page_count):
            page = doc[page_num]
            # Render at target DPI
            zoom = self.PDF_RENDER_DPI / 72  # 72 is default PDF DPI
            matrix = fitz.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix)

            # Convert to PNG bytes
            png_bytes = pixmap.tobytes("png")
            images.append(png_bytes)
            logger.debug(f"Rendered page {page_num + 1}: {pixmap.width}x{pixmap.height}")

        doc.close()
        return images

    def _load_image(self, file_path: Path) -> list[bytes]:
        """
        Load and validate a single image file.
        Returns a list with one PNG image (for consistency with PDF flow).
        """
        try:
            img = Image.open(file_path)
            img.verify()  # Verify image integrity
        except Exception as e:
            raise InputValidationError(f"Cannot open image (possibly corrupted): {e}")

        # Re-open after verify (verify closes the image)
        img = Image.open(file_path)

        # Convert to RGB if necessary (e.g., RGBA, grayscale)
        if img.mode != "RGB":
            img = img.convert("RGB")

        # Convert to PNG bytes
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        logger.info(f"Image loaded: {img.width}x{img.height} ({img.mode})")
        return [png_bytes]

    def _preprocess_image(self, image_bytes: bytes, page_num: int = 1) -> bytes:
        """
        Apply light preprocessing to improve vision model input quality.

        Steps:
        1. Decode image
        2. Deskew correction (if skew detected)
        3. Contrast enhancement (CLAHE)
        4. Re-encode to PNG

        This is intentionally conservative — heavy preprocessing can
        degrade quality for already-clean documents.
        """
        # Decode PNG bytes to OpenCV array
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            logger.warning(f"Page {page_num}: Could not decode image, returning original")
            return image_bytes

        # --- Denoise (helps crumpled/low-quality scans) ---
        img = self._denoise(img, page_num)

        # --- Deskew detection and correction ---
        img = self._auto_deskew(img, page_num)

        # --- Contrast enhancement (CLAHE) ---
        img = self._enhance_contrast(img, page_num)

        # Re-encode to PNG
        success, encoded = cv2.imencode(".png", img)
        if not success:
            logger.warning(f"Page {page_num}: PNG re-encode failed, returning original")
            return image_bytes

        return encoded.tobytes()

    def score_document_quality(self, image_bytes: bytes) -> float:
        """
        Score scan quality 0.0–1.0 from blur, contrast, and brightness.
        Used for routing and threshold overrides (Phase 4).
        """
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.5

        blur = cv2.Laplacian(img, cv2.CV_64F).var()
        blur_score = min(1.0, blur / 500.0)

        contrast = float(np.std(img)) / 128.0
        contrast_score = min(1.0, contrast)

        mean_brightness = float(np.mean(img)) / 255.0
        brightness_score = 1.0 - abs(mean_brightness - 0.5) * 2

        return float(
            round((blur_score * 0.5 + contrast_score * 0.3 + brightness_score * 0.2), 3)
        )

    def _denoise(self, img: np.ndarray, page_num: int) -> np.ndarray:
        """Apply fast non-local means denoising for noisy scans."""
        try:
            result = cv2.fastNlMeansDenoisingColored(img, None, 6, 6, 7, 21)
            logger.debug(f"Page {page_num}: Denoise applied")
            return result
        except cv2.error:
            return img

    def _auto_deskew(self, img: np.ndarray, page_num: int) -> np.ndarray:
        """
        Detect and correct document skew using Hough Line Transform.
        Only corrects if skew angle is between 0.5° and 15°.
        """
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)

        if lines is None:
            return img

        # Calculate median angle from detected lines
        angles = []
        for line in lines:
            # Handle both array and scalar cases
            coords = line[0] if isinstance(line, np.ndarray) and line.ndim > 1 else line
            if not isinstance(coords, (list, tuple, np.ndarray)) or len(coords) < 4:
                continue
            x1, y1, x2, y2 = coords[0], coords[1], coords[2], coords[3]
            if x2 - x1 == 0:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            angles.append(angle)

        if not angles:
            return img

        median_angle = np.median(angles)

        # Only correct if skew is meaningful but not extreme
        if 0.5 < abs(median_angle) < 15:
            logger.info(f"Page {page_num}: Deskewing by {median_angle:.2f}°")
            h, w = img.shape[:2]
            center = (w // 2, h // 2)
            rotation_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
            img = cv2.warpAffine(
                img, rotation_matrix, (w, h),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )

        return img

    def _enhance_contrast(self, img: np.ndarray, page_num: int) -> np.ndarray:
        """
        Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
        to the luminance channel for improved text readability.
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)

        # Apply CLAHE to luminance channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_enhanced = clahe.apply(l_channel)

        # Merge back
        lab_enhanced = cv2.merge([l_enhanced, a_channel, b_channel])
        result = cv2.cvtColor(lab_enhanced, cv2.COLOR_LAB2BGR)

        logger.debug(f"Page {page_num}: Contrast enhancement applied")
        return result
