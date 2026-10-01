from datetime import datetime
from app.storage.expressions import BinaryExpression, OrderExpression, FieldExpression

class Query:
    def __init__(self, model_class, session, filters=None, orders=None, limit=None, offset=None, distinct_col=None, func_call=None):
        self.model_class = model_class
        self.session = session
        self.filters = list(filters or [])
        self.orders = list(orders or [])
        self._limit = limit
        self._offset = offset
        self._distinct = False
        self.distinct_col = distinct_col
        self.func_call = func_call

    def _clone(self):
        q = Query(
            self.model_class,
            self.session,
            filters=self.filters,
            orders=self.orders,
            limit=self._limit,
            offset=self._offset,
            distinct_col=self.distinct_col,
            func_call=self.func_call
        )
        q._distinct = self._distinct
        return q

    def filter(self, *criterion):
        q = self._clone()
        for c in criterion:
            if c is not None:
                q.filters.append(c)
        return q

    def filter_by(self, **kwargs):
        q = self._clone()
        for k, v in kwargs.items():
            q.filters.append(BinaryExpression(k, '==', v))
        return q

    def order_by(self, *criteria):
        q = self._clone()
        for c in criteria:
            if isinstance(c, OrderExpression):
                q.orders.append(c)
            elif isinstance(c, FieldExpression):
                q.orders.append(OrderExpression(c.name, ascending=True))
            elif hasattr(c, 'name'):
                q.orders.append(OrderExpression(c.name, ascending=True))
            elif isinstance(c, str):
                if c.startswith('-'):
                    q.orders.append(OrderExpression(c[1:], ascending=False))
                else:
                    q.orders.append(OrderExpression(c, ascending=True))
        return q

    def limit(self, n):
        q = self._clone()
        q._limit = int(n) if n is not None else None
        return q

    def offset(self, n):
        q = self._clone()
        q._offset = int(n) if n is not None else None
        return q

    def distinct(self):
        q = self._clone()
        q._distinct = True
        return q

    def _execute_filter(self):
        # Fetch all instances of model_class from session
        instances = self.session.get_all_instances(self.model_class)
        # Apply filters
        for f in self.filters:
            if hasattr(f, 'evaluate'):
                instances = [inst for inst in instances if f.evaluate(inst)]
            elif callable(f):
                instances = [inst for inst in instances if f(inst)]
            elif bool(f) is False:
                return []

        # Apply orders (stable sort from last to first)
        if self.orders:
            for order in reversed(self.orders):
                field = order.field_name
                def make_key(f_name):
                    def key_fn(obj):
                        v = getattr(obj, f_name, None)
                        if v is None:
                            return (1, 0, "")
                        if isinstance(v, (int, float)):
                            return (0, v, "")
                        if isinstance(v, datetime):
                            return (0, v.timestamp(), "")
                        return (0, 0, str(v).lower())
                    return key_fn
                instances.sort(key=make_key(field), reverse=not order.ascending)

        return instances

    def all(self):
        if self.func_call:
            val = self.scalar()
            return [val] if val is not None else []

        # If this is a column-level distinct query, e.g. AuditLog.action
        if self.distinct_col:
            instances = self._execute_filter()
            col_name = self.distinct_col.name if hasattr(self.distinct_col, 'name') else str(self.distinct_col)
            vals = []
            seen = set()
            for inst in instances:
                v = getattr(inst, col_name, None)
                if self._distinct:
                    if v not in seen:
                        seen.add(v)
                        vals.append((v,))
                else:
                    vals.append((v,))
            if self._offset:
                vals = vals[self._offset:]
            if self._limit is not None:
                vals = vals[:self._limit]
            return vals

        instances = self._execute_filter()

        if self._distinct:
            seen_ids = set()
            unique_instances = []
            for inst in instances:
                if inst.id not in seen_ids:
                    seen_ids.add(inst.id)
                    unique_instances.append(inst)
            instances = unique_instances

        if self._offset:
            instances = instances[self._offset:]
        if self._limit is not None:
            instances = instances[:self._limit]

        return instances

    def first(self):
        results = self.limit(1).all()
        return results[0] if results else None

    def count(self):
        instances = self._execute_filter()
        if self._distinct:
            seen_ids = set()
            cnt = 0
            for inst in instances:
                if inst.id not in seen_ids:
                    seen_ids.add(inst.id)
                    cnt += 1
            return cnt
        return len(instances)

    def get(self, pk):
        try:
            pk = int(pk)
        except (ValueError, TypeError):
            return None
        return self.session.get(self.model_class, pk)

    def get_or_404(self, pk):
        inst = self.get(pk)
        if not inst:
            from flask import abort
            abort(404)
        return inst

    def delete(self):
        """Delete all matching instances from the session. Returns count deleted."""
        instances = self._execute_filter()
        count = len(instances)
        for inst in instances:
            self.session.delete(inst)
        return count

    def scalar(self):
        if not self.func_call:
            first_item = self.first()
            return first_item

        fn_type, col = self.func_call
        col_name = col.name if hasattr(col, 'name') else str(col)
        instances = self._execute_filter()
        values = [getattr(inst, col_name, None) for inst in instances]
        valid_values = [v for v in values if v is not None]

        if fn_type == 'max':
            return max(valid_values) if valid_values else None
        elif fn_type == 'min':
            return min(valid_values) if valid_values else None
        elif fn_type == 'sum':
            return sum(valid_values) if valid_values else 0.0
        elif fn_type == 'count':
            return len(valid_values)
        return None

    def __iter__(self):
        return iter(self.all())

    def __len__(self):
        return self.count()

    def __getitem__(self, item):
        if isinstance(item, slice):
            start = item.start or 0
            stop = item.stop
            q = self._clone()
            if start:
                q = q.offset(start)
            if stop is not None:
                q = q.limit(stop - start)
            return q.all()
        elif isinstance(item, int):
            all_items = self.all()
            return all_items[item]
        raise TypeError(f"Invalid query index: {type(item)}")

    def __repr__(self):
        return f"<Query {getattr(self.model_class, '__name__', 'Unknown')} filters={len(self.filters)}>"
