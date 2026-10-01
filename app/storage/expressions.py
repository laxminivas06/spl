import re
from datetime import datetime

class BaseExpression:
    def __or__(self, other):
        return OrExpression(self, other)

    def __and__(self, other):
        return AndExpression(self, other)

    def __invert__(self):
        return NotExpression(self)

    def evaluate(self, obj):
        raise NotImplementedError

class FieldExpression(BaseExpression):
    def __init__(self, name, model_class=None):
        self.name = name
        self.model_class = model_class

    def __eq__(self, other):
        return BinaryExpression(self.name, '==', other)

    def __ne__(self, other):
        return BinaryExpression(self.name, '!=', other)

    def __lt__(self, other):
        return BinaryExpression(self.name, '<', other)

    def __le__(self, other):
        return BinaryExpression(self.name, '<=', other)

    def __gt__(self, other):
        return BinaryExpression(self.name, '>', other)

    def __ge__(self, other):
        return BinaryExpression(self.name, '>=', other)

    def ilike(self, pattern):
        return BinaryExpression(self.name, 'ilike', pattern)

    def in_(self, values):
        return BinaryExpression(self.name, 'in', values)

    def is_(self, other):
        return BinaryExpression(self.name, '==', other)

    def isnot(self, other):
        return BinaryExpression(self.name, '!=', other)

    def is_not(self, other):
        return BinaryExpression(self.name, '!=', other)

    def asc(self):
        return OrderExpression(self.name, ascending=True)

    def desc(self):
        return OrderExpression(self.name, ascending=False)

    def evaluate(self, obj):
        return bool(getattr(obj, self.name, None))

    def __repr__(self):
        return f"<FieldExpression {self.name}>"

class OrderExpression:
    def __init__(self, field_name, ascending=True):
        self.field_name = field_name
        self.ascending = ascending

    def __repr__(self):
        return f"<OrderExpression {self.field_name} {'ASC' if self.ascending else 'DESC'}>"

class BinaryExpression(BaseExpression):
    def __init__(self, field_name, op, value):
        self.field_name = field_name
        self.op = op
        self.value = value

    def evaluate(self, obj):
        val = getattr(obj, self.field_name, None)
        target = self.value

        # Handle null/None checks
        if target is None:
            if self.op == '==':
                return val is None
            elif self.op == '!=':
                return val is not None
            elif self.op in ('<', '<=', '>', '>='):
                return False

        if val is None:
            if self.op == '==':
                return target is None
            elif self.op == '!=':
                return target is not None
            elif self.op in ('<', '<=', '>', '>='):
                return False
            elif self.op == 'ilike':
                return False
            elif self.op == 'in':
                return False

        # DateTime comparisons if one is datetime and other is str
        if isinstance(val, datetime) and isinstance(target, str):
            try:
                target = datetime.fromisoformat(target)
            except Exception:
                pass
        elif isinstance(target, datetime) and isinstance(val, str):
            try:
                val = datetime.fromisoformat(val)
            except Exception:
                pass

        if self.op == '==':
            if isinstance(val, str) and isinstance(target, str):
                return val == target
            return val == target
        elif self.op == '!=':
            return val != target
        elif self.op == '<':
            try:
                return val < target
            except TypeError:
                return False
        elif self.op == '<=':
            try:
                return val <= target
            except TypeError:
                return False
        elif self.op == '>':
            try:
                return val > target
            except TypeError:
                return False
        elif self.op == '>=':
            try:
                return val >= target
            except TypeError:
                return False
        elif self.op == 'in':
            try:
                return val in target
            except TypeError:
                return False
        elif self.op == 'ilike':
            pat = str(target)
            val_str = str(val)
            parts = []
            for c in pat:
                if c == '%':
                    parts.append('.*')
                elif c == '_':
                    parts.append('.')
                else:
                    parts.append(re.escape(c))
            reg = '^' + ''.join(parts) + '$'
            return bool(re.match(reg, val_str, re.IGNORECASE | re.DOTALL))

        return False

    def __repr__(self):
        return f"<BinaryExpression {self.field_name} {self.op} {repr(self.value)}>"

class OrExpression(BaseExpression):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def evaluate(self, obj):
        left_res = self.left.evaluate(obj) if hasattr(self.left, 'evaluate') else bool(self.left)
        if left_res:
            return True
        return self.right.evaluate(obj) if hasattr(self.right, 'evaluate') else bool(self.right)

    def __repr__(self):
        return f"({self.left} | {self.right})"

class AndExpression(BaseExpression):
    def __init__(self, left, right):
        self.left = left
        self.right = right

    def evaluate(self, obj):
        left_res = self.left.evaluate(obj) if hasattr(self.left, 'evaluate') else bool(self.left)
        if not left_res:
            return False
        return self.right.evaluate(obj) if hasattr(self.right, 'evaluate') else bool(self.right)

    def __repr__(self):
        return f"({self.left} & {self.right})"

class NotExpression(BaseExpression):
    def __init__(self, expr):
        self.expr = expr

    def evaluate(self, obj):
        res = self.expr.evaluate(obj) if hasattr(self.expr, 'evaluate') else bool(self.expr)
        return not res

    def __repr__(self):
        return f"(~{self.expr})"
