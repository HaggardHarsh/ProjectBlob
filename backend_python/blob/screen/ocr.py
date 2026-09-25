import easyocr

class OCRProcessor:
    def __init__(self):
        self.reader = None
        
    def get_reader(self):
        if self.reader is None:
            self.reader = easyocr.Reader(['en'])
        return self.reader
        
    def extract_text(self, image_path: str) -> str:
        reader = self.get_reader()
        result = reader.readtext(image_path)
        return " ".join([text for _, text, _ in result])
