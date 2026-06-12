from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


class DecimalText(TypeDecorator):
    """Store a Decimal exactly as TEXT.

    SQLite has no exact decimal type; SQLAlchemy's Numeric round-trips through
    float there, which would corrupt money. Storing the canonical string keeps
    Decimal values exact across write/read.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, Decimal):
            value = Decimal(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"corrupt DecimalText value in database: {value!r}") from exc
