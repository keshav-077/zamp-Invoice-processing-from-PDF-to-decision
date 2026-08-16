"""
InvoiceFlow AI — Input Handler Tests

Tests file validation logic including:
- Supported file types
- Unsupported file types
- Empty files
- Missing files
"""

import pytest
import tempfile
from pathlib import Path
from app.pipeline.input_handler import InputHandler, InputValidationError


@pytest.fixture
def handler():
    return InputHandler()


class TestFileValidation:
    """Tests for file validation checks."""

    def test_missing_file(self, handler):
        """Non-existent file should raise InputValidationError."""
        with pytest.raises(InputValidationError, match="not found"):
            handler.validate_and_preprocess(Path("nonexistent_invoice.pdf"))

    def test_empty_file(self, handler, tmp_path):
        """Empty file should raise InputValidationError."""
        empty_file = tmp_path / "empty.pdf"
        empty_file.touch()
        with pytest.raises(InputValidationError, match="empty"):
            handler.validate_and_preprocess(empty_file)

    def test_unsupported_extension(self, handler, tmp_path):
        """Unsupported file type should raise InputValidationError."""
        bad_file = tmp_path / "invoice.docx"
        bad_file.write_text("test content")
        with pytest.raises(InputValidationError, match="Unsupported"):
            handler.validate_and_preprocess(bad_file)

    def test_supported_extensions(self, handler):
        """Check that all expected extensions are in the supported set."""
        assert ".pdf" in handler.SUPPORTED_EXTENSIONS
        assert ".png" in handler.SUPPORTED_EXTENSIONS
        assert ".jpg" in handler.SUPPORTED_EXTENSIONS
        assert ".jpeg" in handler.SUPPORTED_EXTENSIONS

    def test_valid_image(self, handler, tmp_path):
        """Valid PNG image should process successfully."""
        from PIL import Image
        img = Image.new("RGB", (100, 100), color="white")
        img_path = tmp_path / "test.png"
        img.save(str(img_path))
        result = handler.validate_and_preprocess(img_path)
        assert len(result) == 1
        assert isinstance(result[0], bytes)
        assert len(result[0]) > 0
