import os

class OCRProcessor:
    def __init__(self):
        self.reader = None
        
    def get_reader(self):
        if self.reader is None:
            try:
                import easyocr
                self.reader = easyocr.Reader(['en'])
            except ImportError:
                self.reader = None
        return self.reader
        
    def extract_text(self, image_source) -> str:
        reader = self.get_reader()
        if not reader:
            return "OCR is not available. Please install easyocr."

        temp_path = None
        target_path = image_source

        if not isinstance(image_source, str):
            import uuid
            temp_path = f"/tmp/blob_ocr_{uuid.uuid4().hex}.png"
            image_source.save(temp_path)
            target_path = temp_path

        try:
            result = reader.readtext(target_path)
            return " ".join([text for _, text, _ in result])
        except Exception as e:
            return f"Failed to extract text: {e}"
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
