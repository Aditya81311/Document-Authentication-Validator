import io
from PIL import Image, ImageEnhance, ImageFilter


def extract_image_from_file(file_bytes: bytes, file_ext: str):
    """
    Extract a preprocessed PIL Image from the uploaded file.
    Returns: (PIL.Image or None, image_bytes or None, media_type str)
    """
    ext = file_ext.lower().lstrip('.')

    if ext == 'pdf':
        return _from_pdf(file_bytes)
    elif ext in ('jpg', 'jpeg', 'png'):
        return _from_image(file_bytes)
    elif ext == 'docx':
        return None, None, None
    return None, None, None


def _from_pdf(file_bytes: bytes):
    try:
        import fitz  # PyMuPDF
        doc  = fitz.open(stream=file_bytes, filetype='pdf')
        page = doc[0]
        mat  = fitz.Matrix(2.5, 2.5)   # 2.5x zoom → ~180 DPI equivalent
        pix  = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes('png')
        pil_img   = Image.open(io.BytesIO(img_bytes)).convert('RGB')
        pil_img   = _preprocess(pil_img)
        out = io.BytesIO()
        pil_img.save(out, format='PNG')
        return pil_img, out.getvalue(), 'image/png'
    except Exception as e:
        print(f'[extractor] PDF error: {e}')
        return None, None, None


def _from_image(file_bytes: bytes):
    try:
        pil_img = Image.open(io.BytesIO(file_bytes)).convert('RGB')
        pil_img = _preprocess(pil_img)
        out = io.BytesIO()
        pil_img.save(out, format='PNG')
        return pil_img, out.getvalue(), 'image/png'
    except Exception as e:
        print(f'[extractor] Image error: {e}')
        return None, None, None


def _preprocess(img: Image.Image) -> Image.Image:
    """
    Prepare image for best OCR accuracy:
    1. Upscale if too small — Tesseract needs ~150px per character height
    2. Convert to grayscale
    3. Boost contrast
    4. Sharpen edges
    """
    # 1. Upscale to minimum 1800px wide if smaller
    w, h = img.size
    min_width = 1800
    if w < min_width:
        scale  = min_width / w
        img    = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # 2. Grayscale — OCR works better on single channel
    img = img.convert('L')

    # 3. Contrast boost — helps on faded / scanned certificates
    img = ImageEnhance.Contrast(img).enhance(1.8)

    # 4. Sharpness — improves edge definition on blurry scans
    img = ImageEnhance.Sharpness(img).enhance(2.0)

    # 5. Back to RGB (Tesseract handles both, but consistent with rest of pipeline)
    img = img.convert('RGB')

    return img


def extract_text_from_docx(file_bytes: bytes) -> str:
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        return '\n'.join([p.text for p in doc.paragraphs if p.text.strip()])
    except Exception as e:
        print(f'[extractor] DOCX error: {e}')
        return ''