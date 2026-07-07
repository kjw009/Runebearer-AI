from app.graph.state import BuildState

def build_state_to_summary(state: BuildState) -> str:
    """
    Converts the current state dictionary into a highly structured, token-efficient
    multi-line summary string for the Grace Supervisor Node to read.
    
    Defensively handles missing keys, uninitialized nested schemas, optional 
    Pydantic status objects, and dynamic weapon tracking slots.
    """
    
    # -------------------------------------------------------------------------
    # 1. Onboarding & Player Profile Section (Safely nested TypedDict handling)
    # -------------------------------------------------------------------------
    onboarding_status = "COMPLETED" if state.get("onboarding_completed") else "INCOMPLETE"
    profile = state.get("player_profile") or {}
    
    exp_level = profile.get("experience_level", "Unset")
    skill_confidence= profile.get("skill_confidence", "Unset")
    preferred_archetype = profile.get("preferred_archetype", "Unset")
    current_hurdle = profile.get("current_hurdle", "Unset")
    playstyle = state.get("playstyle", "Unset")
    
    onboarding_line = f"Onboarding: {onboarding_status}"
    if onboarding_status == "COMPLETED":
        onboarding_line += f" (Exp: {exp_level}, Skill: {skill_confidence}, Preferred Archetype: {preferred_archetype})"
    if current_hurdle is not None:
        onboarding_line += f" (Current Hurdle: {current_hurdle})"

    # -------------------------------------------------------------------------
    # 2. Stats Section (Handles Optional[BuildStats] Pydantic Model)
    # -------------------------------------------------------------------------
    stats_model = state.get("stats")
    stats_list = []
    
    if stats_model is not None:
        # Coerce Pydantic models (v1 or v2 layouts) safely into a working dictionary
        if hasattr(stats_model, "model_dump"):
            stats_dict = stats_model.model_dump()
        elif hasattr(stats_model, "dict"):
            stats_dict = stats_model.dict()
        else:
            stats_dict = dict(stats_model) if isinstance(stats_model, dict) else {}
            
        stat_keys = ["vigor", "mind", "endurance", "strength", "dexterity", "intelligence", "faith", "arcane"]
        for key in stat_keys:
            val = stats_dict.get(key)
            if val is not None:
                stats_list.append(f"{key[:2].upper()}:{val}")
                
        stats_str = ", ".join(stats_list) if stats_list else "None allocated"
    else:
        stats_str = "Not Initialized"

    # -------------------------------------------------------------------------
    # 3. Gear & Armory Section (Handles list[WeaponSlot] Pydantic array)
    # -------------------------------------------------------------------------
    player_class = state.get("player_class") or "Unset"
    level = state.get("current_level") or "Unset"
    talismans = state.get("talismans") or []
    
    raw_weapons = state.get("weapons") or []
    weapons_list = []
    
    for slot in raw_weapons:
        if slot is not None:
            # Check if it's an instantiated Pydantic object
            if hasattr(slot, "name"):
                w_name = slot.name
                w_level = f"+{slot.upgrade_level}" if slot.upgrade_level > 0 else ""
                w_aff = f" ({slot.affinity})" if slot.affinity else ""
                weapons_list.append(f"{w_name}{w_level}{w_aff}")
            # Fallback dictionary parser check
            elif isinstance(slot, dict):
                w_name = slot.get("name", "Unknown Weapon")
                w_lvl_num = slot.get("upgrade_level", 0)
                w_level = f"+{w_lvl_num}" if w_lvl_num > 0 else ""
                w_aff = f" ({slot.get('affinity')})" if slot.get("affinity") else ""
                weapons_list.append(f"{w_name}{w_level}{w_aff}")
            else:
                weapons_list.append(str(slot))

    weapons_str = ", ".join(weapons_list) if weapons_list else "None"
    talismans_str = ", ".join(talismans) if talismans else "None"

    build_line = (
        f"Build: Class: {player_class} | Lvl: {level} | Style: {playstyle}\n"
        f"       Stats: [{stats_str}]\n"
        f"       Gear: Weapons: ({weapons_str}) | Talismans: ({talismans_str})"
    )

    # -------------------------------------------------------------------------
    # 4. History Tracking & Execution Progress Loops
    # -------------------------------------------------------------------------
    agent_responses = state.get("agent_responses") or {}
    history_experts = list(agent_responses.keys())
    progress_str = ", ".join(history_experts) if history_experts else "None yet"

    intent_list = state.get("intent") or []
    intent_str = ", ".join(intent_list) if intent_list else "Not yet classified"

    queue_list = state.get("intent_queue") or []
    queue_str = ", ".join(queue_list) if queue_list else "Empty"

    progress_line = (
        f"Progress Check:\n"
        f"       Original Classified Intent (do not alter): [{intent_str}]\n"
        f"       Historical Responses: [{progress_str}]\n"
        f"       Active Execution Queue remaining: [{queue_str}]"
    )

    # Combine sections into the final clean, scannable string
    return f"{onboarding_line}\n{build_line}\n{progress_line}"