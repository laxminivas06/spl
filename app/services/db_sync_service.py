from app.extensions import db

def sync_database_schema(app=None):
    """
    Ensures all JSON storage table files exist and are ready.
    In JSON-based storage, new fields are automatically populated with defaults
    during deserialization, eliminating traditional SQL schema migration steps.
    """
    if app:
        with app.app_context():
            _do_sync()
    else:
        _do_sync()

def _do_sync():
    try:
        db.create_all()
    except Exception as e:
        print(f"[JSON Storage] Warning during schema check: {e}")
