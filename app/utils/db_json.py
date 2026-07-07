import json
from typing import Any


def parse_jsonb(value: Any) -> Any:
    """
    Normalizes a JSONB column's value into a native Python object.

    asyncpg does not decode json/jsonb columns by default — it hands back the
    raw JSON text as a str unless a type codec is registered on the connection
    (the same category of problem VectorRepository solves for the vector type
    via register_vector()). This makes reading a JSONB column safe regardless
    of whether that registration exists: an already-decoded value (dict, list,
    None) passes through untouched, and a str gets json.loads'd.

    Deliberately does not catch json.JSONDecodeError — a parse failure here
    means our own previously-persisted data is malformed, which is a real bug
    worth surfacing loudly rather than silently degrading into a default.
    """
    if value is None or not isinstance(value, str):
        return value
    return json.loads(value)


def parse_jsonb_fields(row: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Returns a copy of row with each of the named fields passed through parse_jsonb."""
    parsed = dict(row)
    for field in fields:
        if field in parsed:
            parsed[field] = parse_jsonb(parsed[field])
    return parsed
