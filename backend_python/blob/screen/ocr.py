import os
import logging

logger = logging.getLogger(__name__)

class OCRProcessor:
    def __init__(self):
        self.reader = None
        self.backend = None
        
    def get_reader(self):
        if self.reader is None:
            try:
                from rapidocr import RapidOCR
                self.reader = RapidOCR(params={"Global.log_level": "warning"})
                self.backend = "rapidocr"
            except ImportError:
                try:
                    import easyocr
                    self.reader = easyocr.Reader(['en'])
                    self.backend = "easyocr"
                except ImportError:
                    return None
        return self.reader
        
    def extract_text(self, image_source) -> str:
        reader = self.get_reader()
        if not reader:
            return "OCR is not available. Install the OCR extra."

        if self.backend == "rapidocr":
            import numpy as np

            if isinstance(image_source, str):
                result = reader(image_source)
            else:
                result = reader(np.asarray(image_source.convert("RGB")))
            return "\n".join(result.txts or ()) or "(No readable text found)"

        temp_path = None
        target_path = image_source

        if not isinstance(image_source, str):
            import uuid
            temp_path = f"/tmp/blob_ocr_{uuid.uuid4().hex}.png"
            image_source.save(temp_path)
            target_path = temp_path

        try:
            result = reader.readtext(target_path)
            return "\n".join(text for _, text, _ in result) or "(No readable text found)"
        except Exception as e:
            logger.warning("OCR failed: %s", e)
            return f"Failed to extract text: {e}"
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
