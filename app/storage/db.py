import os
import sqlite3
from app.storage.engine import JSONEngine
from app.storage.session import Session
from app.storage.models import (
    JsonModel, Column, Integer, Float, Boolean, String, Text, DateTime,
    ForeignKey, Relationship, _TABLE_REGISTRY
)

class AggregateFunc:
    def __init__(self, func_name, col):
        self.func_name = func_name
        self.col = col

class DBFunc:
    def max(self, col):
        return AggregateFunc('max', col)

    def min(self, col):
        return AggregateFunc('min', col)

    def sum(self, col):
        return AggregateFunc('sum', col)

    def count(self, col):
        return AggregateFunc('count', col)

class SelectStatement:
    def __init__(self, val):
        self.val = val

    def scalar(self):
        return self.val

class JSONDB:
    def __init__(self, app=None):
        self.engine = JSONEngine()
        self.session = Session(self.engine)
        self.Model = JsonModel
        self.Column = Column
        self.Integer = Integer
        self.Float = Float
        self.Boolean = Boolean
        self.String = String
        self.Text = Text
        self.DateTime = DateTime
        self.ForeignKey = ForeignKey
        self.relationship = Relationship
        self.func = DBFunc()

        if app:
            self.init_app(app)

    def select(self, val):
        return SelectStatement(val)

    def init_app(self, app):
        data_dir = app.config.get('JSON_DATA_DIR')
        if not data_dir:
            data_dir = os.path.join(app.instance_path, 'data')

        os.makedirs(data_dir, exist_ok=True)
        self.engine.set_data_dir(data_dir)

        # One-time migration from legacy SQLite if it exists and JSON is unpopulated
        self._migrate_legacy_sqlite(app, data_dir)

        self.create_all()

        @app.teardown_appcontext
        def shutdown_session(exception=None):
            self.session.remove()

    def _migrate_legacy_sqlite(self, app, data_dir):
        # Look for existing SQLite DB to preserve existing data
        sqlite_paths = [
            os.path.join(app.instance_path, 'spl_auction.db'),
            os.path.join(app.root_path, '..', 'instance', 'spl_auction.db')
        ]
        sqlite_file = None
        for p in sqlite_paths:
            p_abs = os.path.abspath(p)
            if os.path.exists(p_abs) and os.path.getsize(p_abs) > 0:
                sqlite_file = p_abs
                break

        if not sqlite_file:
            return

        # Check if users.json already has data
        users_file = os.path.join(data_dir, 'users.json')
        if os.path.exists(users_file) and os.path.getsize(users_file) > 10:
            return

        print(f"[JSON Storage] Migrating existing data from {sqlite_file} to JSON files...")
        try:
            conn = sqlite3.connect(sqlite_file)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall() if not r[0].startswith('sqlite_')]

            for t in tables:
                cursor.execute(f"SELECT * FROM {t};")
                rows = [dict(row) for row in cursor.fetchall()]
                # Convert integer booleans or None appropriately
                target_json = os.path.join(data_dir, f"{t}.json")
                self.engine._atomic_write_json(target_json, rows)
                print(f"[JSON Storage] Migrated {len(rows)} records for '{t}' to {target_json}")

            conn.close()
            backup_sqlite = sqlite_file + ".migrated_backup"
            if not os.path.exists(backup_sqlite):
                os.rename(sqlite_file, backup_sqlite)
                print(f"[JSON Storage] Legacy SQLite file renamed to {backup_sqlite}")
        except Exception as e:
            print(f"[JSON Storage] Migration notice: {e}")

    def create_all(self):
        for table_name in _TABLE_REGISTRY.keys():
            self.engine.ensure_table(table_name)

    def drop_all(self):
        self.session.rollback()
        table_names = list(_TABLE_REGISTRY.keys())
        self.engine.clear_all(table_names)
