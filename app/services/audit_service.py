from flask import request
from app.extensions import db
from app.models import AuditLog

def log_audit(admin_id, action, target_type=None, target_id=None, old_value=None, new_value=None, status='SUCCESS', franchise_id=None, ip_address=None):
    """Utility function to create audit log records for admin and security actions."""
    try:
        if ip_address is None and request:
            try:
                ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
            except RuntimeError:
                ip_address = None

        log = AuditLog(
            admin_id=admin_id,
            franchise_id=franchise_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            status=status,
            ip_address=ip_address,
            old_value=str(old_value) if old_value is not None else None,
            new_value=str(new_value) if new_value is not None else None
        )
        db.session.add(log)
        db.session.commit()
        return log
    except Exception as e:
        db.session.rollback()
        print(f"Failed to write audit log: {e}")
        return None
