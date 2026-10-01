import os
from datetime import datetime
from app.storage.expressions import FieldExpression

_MODEL_REGISTRY = {}
_TABLE_REGISTRY = {}

class ColumnType:
    pass

class Integer(ColumnType):
    pass

class Float(ColumnType):
    pass

class Boolean(ColumnType):
    pass

class String(ColumnType):
    def __init__(self, length=None):
        self.length = length

class Text(ColumnType):
    pass

class DateTime(ColumnType):
    pass

class ForeignKey:
    def __init__(self, target):
        self.target = target  # e.g. 'franchises.id' or 'players.id'

class Column:
    def __init__(self, col_type=None, *args, primary_key=False, unique=False, nullable=True, default=None, onupdate=None, index=False, **kwargs):
        self.type = col_type
        self.primary_key = primary_key
        self.unique = unique
        self.nullable = nullable
        self.default = default
        self.onupdate = onupdate
        self.index = index
        self.name = None
        self.model_class = None

        # Check if ForeignKey passed in args
        self.foreign_key = None
        for a in args:
            if isinstance(a, ForeignKey):
                self.foreign_key = a

    def __set_name__(self, owner, name):
        self.name = name
        self.model_class = owner

    def __get__(self, instance, owner):
        if instance is None:
            # Accessed on class -> return FieldExpression for queries
            expr = FieldExpression(self.name, model_class=owner)
            return expr
        return instance.__dict__.get(self.name)

    def __set__(self, instance, value):
        instance.__dict__[self.name] = value

    def __eq__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) == other

    def __ne__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) != other

    def __lt__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) < other

    def __le__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) <= other

    def __gt__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) > other

    def __ge__(self, other):
        return FieldExpression(self.name, model_class=self.model_class) >= other

    def ilike(self, pattern):
        return FieldExpression(self.name, model_class=self.model_class).ilike(pattern)

    def in_(self, values):
        return FieldExpression(self.name, model_class=self.model_class).in_(values)

    def asc(self):
        return FieldExpression(self.name, model_class=self.model_class).asc()

    def desc(self):
        return FieldExpression(self.name, model_class=self.model_class).desc()

class Relationship:
    def __init__(self, target_model, foreign_keys=None, back_populates=None, lazy=None):
        self.target_model_name = target_model if isinstance(target_model, str) else getattr(target_model, '__name__', str(target_model))
        self.foreign_keys = foreign_keys
        self.back_populates = back_populates
        self.lazy = lazy
        self.name = None
        self.owner_class = None

    def __set_name__(self, owner, name):
        self.name = name
        self.owner_class = owner

    def _resolve_target_class(self):
        target_cls = _MODEL_REGISTRY.get(self.target_model_name)
        if not target_cls:
            # Try fuzzy lookup
            for k, v in _MODEL_REGISTRY.items():
                if k.lower() == self.target_model_name.lower():
                    return v
        return target_cls

    def _resolve_fk_name(self, instance):
        if self.foreign_keys:
            fk_spec = self.foreign_keys
            if isinstance(fk_spec, list) and len(fk_spec) > 0:
                fk_spec = fk_spec[0]
            if isinstance(fk_spec, Column):
                return fk_spec.name
            if isinstance(fk_spec, str):
                if '.' in fk_spec:
                    return fk_spec.split('.')[-1]
                return fk_spec

        # Default heuristics based on target model name or relation name
        candidates = [
            f"{self.name}_id",
            f"{self.target_model_name.lower()}_id",
        ]
        if self.target_model_name.lower() == 'franchise':
            candidates.append('sold_to')

        for c in candidates:
            if c in instance.__dict__ or hasattr(self.owner_class, c):
                return c
        return None

    def __get__(self, instance, owner):
        if instance is None:
            return self

        target_cls = self._resolve_target_class()
        if not target_cls:
            return None

        # 1. Dynamic relationship (e.g. Franchise.sold_players, Franchise.users)
        if self.lazy == 'dynamic':
            # Find the foreign key attribute in target_cls that points to owner_class
            fk_name = None
            if self.foreign_keys:
                fk_spec = self.foreign_keys
                if isinstance(fk_spec, str):
                    fk_name = fk_spec.split('.')[-1]
                elif hasattr(fk_spec, 'name'):
                    fk_name = fk_spec.name

            if not fk_name:
                # Look for columns in target_cls referencing owner table
                owner_table = getattr(self.owner_class, '__tablename__', '')
                for col_name, col in getattr(target_cls, '_columns', {}).items():
                    if col.foreign_key and col.foreign_key.target.startswith(f"{owner_table}."):
                        fk_name = col_name
                        break

            if not fk_name:
                candidates = [f"{owner.__name__.lower()}_id"]
                if owner.__name__.lower() == 'franchise':
                    candidates.append('sold_to')
                for c in candidates:
                    if hasattr(target_cls, c):
                        fk_name = c
                        break

            if fk_name:
                return target_cls.query.filter_by(**{fk_name: instance.id})
            return target_cls.query.filter_by(id=-1)

        # 2. Standard Many-to-One / One-to-One lookup
        fk_name = self._resolve_fk_name(instance)
        if fk_name:
            fk_val = getattr(instance, fk_name, None)
            if fk_val is not None:
                return target_cls.query.get(fk_val)

        return None

    def __set__(self, instance, value):
        fk_name = self._resolve_fk_name(instance)
        if fk_name:
            if value is not None:
                setattr(instance, fk_name, getattr(value, 'id', None))
            else:
                setattr(instance, fk_name, None)

class ModelMeta(type):
    def __new__(mcls, name, bases, attrs):
        columns = {}
        for k, v in list(attrs.items()):
            if isinstance(v, Column):
                v.name = k
                columns[k] = v
            elif isinstance(v, Relationship):
                v.name = k

        cls = super().__new__(mcls, name, bases, attrs)
        cls._columns = columns
        for c in columns.values():
            c.model_class = cls

        if name != 'JsonModel':
            _MODEL_REGISTRY[name] = cls
            table_name = attrs.get('__tablename__')
            if table_name:
                _TABLE_REGISTRY[table_name] = cls

        return cls

class classproperty:
    def __init__(self, fget):
        self.fget = fget
    def __get__(self, instance, owner):
        return self.fget(owner)

class JsonModel(metaclass=ModelMeta):
    __tablename__ = None

    def __init__(self, **kwargs):
        # Set all defined columns to default or kwargs
        for col_name, col in self._columns.items():
            if col_name in kwargs:
                setattr(self, col_name, kwargs[col_name])
            else:
                default_val = col.default
                if callable(default_val):
                    setattr(self, col_name, default_val())
                elif default_val is not None:
                    setattr(self, col_name, default_val)
                else:
                    setattr(self, col_name, None)

        # Set any extra kwargs
        for k, v in kwargs.items():
            if k not in self._columns:
                setattr(self, k, v)

    @classproperty
    def query(cls):
        from app.extensions import db
        return db.session.query(cls)

    def _apply_onupdate(self):
        for col_name, col in self._columns.items():
            if col.onupdate is not None:
                if callable(col.onupdate):
                    setattr(self, col_name, col.onupdate())
                else:
                    setattr(self, col_name, col.onupdate)

    def to_storage_dict(self):
        res = {}
        for col_name, col in self._columns.items():
            val = getattr(self, col_name, None)
            if isinstance(val, datetime):
                res[col_name] = val.isoformat()
            else:
                res[col_name] = val
        if 'id' not in res and hasattr(self, 'id'):
            res['id'] = self.id
        return res

    def to_dict(self):
        res = {}
        for col_name in self._columns:
            res[col_name] = getattr(self, col_name, None)
        return res

    @classmethod
    def from_dict(cls, data):
        inst = cls.__new__(cls)
        inst.__dict__ = {}
        for col_name, col in cls._columns.items():
            if col_name in data:
                val = data[col_name]
                if col.type is DateTime or (isinstance(col.type, type) and issubclass(col.type, DateTime)):
                    if isinstance(val, str) and val.strip():
                        try:
                            val = datetime.fromisoformat(val)
                        except Exception:
                            for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S.%f'):
                                try:
                                    val = datetime.strptime(val, fmt)
                                    break
                                except Exception:
                                    pass
                inst.__dict__[col_name] = val
            else:
                default_val = col.default
                if callable(default_val):
                    inst.__dict__[col_name] = default_val()
                elif default_val is not None:
                    inst.__dict__[col_name] = default_val
                else:
                    inst.__dict__[col_name] = None

        if 'id' in data and data['id'] is not None:
            inst.id = int(data['id'])
        return inst
