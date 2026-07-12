import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import uuid
from datetime import datetime
from functools import wraps

from flask import (Flask, render_template, redirect, url_for,
                   request, flash, session, g, jsonify)
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from database import get_db, init_db
from hasher import compute_sha256, compute_phash, phash_similarity, compare_fields, determine_status
from extractor import extract_image_from_file, extract_text_from_docx
from ai_extractor import extract_fields_with_ai

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-docauth-secret-2024')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager = LoginManager(app)

# Jinja filter: parse JSON in templates
import json as _json
@app.template_filter('from_json')
def from_json_filter(val):
    try: return _json.loads(val)
    except: return []
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


# ── User model ────────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE id = ?', [user_id]).fetchone()
    db.close()
    return User(row['id'], row['username'], row['role']) if row else None

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# ── Helpers ───────────────────────────────────────────────────
def process_document(file_bytes, file_ext, field_names=None):
    sha256 = compute_sha256(file_bytes)
    pil_img, img_bytes, media_type = extract_image_from_file(file_bytes, file_ext)
    phash_str = compute_phash(pil_img) if pil_img else None

    if img_bytes:
        extracted = extract_fields_with_ai(image_bytes=img_bytes, media_type=media_type, field_names=field_names)
    elif file_ext.lower() == 'docx':
        text = extract_text_from_docx(file_bytes)
        extracted = extract_fields_with_ai(text_content=text, field_names=field_names)
    else:
        extracted = {}

    return sha256, phash_str, extracted


def find_best_match(db, query_sha256, query_phash):
    certs = db.execute('SELECT * FROM certificates').fetchall()

    for cert in certs:
        if cert['sha256_hash'] == query_sha256:
            return dict(cert), 100.0, True

    if not query_phash:
        return None, None, False

    best_cert, best_score = None, -1.0
    for cert in certs:
        if cert['phash']:
            score = phash_similarity(query_phash, cert['phash'])
            if score > best_score:
                best_score, best_cert = score, dict(cert)

    return (best_cert, best_score, False) if best_cert else (None, None, False)


# ── Auth ──────────────────────────────────────────────────────
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard') if current_user.role == 'admin' else url_for('user_validate'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        row = db.execute('SELECT * FROM users WHERE username = ?', [username]).fetchone()
        db.close()
        if row and check_password_hash(row['password_hash'], password):
            login_user(User(row['id'], row['username'], row['role']))
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'info')
    return redirect(url_for('login'))


# ── Admin: Templates ──────────────────────────────────────────
@app.route('/admin/templates')
@login_required
@admin_required
def admin_templates():
    db = get_db()
    templates = db.execute(
        'SELECT t.*, u.username as created_by_name, '
        '(SELECT COUNT(*) FROM certificates WHERE template_id = t.id) as cert_count '
        'FROM certificate_templates t LEFT JOIN users u ON t.created_by = u.id '
        'ORDER BY t.created_at DESC'
    ).fetchall()
    db.close()
    return render_template('admin/templates.html', templates=templates)

@app.route('/admin/templates/new', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_template_new():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        raw_fields = request.form.get('fields', '')
        field_names = [f.strip() for f in raw_fields.splitlines() if f.strip()]

        if not name:
            flash('Template name is required.', 'error')
            return redirect(request.url)
        if len(field_names) < 1:
            flash('Add at least one field.', 'error')
            return redirect(request.url)

        db = get_db()
        db.execute(
            'INSERT INTO certificate_templates (name, field_names, created_by) VALUES (?, ?, ?)',
            [name, json.dumps(field_names), current_user.id]
        )
        db.commit()
        db.close()
        flash(f'Template "{name}" created.', 'success')
        return redirect(url_for('admin_templates'))

    return render_template('admin/template_form.html', template=None)

@app.route('/admin/templates/<int:tmpl_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_template_edit(tmpl_id):
    db = get_db()
    tmpl = db.execute('SELECT * FROM certificate_templates WHERE id = ?', [tmpl_id]).fetchone()
    if not tmpl:
        db.close()
        flash('Template not found.', 'error')
        return redirect(url_for('admin_templates'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        raw_fields = request.form.get('fields', '')
        field_names = [f.strip() for f in raw_fields.splitlines() if f.strip()]

        if not name or not field_names:
            flash('Name and fields are required.', 'error')
        else:
            db.execute(
                'UPDATE certificate_templates SET name = ?, field_names = ? WHERE id = ?',
                [name, json.dumps(field_names), tmpl_id]
            )
            db.commit()
            flash(f'Template "{name}" updated.', 'success')
            db.close()
            return redirect(url_for('admin_templates'))

    db.close()
    tmpl = dict(tmpl)
    tmpl['field_names_list'] = json.loads(tmpl['field_names'])
    return render_template('admin/template_form.html', template=tmpl)

@app.route('/admin/templates/<int:tmpl_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_template_delete(tmpl_id):
    db = get_db()
    count = db.execute('SELECT COUNT(*) as c FROM certificates WHERE template_id = ?', [tmpl_id]).fetchone()['c']
    if count > 0:
        flash(f'Cannot delete — {count} certificate(s) use this template.', 'error')
    else:
        db.execute('DELETE FROM certificate_templates WHERE id = ?', [tmpl_id])
        db.commit()
        flash('Template deleted.', 'success')
    db.close()
    return redirect(url_for('admin_templates'))

@app.route('/api/template-fields/<int:tmpl_id>')
@login_required
def api_template_fields(tmpl_id):
    db = get_db()
    tmpl = db.execute('SELECT field_names FROM certificate_templates WHERE id = ?', [tmpl_id]).fetchone()
    db.close()
    if not tmpl:
        return jsonify([])
    return jsonify(json.loads(tmpl['field_names']))


# ── Admin: Certificates ───────────────────────────────────────
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    db = get_db()
    certs = db.execute(
        'SELECT c.*, u.username as uploaded_by_name FROM certificates c '
        'LEFT JOIN users u ON c.uploaded_by = u.id ORDER BY c.uploaded_at DESC'
    ).fetchall()
    total = db.execute('SELECT COUNT(*) as cnt FROM certificates').fetchone()['cnt']
    logs  = db.execute('SELECT COUNT(*) as cnt FROM validation_logs').fetchone()['cnt']
    tmpls = db.execute('SELECT COUNT(*) as cnt FROM certificate_templates').fetchone()['cnt']
    db.close()
    certs = [dict(c) | {'fields_dict': json.loads(c['fields'])} for c in certs]
    return render_template('admin/dashboard.html', certs=certs, total=total,
                           total_validations=logs, total_templates=tmpls)

@app.route('/admin/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_upload():
    db = get_db()
    templates = db.execute('SELECT * FROM certificate_templates ORDER BY name').fetchall()

    if request.method == 'POST':
        tmpl_id = request.form.get('template_id')
        if not tmpl_id:
            flash('Select a template.', 'error')
            db.close()
            return redirect(request.url)

        tmpl = db.execute('SELECT * FROM certificate_templates WHERE id = ?', [tmpl_id]).fetchone()
        if not tmpl:
            flash('Invalid template.', 'error')
            db.close()
            return redirect(request.url)

        field_names = json.loads(tmpl['field_names'])

        if 'certificate' not in request.files or request.files['certificate'].filename == '':
            flash('No file selected.', 'error')
            db.close()
            return redirect(request.url)

        file = request.files['certificate']
        if not allowed_file(file.filename):
            flash('File type not allowed. Use PDF, JPG, PNG, or DOCX.', 'error')
            db.close()
            return redirect(request.url)

        file_bytes = file.read()
        file_ext   = file.filename.rsplit('.', 1)[1].lower()
        orig_name  = secure_filename(file.filename)
        stored_name = f"{uuid.uuid4().hex}_{orig_name}"

        sha256, phash_str, _ = process_document(file_bytes, file_ext, field_names)

        # Duplicate check
        if db.execute('SELECT id FROM certificates WHERE sha256_hash = ?', [sha256]).fetchone():
            db.close()
            flash('This certificate already exists in the system.', 'warning')
            return redirect(url_for('admin_dashboard'))

        # Build fields from form (admin-entered values are ground truth)
        fields = {}
        for fname in field_names:
            val = request.form.get(f'field_{fname}', '').strip()
            fields[fname] = val if val else None

        if not any(fields.values()):
            flash('Please fill in at least one field.', 'error')
            db.close()
            return redirect(request.url)

        save_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_name)
        with open(save_path, 'wb') as f:
            f.write(file_bytes)

        db.execute(
            '''INSERT INTO certificates
               (template_id, template_name, fields, file_type, original_filename,
                stored_filename, sha256_hash, phash, uploaded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [tmpl_id, tmpl['name'], json.dumps(fields), file_ext, orig_name,
             stored_name, sha256, phash_str, current_user.id]
        )
        db.commit()
        db.close()

        first_val = next((v for v in fields.values() if v), 'Certificate')
        flash(f'"{first_val}" uploaded successfully.', 'success')
        return redirect(url_for('admin_dashboard'))

    db.close()
    return render_template('admin/upload.html', templates=templates)

@app.route('/admin/certificate/<int:cert_id>')
@login_required
@admin_required
def admin_certificate_detail(cert_id):
    db = get_db()
    cert = db.execute(
        'SELECT c.*, u.username as uploaded_by_name FROM certificates c '
        'LEFT JOIN users u ON c.uploaded_by = u.id WHERE c.id = ?', [cert_id]
    ).fetchone()
    db.close()
    if not cert:
        flash('Certificate not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    cert = dict(cert)
    cert['fields_dict'] = json.loads(cert['fields'])
    return render_template('admin/certificate_detail.html', cert=cert)

@app.route('/admin/certificate/<int:cert_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_certificate(cert_id):
    db = get_db()
    cert = db.execute('SELECT * FROM certificates WHERE id = ?', [cert_id]).fetchone()
    if not cert:
        db.close()
        flash('Not found.', 'error')
        return redirect(url_for('admin_dashboard'))
    path = os.path.join(app.config['UPLOAD_FOLDER'], cert['stored_filename'])
    if os.path.exists(path):
        os.remove(path)
    db.execute('DELETE FROM certificates WHERE id = ?', [cert_id])
    db.commit()
    db.close()
    flash(f'Certificate #{cert_id} deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logs')
@login_required
@admin_required
def admin_logs():
    db = get_db()
    logs = db.execute(
        '''SELECT vl.*, u.username as validated_by_name, c.template_name, c.fields
           FROM validation_logs vl
           LEFT JOIN users u ON vl.validated_by = u.id
           LEFT JOIN certificates c ON vl.matched_cert_id = c.id
           ORDER BY vl.validated_at DESC LIMIT 100'''
    ).fetchall()
    db.close()
    logs_list = []
    for log in logs:
        l = dict(log)
        if l.get('fields'):
            fd = json.loads(l['fields'])
            l['cert_label'] = next((v for v in fd.values() if v), f"#{l['matched_cert_id']}")
        else:
            l['cert_label'] = None
        logs_list.append(l)
    return render_template('admin/logs.html', logs=logs_list)


# ── User: Validate ────────────────────────────────────────────
@app.route('/validate', methods=['GET', 'POST'])
@login_required
def user_validate():
    if request.method == 'POST':
        if 'certificate' not in request.files or request.files['certificate'].filename == '':
            flash('No file selected.', 'error')
            return redirect(request.url)
        file = request.files['certificate']
        if not allowed_file(file.filename):
            flash('Invalid file type.', 'error')
            return redirect(request.url)

        file_bytes = file.read()
        file_ext   = file.filename.rsplit('.', 1)[1].lower()

        sha256, phash_str, _ = process_document(file_bytes, file_ext)
        db = get_db()
        matched_cert, phash_score, sha256_exact = find_best_match(db, sha256, phash_str)

        field_comparison = {'score': 0, 'matches': {}, 'details': [], 'match_count': 0, 'total': 0}
        query_fields = {}

        if matched_cert:
            stored_fields = json.loads(matched_cert.get('fields') or '{}')
            field_names   = list(stored_fields.keys())
            _, _, query_fields = process_document(file_bytes, file_ext, field_names)
            field_comparison  = compare_fields(stored_fields, query_fields)

        status, confidence, description = determine_status(sha256_exact, phash_score, field_comparison)

        db.execute(
            '''INSERT INTO validation_logs
               (query_filename, query_sha256, query_phash, query_fields,
                matched_cert_id, phash_score, field_match_score, status, confidence, validated_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [secure_filename(file.filename), sha256, phash_str, json.dumps(query_fields),
             matched_cert['id'] if matched_cert else None,
             phash_score, field_comparison['score'], status, confidence, current_user.id]
        )
        db.commit()
        db.close()

        session['last_report'] = {
            'status': status, 'confidence': confidence, 'description': description,
            'sha256_exact': sha256_exact, 'phash_score': phash_score,
            'query_sha256': sha256, 'query_phash': phash_str,
            'query_fields': query_fields, 'matched_cert': matched_cert,
            'field_comparison': field_comparison,
            'query_filename': file.filename,
            'validated_at': datetime.now().strftime('%d %b %Y, %H:%M:%S'),
        }
        return redirect(url_for('user_report'))

    return render_template('user/validate.html')

@app.route('/report')
@login_required
def user_report():
    report = session.get('last_report')
    if not report:
        flash('No report found. Validate a certificate first.', 'info')
        return redirect(url_for('user_validate'))
    if report.get('matched_cert') and report['matched_cert'].get('fields'):
        report['matched_cert']['fields_dict'] = json.loads(report['matched_cert']['fields'])
    return render_template('user/report.html', report=report)


if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
