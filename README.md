# DocAuth — Document Authentication Validator

A self-hosted, fully offline web application for institutions to register original certificates and for verifying parties to validate them — with confidence scores, hash metrics, and field-by-field comparison.

---

## What it does

**Admin (college / institution):**
- Uploads original certificate files
- System extracts SHA-256 hash, perceptual hash (pHash), and fields via OCR
- All markers stored as ground truth in the registry

**User (company / verifier):**
- Uploads a copy of the certificate (scan, photo, PDF export)
- System compares against registry using three matching layers
- Returns a validation report with confidence score and field comparison

---

## How matching works

| Layer | Method | Use case |
|---|---|---|
| 1 | SHA-256 hash | Exact same digital file |
| 2 | Perceptual hash (pHash) | Scanned, photographed, or compressed copies |
| 3 | OCR field extraction | Content-level comparison (name, date, issuer, etc.) |

### Confidence score

```
Confidence = (pHash similarity × 60%) + (field match score × 40%)
```

| Status | Condition |
|---|---|
| ✅ AUTHENTIC | SHA-256 match OR pHash ≥ 90% + fields ≥ 75% |
| 🟢 LIKELY AUTHENTIC | pHash ≥ 90% + fields ≥ 50% |
| ⚠️ SUSPICIOUS | High visual similarity but fields mismatch — possible tampering |
| 🔵 REVIEW NEEDED | pHash 70–89% — manual check advised |
| ❌ NOT FOUND | No matching certificate in registry |

---

## Key features

- **Fully offline** — no external API, no cloud, no internet dependency after setup
- **Dynamic template system** — admin defines field names for any certificate type; no hardcoded assumptions
- **Supports PDF, JPG, PNG, DOCX**
- **Image preprocessing pipeline** — upscale, grayscale, contrast + sharpness boost before OCR for better accuracy on scanned documents
- **Role-based access** — separate admin and user flows
- **Validation logs** — every validation attempt is recorded with scores and matched certificate

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask 3.0 |
| Database | SQLite |
| Auth | Flask-Login (role-based) |
| Cryptographic hash | hashlib (SHA-256) |
| Visual hash | imagehash (pHash) |
| OCR | Tesseract via pytesseract |
| Image processing | Pillow |
| PDF rendering | PyMuPDF (fitz) |
| DOCX parsing | python-docx |
| Frontend | Bootstrap 5, Vanilla JS |

---

## Project structure

```
docauth/
├── app.py                    # All Flask routes
├── database.py               # SQLite schema + seed data
├── requirements.txt
├── utils/
│   ├── hasher.py             # SHA-256, pHash, field comparison, status logic
│   ├── extractor.py          # Image preprocessing + PDF/image/DOCX to PIL
│   └── ai_extractor.py       # OCR orchestration + dynamic field extraction
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── admin/
│   │   ├── dashboard.html
│   │   ├── upload.html
│   │   ├── templates.html
│   │   ├── template_form.html
│   │   ├── certificate_detail.html
│   │   └── logs.html
│   └── user/
│       ├── validate.html
│       └── report.html
├── static/css/style.css
└── uploads/                  # Stored certificate files (gitignore this)
```

---

## Setup

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Tesseract OCR binary

**Linux:**
```bash
sudo apt install tesseract-ocr
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
Download the installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and add it to your system PATH.

### 3. Run

```bash
python app.py
```

Visit `http://localhost:5000`

---

## Default credentials

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin123` |
| User | `user` | `user123` |

> **Change these before any real use.** Update the seeded password hashes in `database.py` using `werkzeug.security.generate_password_hash`.

---

## ⚠️ Remove before production

The login page includes **clickable credential cards** (Admin / Verifier) that auto-fill the username and password on click. This is intentional for testing and demo convenience only.

**Before deploying to any real environment:**

1. Open `templates/login.html`
2. Remove the entire quick access block:

```html
<!-- REMOVE THIS BLOCK IN PRODUCTION -->
<div class="divider"><span>Quick access</span></div>
<div class="cred-hints">
  <div class="cred-card admin" onclick="fillCreds('admin','admin123')"> ... </div>
  <div class="cred-card user"  onclick="fillCreds('user','user123')">  ... </div>
</div>
<!-- END REMOVE -->
```

3. Remove the `fillCreds()` and `selectRole()` JS functions at the bottom of the same file.
4. Replace default passwords with strong credentials.

---

## Adding a certificate template

1. Login as admin → **Templates** → **New Template**
2. Enter a name (e.g. `Infosys Springboard`)
3. Add field names one per line — use natural names as they appear on the certificate:

```
Participant Name
Course Name
Completion Date
Issue Date
Issued By
Verify URL
```

4. Save — the template is now selectable on the upload form

The OCR engine reads the field names as hints to determine what type of value to extract (person name, date, identifier, URL, organisation, etc.). Admin-entered values on upload are always the ground truth — OCR only assists during user validation.

---

## OCR accuracy notes

- Fields that OCR cannot extract are **skipped, not penalized** in the match score
- For best results on physical certificates, scan at minimum 300 DPI
- pHash is the primary matching signal; field comparison adds secondary confidence
- Digital PDF certificates consistently produce better OCR output than photographs

---

## Production checklist

- [ ] Remove quick-access credential cards from `login.html`
- [ ] Change default admin and user passwords
- [ ] Set a strong `SECRET_KEY` as an environment variable
- [ ] Add `uploads/` to `.gitignore` — do not commit certificate files
- [ ] Migrate from SQLite to PostgreSQL for large-scale use
- [ ] Set up regular database backups
- [ ] Add HTTPS via reverse proxy (nginx + certbot)

---

## License

MIT
