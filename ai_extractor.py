"""
Offline field extractor — Tesseract OCR + dynamic keyword matching.
No API, no internet, no GPU.

Install:
  pip install pytesseract pillow
  sudo apt install tesseract-ocr   # Linux
  brew install tesseract           # Mac
  # Windows: https://github.com/UB-Mannheim/tesseract/wiki
"""

import re
import io
from PIL import Image


def extract_fields_with_ai(image_bytes=None, media_type='image/png',
                           text_content=None, field_names=None):
    text = ''
    if image_bytes:
        text = _ocr_image(image_bytes)
    elif text_content:
        text = text_content

    if not text.strip() or not field_names:
        return {f: None for f in (field_names or [])}

    return _extract_dynamic(text, field_names)


def _ocr_image(image_bytes: bytes) -> str:
    try:
        import pytesseract
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
        return pytesseract.image_to_string(img, config='--psm 6')
    except ImportError:
        print('[ocr] pytesseract not installed.')
        return ''
    except Exception as e:
        print(f'[ocr] error: {e}')
        return ''


def _extract_dynamic(text: str, field_names: list) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    flat  = ' '.join(lines)
    return {field: _extract_one(field, lines, flat) for field in field_names}


def _extract_one(field_name: str, lines: list, flat: str):
    fn = field_name.lower()

    # ── Priority: specific types before generic fallbacks ──────
    # URL fields — check first, very specific
    if any(w in fn for w in ['url', 'link', 'verify', 'validation', 'certificate url']):
        return _find_url(flat)

    # Code / ID fields — before "name" check
    if any(w in fn for w in ['code', 'id', 'roll', 'enrollment', 'reg', 'license', 'number', 'no.']):
        val = _find_identifier(flat, fn)
        if val:
            return val

    # Date fields
    if any(w in fn for w in ['issue date', 'valid until', 'expiry', 'expir', 'completion date']) or (('date' in fn) and ('issue' in fn or 'complet' in fn or 'valid' in fn)):
        return _find_date_or_year(flat)

    # Duration
    if any(w in fn for w in ['duration', 'hours', 'days', 'weeks', 'months']):
        return _find_duration(flat)

    # Organisation — before "name" check to avoid "Issuing Authority" → person name
    if any(w in fn for w in ['institution', 'university', 'college', 'organizer', 'authority',
                              'issuing', 'board', 'institute', 'school', 'academy', 'issued by',
                              'issuer', 'organisation', 'organization', 'company', 'provider']):
        return _find_organisation(lines, flat)

    # Course/subject fields — before "name" check so "Course Name" goes here not to person
    if any(w in fn for w in ['course', 'degree', 'program', 'diploma', 'subject',
                              'discipline', 'workshop', 'training', 'field', 'certification']):
        val = _find_course(flat)
        if val:
            return val

    # Person name — only if field clearly means a person
    if any(w in fn for w in ['participant', 'student', 'holder', 'recipient',
                              'candidate', 'awardee', 'name']):
        # Double-check: don't use person extraction if "course" or "org" keyword also present
        is_course_name = any(w in fn for w in ['course', 'degree', 'subject', 'program'])
        is_org_name    = any(w in fn for w in ['institution', 'authority', 'issuing', 'company'])
        if not is_course_name and not is_org_name:
            return _find_person_name(lines, flat)

    # ── Fallback: label-based extraction ──────────────────────
    keywords = [re.escape(w) for w in field_name.split() if len(w) > 2]
    if keywords:
        label_pat = r'(?:' + r'[\s\-]*'.join(keywords) + r')\s*[:\-\|]?\s*(.{2,80})'
        m = re.search(label_pat, flat, re.IGNORECASE)
        if m:
            val = _clean_value(m.group(1))
            if val:
                return val

    return None


# ── OCR helpers ───────────────────────────────────────────────

def _find_url(flat: str):
    m = re.search(r'https?://[^\s<>"\']+', flat)
    return m.group(0).strip('.,;)') if m else None


def _find_identifier(flat: str, fn: str = ''):
    # Parenthesized codes like (CEPYT1IN) — common on IBM certs
    m = re.search(r'\(([A-Z0-9]{4,20})[,\s)]', flat)
    if m:
        return m.group(1)

    # Label-prefixed identifier
    m = re.search(
        r'(?:code|id|roll|enrollment|reg(?:istration)?|license|certificate)\s*[:\-#]?\s*'
        r'([A-Z0-9][A-Z0-9\/\-]{2,20})',
        flat, re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # Standalone alphanumeric code: 6-20 chars, mix of letters+digits
    m = re.search(r'\b([A-Z]{2,8}\d{2,8}[A-Z0-9]*)\b', flat)
    if m:
        return m.group(1)

    return None


def _find_date_or_year(flat: str):
    # Full named-month date first: "November 25, 2024" / "25 November 2024"
    m = re.search(
        r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{4})\b',
        flat, re.IGNORECASE
    )
    if m:
        return m.group(1)

    m = re.search(
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b',
        flat, re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Numeric date: DD/MM/YYYY or MM-DD-YYYY
    m = re.search(r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b', flat)
    if m:
        return m.group(1)

    # Context year
    m = re.search(
        r'(?:year|issued|awarded|passed|completed|valid|dated?)[^\d]{0,20}(20\d{2}|19\d{2})',
        flat, re.IGNORECASE
    )
    if m:
        return m.group(1)

    # Last bare year as fallback
    years = re.findall(r'\b((?:19|20)\d{2})\b', flat)
    return years[-1] if years else None


def _find_person_name(lines: list, flat: str):
    # "certify that NAME" pattern
    m = re.search(
        r'(?:certif(?:y|ied)\s+that|awarded\s+to|presented\s+to|'
        r'conferred\s+(?:upon|to)|this\s+is\s+to\s+certify\s+that)\s+(.{4,50})',
        flat, re.IGNORECASE
    )
    if m:
        return _clean_name(m.group(1))

    m = re.search(r'(?:student|participant|holder|recipient)\s+name\s*[:\-]\s*(.{4,50})', flat, re.IGNORECASE)
    if m:
        return _clean_name(m.group(1))

    # ALL-CAPS line of 2–4 words (common name style on certificates)
    for line in lines:
        words = line.split()
        # filter single-char OCR noise, require real words
        real_words = [w for w in words if w.isalpha() and len(w) > 1]
        if 2 <= len(real_words) <= 4 and all(w.isupper() for w in real_words):
            return ' '.join(real_words).title()

    return None


_NAME_STOP = re.compile(
    r'\b(has|have|having|is|was|the|in|of|for|and|with|successfully|'
    r'hereby|been|passed|completed|awarded|received)\b',
    re.IGNORECASE
)

def _clean_name(raw: str) -> str:
    m = _NAME_STOP.search(raw)
    result = raw[:m.start()].strip() if m else raw.strip()
    # filter single-char words (OCR noise) and non-alpha
    words = [w for w in result.split() if re.match(r'^[A-Za-z\.]+$', w) and len(w) > 1]
    name = ' '.join(words[:4]).title()
    return name if len(name) > 2 else None


def _find_organisation(lines: list, flat: str):
    # "Issued by\nORG NAME" — multiline, very common pattern
    m = re.search(r'[Ii]ssued\s+by\s*\n?\s*([A-Za-z][A-Za-z\s&\.,]{4,60})', flat)
    if m:
        val = m.group(1).strip().split('\n')[0].strip()
        # remove single-char OCR artifacts (e.g. 'a' from signature scan)
        val = ' '.join(w for w in val.split() if len(w) > 1)
        if len(val) > 4:
            return val[:80]

    # Org keyword in text
    m = re.search(
        r'([A-Za-z][A-Za-z\s&\.,]{3,60}'
        r'(?:University|Institute|College|Board|Council|Academy|'
        r'School|Organization|Program|Network|Ltd|Inc|Corp|Pvt))',
        flat, re.IGNORECASE
    )
    if m:
        val = m.group(1).strip()
        if len(val) > 5:
            return val[:80]

    # Letterhead / footer lines
    for line in (lines[:3] + lines[-3:]):
        if re.search(r'university|institute|college|board|academy|program|network|ltd|pvt',
                     line, re.IGNORECASE):
            return line[:80]

    return None


def _find_course(flat: str):
    pats = [
        r'(Bachelor\s+of\s+[A-Za-z\s]{3,40})',
        r'(Master\s+of\s+[A-Za-z\s]{3,40})',
        r'(Doctor\s+of\s+[A-Za-z\s]{3,40})',
        r'(B\.?\s*Tech[A-Za-z\s\.]{0,30})',
        r'(M\.?\s*Tech[A-Za-z\s\.]{0,30})',
        r'(Diploma\s+in\s+[A-Za-z\s]{3,40})',
        r'(Certificate\s+(?:in|of)\s+[A-Za-z\s]{3,40})',
        r'(Ph\.?\s*D[A-Za-z\s\.]{0,20})',
        r'(MBA[A-Za-z\s\.]{0,20})',
    ]
    for pat in pats:
        m = re.search(pat, flat, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(r'\bfrom\b|\band\b|\bhas\b', val, flags=re.IGNORECASE)[0].strip()
            val = re.split(r'\s*\(', val)[0].strip()
            return val[:80]

    # "passing grade in COURSE NAME" — IBM style
    m = re.search(r'(?:grade\s+in|completed\s+(?:the\s+)?course\s+in|course\s+in)\s+(.{3,60})', flat, re.IGNORECASE)
    if m:
        val = _clean_value(m.group(1))
        # cut at parenthesis — e.g. "Introduction to Python (CEPYT1IN..."
        if val:
            val = re.split(r'\s*\(', val)[0].strip()
        return val if val else None

    return None


def _find_duration(flat: str):
    m = re.search(r'(\d+\s*(?:hours?|days?|weeks?|months?))', flat, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _clean_value(raw: str) -> str:
    cut = re.split(
        r'\b(has|have|is|was|the\s+course|for|and\s+has|hereby|been|provided\s+by)\b',
        raw, maxsplit=1, flags=re.IGNORECASE
    )[0]
    val = re.sub(r'\s+', ' ', cut).strip(' .,;:-|()')
    return val if len(val) >= 2 else None