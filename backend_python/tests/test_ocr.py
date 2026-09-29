from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

from PIL import Image

from blob.screen.ocr import OCRProcessor


def test_rapidocr_preserves_line_breaks_for_screen_context():
    ocr = OCRProcessor()
    ocr.backend = "rapidocr"
    ocr.reader = MagicMock(return_value=SimpleNamespace(txts=("Project Blob", "Screen ready")))

    text = ocr.extract_text(Image.new("RGB", (8, 8)))

    assert text == "Project Blob\nScreen ready"
    ocr.reader.assert_called_once()


def test_rapidocr_starts_without_info_logs(monkeypatch):
    reader_type = MagicMock()
    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(RapidOCR=reader_type))
    OCRProcessor().get_reader()
    reader_type.assert_called_once_with(params={"Global.log_level": "warning"})
