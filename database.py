import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'docauth.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS certificate_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            field_names TEXT NOT NULL,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER,
            template_name TEXT NOT NULL,
            fields TEXT NOT NULL,
            file_type TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            sha256_hash TEXT NOT NULL,
            phash TEXT,
            uploaded_by INTEGER,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES certificate_templates(id),
            FOREIGN KEY (uploaded_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS validation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_filename TEXT,
            query_sha256 TEXT,
            query_phash TEXT,
            query_fields TEXT,
            matched_cert_id INTEGER,
            phash_score REAL,
            field_match_score REAL,
            status TEXT,
            confidence REAL,
            validated_by INTEGER,
            validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (matched_cert_id) REFERENCES certificates(id),
            FOREIGN KEY (validated_by) REFERENCES users(id)
        );
    ''')

    if not db.execute('SELECT id FROM users WHERE username = ?', ['admin']).fetchone():
        db.execute(
            'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
            ['admin', generate_password_hash('admin123'), 'admin']
        )
    if not db.execute('SELECT id FROM users WHERE username = ?', ['user']).fetchone():
        db.execute(
            'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
            ['user', generate_password_hash('user123'), 'user']
        )

    # Seed sample templates
    import json
    templates = [
        ('Degree Certificate', json.dumps(['Student Name', 'Degree', 'Year of Issue', 'Roll Number', 'Institution'])),
        ('Workshop / Training', json.dumps(['Participant Name', 'Course Name', 'Completion Date', 'Organizer', 'Duration'])),
        ('Professional License', json.dumps(['Holder Name', 'License Number', 'Valid Until', 'Issuing Authority', 'Field'])),
    ]
    for name, fields in templates:
        if not db.execute('SELECT id FROM certificate_templates WHERE name = ?', [name]).fetchone():
            db.execute(
                'INSERT INTO certificate_templates (name, field_names, created_by) VALUES (?, ?, 1)',
                [name, fields]
            )

    db.commit()
    db.close()
