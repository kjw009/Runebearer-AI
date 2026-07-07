from typing import Any


def json_default(obj: Any) -> Any:
    """
    Fallback serializer for json.dumps(..., default=json_default).

    Handles Pydantic model instances (BuildStats, WeaponSlot, Citation, ...)
    by converting them to plain dicts, instead of json.dumps's usual
    default=str fallback — str(a_pydantic_model) produces its repr
    ("vigor=30 mind=10 ..."), which is not valid JSON structure and can't be
    round-tripped back into a dict/model on the other end.
    """
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return str(obj)
