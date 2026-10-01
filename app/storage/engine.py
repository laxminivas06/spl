import os
import json
import tempfile
import threading
from datetime import datetime

class JSONEngine:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir
        self._lock = threading.RLock()
        self._tables = {}  # table_name -> dict of id -> record_dict
        self._dirty_tables = set()
        self._max_ids = {}  # table_name -> int

    def set_data_dir(self, data_dir):
        with self._lock:
            self.data_dir = data_dir
            if self.data_dir:
                os.makedirs(self.data_dir, exist_ok=True)
            self._tables.clear()
            self._dirty_tables.clear()
            self._max_ids.clear()

    def _get_table_path(self, table_name):
        if not self.data_dir:
            raise RuntimeError("JSON data directory is not set.")
        return os.path.join(self.data_dir, f"{table_name}.json")

    def ensure_table(self, table_name):
        with self._lock:
            if not self.data_dir:
                return
            os.makedirs(self.data_dir, exist_ok=True)
            path = self._get_table_path(table_name)
            if not os.path.exists(path):
                self._atomic_write_json(path, [])
            if table_name not in self._tables:
                self._load_table(table_name)

    def _load_table(self, table_name):
        path = self._get_table_path(table_name)
        records_map = {}
        max_id = 0
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if isinstance(data, list):
                            for item in data:
                                if isinstance(item, dict) and 'id' in item and item['id'] is not None:
                                    rec_id = int(item['id'])
                                    records_map[rec_id] = item
                                    if rec_id > max_id:
                                        max_id = rec_id
            except Exception as e:
                print(f"[JSONEngine] Error reading {path}: {e}")

        self._tables[table_name] = records_map
        self._max_ids[table_name] = max_id

    def get_records(self, table_name):
        with self._lock:
            if table_name not in self._tables:
                self._load_table(table_name)
            return list(self._tables[table_name].values())

    def get_record(self, table_name, record_id):
        with self._lock:
            if table_name not in self._tables:
                self._load_table(table_name)
            return self._tables[table_name].get(int(record_id))

    def get_next_id(self, table_name):
        with self._lock:
            if table_name not in self._max_ids:
                self._load_table(table_name)
            next_id = self._max_ids[table_name] + 1
            self._max_ids[table_name] = next_id
            return next_id

    def set_record(self, table_name, record_dict):
        with self._lock:
            if table_name not in self._tables:
                self._load_table(table_name)

            rec_id = record_dict.get('id')
            if rec_id is None:
                rec_id = self.get_next_id(table_name)
                record_dict['id'] = rec_id
            else:
                rec_id = int(rec_id)
                record_dict['id'] = rec_id
                if rec_id > self._max_ids.get(table_name, 0):
                    self._max_ids[table_name] = rec_id

            self._tables[table_name][rec_id] = record_dict
            self._dirty_tables.add(table_name)
            return rec_id

    def delete_record(self, table_name, record_id):
        with self._lock:
            if table_name not in self._tables:
                self._load_table(table_name)
            rec_id = int(record_id)
            if rec_id in self._tables[table_name]:
                del self._tables[table_name][rec_id]
                self._dirty_tables.add(table_name)

    def commit(self):
        with self._lock:
            for table_name in list(self._dirty_tables):
                path = self._get_table_path(table_name)
                # Sort records by id for stable JSON files
                records = sorted(self._tables[table_name].values(), key=lambda r: r.get('id', 0))
                self._atomic_write_json(path, records)
            self._dirty_tables.clear()

    def rollback(self):
        with self._lock:
            # Reload all dirty tables from disk
            for table_name in self._dirty_tables:
                self._load_table(table_name)
            self._dirty_tables.clear()

    def clear_all(self, table_names=None):
        with self._lock:
            if table_names is None:
                table_names = list(self._tables.keys())
            for table_name in table_names:
                self._tables[table_name] = {}
                self._max_ids[table_name] = 0
                path = self._get_table_path(table_name)
                self._atomic_write_json(path, [])
            self._dirty_tables.clear()

    def _atomic_write_json(self, target_path, data):
        dir_name = os.path.dirname(target_path)
        os.makedirs(dir_name, exist_ok=True)
        # Write to temporary file in same directory then rename atomically
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding='utf-8') as tf:
            json.dump(data, tf, indent=2, ensure_ascii=False, default=str)
            tf.flush()
            os.fsync(tf.fileno())
            temp_path = tf.name

        os.replace(temp_path, target_path)
