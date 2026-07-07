import json

from app.graph.state import BuildState


def build_state_to_json(state: BuildState) -> str:
    """
    Serializes the player-facing build fields into a JSON string for the
    {build_state_json} placeholder shared by all 5 specialist prompts.

    experience_level/skill_confidence are flattened up from player_profile
    rather than left nested, since every specialist prompt reads them as
    top-level keys (e.g. "if 'experience_level' is 'total_beginner'").
    """
    stats = state.get("stats")
    weapons = state.get("weapons") or []
    profile = state.get("player_profile") or {}

    payload = {
        "player_class": state.get("player_class"),
        "current_level": state.get("current_level"),
        "stats": stats.model_dump() if stats is not None else None,
        "weapons": [w.model_dump() if hasattr(w, "model_dump") else w for w in weapons],
        "talismans": state.get("talismans") or [],
        "spirit_ash": state.get("spirit_ash"),
        "target_bosses": state.get("target_bosses") or [],
        "playstyle": state.get("playstyle"),
        "experience_level": profile.get("experience_level"),
        "skill_confidence": profile.get("skill_confidence"),
    }
    return json.dumps(payload, indent=2)
