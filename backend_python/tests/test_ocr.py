from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

from blob.screen.ocr import OCRProcessor


def test_rapidocr_output_is_joined_for_screen_context():
    ocr = OCRProcessor()
    ocr.backend = "rapidocr"
    ocr.reader = MagicMock(return_value=SimpleNamespace(txts=("Project Blob", "Screen ready")))

    text = ocr.extract_text(Image.new("RGB", (8, 8)))

    assert text == "Project Blob Screen ready"
    ocr.reader.assert_called_once()
