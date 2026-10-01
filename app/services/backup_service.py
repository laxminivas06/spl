import os
import json
import shutil
from datetime import datetime
from flask import current_app
from app.services.audit_service import log_audit
from app.extensions import db

def get_backup_dir():
    """Get or create non-public backup directory in instance_path."""
    backup_dir = os.path.join(current_app.instance_path, 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    return backup_dir

def get_json_data_dir():
    """Get path to active JSON data storage directory."""
    return current_app.config.get('JSON_DATA_DIR') or os.path.join(current_app.instance_path, 'data')

def create_database_backup(admin_id=None):
    """Safely snapshot the JSON storage files into instance/backups directory."""
    backup_dir = get_backup_dir()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"spl_backup_{timestamp}.json"
    dest_path = os.path.join(backup_dir, filename)

    data_dir = get_json_data_dir()
    tables_data = {}
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            if f.endswith('.json'):
                t_name = f[:-5]
                f_path = os.path.join(data_dir, f)
                try:
                    with open(f_path, 'r', encoding='utf-8') as jf:
                        tables_data[t_name] = json.load(jf)
                except Exception:
                    tables_data[t_name] = []

    backup_payload = {
        'version': '2.0-json',
        'timestamp': datetime.utcnow().isoformat(),
        'tables': tables_data
    }

    with open(dest_path, 'w', encoding='utf-8') as f:
        json.dump(backup_payload, f, indent=2, ensure_ascii=False)

    log_audit(admin_id, 'DATABASE_BACKUP_CREATED', 'System', None, None, f"Created backup: {filename}")
    return filename

def list_backups():
    """List available backups with file size and timestamp."""
    backup_dir = get_backup_dir()
    files = [f for f in os.listdir(backup_dir) if f.endswith('.json') or f.endswith('.db')]
    files.sort(reverse=True)

    backups = []
    for f in files:
        full_path = os.path.join(backup_dir, f)
        stat = os.stat(full_path)
        backups.append({
            'filename': f,
            'size_bytes': stat.st_size,
            'size_kb': round(stat.st_size / 1024, 1),
            'created_at': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
        })
    return backups

def restore_database_backup(filename, admin_id=None, confirmation_reason=None):
    """Restore JSON storage from backup file safely after explicit admin confirmation."""
    if not confirmation_reason or not confirmation_reason.strip():
        raise ValueError("Confirmation reason is required to restore database backup.")

    backup_dir = get_backup_dir()
    backup_path = os.path.join(backup_dir, filename)
    if not os.path.exists(backup_path):
        raise ValueError(f"Backup file '{filename}' does not exist.")

    data_dir = get_json_data_dir()
    os.makedirs(data_dir, exist_ok=True)

    # Create safety snapshot before overwriting
    create_database_backup(admin_id)

    if filename.endswith('.json'):
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_payload = json.load(f)

        tables = backup_payload.get('tables', {})
        for t_name, rows in tables.items():
            t_path = os.path.join(data_dir, f"{t_name}.json")
            db.engine._atomic_write_json(t_path, rows)

        # Clear in-memory caches and reload
        db.engine._tables.clear()
        db.engine._dirty_tables.clear()
        db.engine._max_ids.clear()
        db.session._identity_map.clear()
        db.create_all()
    elif filename.endswith('.db'):
        # Legacy SQLite backup migration fallback
        import sqlite3
        conn = sqlite3.connect(backup_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cur.fetchall() if not r[0].startswith('sqlite_')]
        for t in tables:
            cur.execute(f"SELECT * FROM {t};")
            rows = [dict(r) for r in cur.fetchall()]
            t_path = os.path.join(data_dir, f"{t}.json")
            db.engine._atomic_write_json(t_path, rows)
        conn.close()
        db.engine._tables.clear()
        db.engine._dirty_tables.clear()
        db.session._identity_map.clear()
        db.create_all()

    log_audit(admin_id, 'DATABASE_RESTORED', 'System', None, None, f"Restored from {filename}. Reason: {confirmation_reason}")
    return True
