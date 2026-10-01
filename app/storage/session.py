import threading

class Session:
    def __init__(self, engine):
        self.engine = engine
        self._lock = threading.RLock()
        self._identity_map = {}  # (table_name, id) -> instance
        self._staged_new = set()
        self._staged_delete = set()

    def add(self, instance):
        with self._lock:
            table_name = getattr(instance, '__tablename__', None)
            if not table_name:
                raise ValueError("Cannot add instance without __tablename__.")

            if instance in self._staged_delete:
                self._staged_delete.remove(instance)

            # Assign ID if not assigned yet
            if getattr(instance, 'id', None) is None:
                instance.id = self.engine.get_next_id(table_name)

            self._identity_map[(table_name, instance.id)] = instance
            self._staged_new.add(instance)

    def add_all(self, instances):
        with self._lock:
            for inst in instances:
                self.add(inst)

    def delete(self, instance):
        with self._lock:
            table_name = getattr(instance, '__tablename__', None)
            if not table_name:
                return

            if instance in self._staged_new:
                self._staged_new.remove(instance)

            self._staged_delete.add(instance)
            inst_id = getattr(instance, 'id', None)
            if inst_id is not None:
                self._identity_map.pop((table_name, inst_id), None)
                self.engine.delete_record(table_name, inst_id)

    def flush(self):
        with self._lock:
            for inst in list(self._staged_new):
                table_name = inst.__tablename__
                if getattr(inst, 'id', None) is None:
                    inst.id = self.engine.get_next_id(table_name)
                self._identity_map[(table_name, inst.id)] = inst

    def commit(self):
        with self._lock:
            # 1. Process deletes
            for inst in list(self._staged_delete):
                table_name = inst.__tablename__
                if inst.id is not None:
                    self.engine.delete_record(table_name, inst.id)
            self._staged_delete.clear()

            # 2. Process all loaded or modified instances in identity map and staged_new
            all_instances = set(self._identity_map.values()) | self._staged_new
            for inst in all_instances:
                table_name = inst.__tablename__
                if inst in self._staged_delete:
                    continue
                if getattr(inst, 'id', None) is None:
                    inst.id = self.engine.get_next_id(table_name)
                # Apply onupdate if defined
                inst._apply_onupdate()
                record_dict = inst.to_storage_dict()
                self.engine.set_record(table_name, record_dict)
                self._identity_map[(table_name, inst.id)] = inst

            self._staged_new.clear()
            self.engine.commit()

    def rollback(self):
        with self._lock:
            # Remove any staged new items from identity map
            for inst in self._staged_new:
                table_name = inst.__tablename__
                if inst.id is not None:
                    self._identity_map.pop((table_name, inst.id), None)
            self._staged_new.clear()
            self._staged_delete.clear()
            # Reload dirty records from engine
            self.engine.rollback()
            # Clear identity map so next access reloads clean data
            self._identity_map.clear()

    def remove(self):
        with self._lock:
            self._staged_new.clear()
            self._staged_delete.clear()

    def get(self, model_class, pk):
        with self._lock:
            try:
                pk = int(pk)
            except (ValueError, TypeError):
                return None

            table_name = getattr(model_class, '__tablename__', None)
            if not table_name:
                return None

            # Check identity map first
            key = (table_name, pk)
            if key in self._identity_map:
                inst = self._identity_map[key]
                if inst not in self._staged_delete:
                    return inst
                return None

            # Look up in engine
            rec = self.engine.get_record(table_name, pk)
            if rec is None:
                return None

            inst = model_class.from_dict(rec)
            self._identity_map[key] = inst
            return inst

    def get_all_instances(self, model_class):
        with self._lock:
            table_name = getattr(model_class, '__tablename__', None)
            if not table_name:
                return []

            records = self.engine.get_records(table_name)
            result = []
            seen_ids = set()

            for rec in records:
                rec_id = int(rec.get('id', 0))
                key = (table_name, rec_id)
                if key in self._identity_map:
                    inst = self._identity_map[key]
                    if inst in self._staged_delete:
                        continue
                else:
                    inst = model_class.from_dict(rec)
                    self._identity_map[key] = inst

                seen_ids.add(rec_id)
                result.append(inst)

            # Include any staged_new not yet in engine
            for inst in self._staged_new:
                if isinstance(inst, model_class) and inst.id not in seen_ids and inst not in self._staged_delete:
                    result.append(inst)

            return result

    def query(self, *entities):
        if not entities:
            raise ValueError("Session.query() requires at least one entity.")

        entity = entities[0]
        # Check if entity is an AggregateFunc (max, sum, etc.)
        if hasattr(entity, 'func_name') and hasattr(entity, 'col'):
            model_cls = getattr(entity.col, 'model_class', None)
            from app.storage.query import Query
            return Query(model_cls, self, func_call=(entity.func_name, entity.col))

        # Check if entity is a column (for distinct column queries)
        if hasattr(entity, 'model_class') and entity.model_class is not None:
            from app.storage.query import Query
            return Query(entity.model_class, self, distinct_col=entity)

        # Standard Model query
        from app.storage.query import Query
        return Query(entity, self)

    def execute(self, stmt):
        class ResultWrapper:
            def __init__(self, val):
                self.val = val
            def scalar(self):
                return self.val

        if hasattr(stmt, 'scalar'):
            return ResultWrapper(stmt.scalar())
        elif hasattr(stmt, 'val'):
            return ResultWrapper(stmt.val)
        return ResultWrapper(1)
