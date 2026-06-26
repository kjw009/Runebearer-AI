from typing import Optional

from pydantic import BaseModel, Field

from app.graph.state import BuildStats, WeaponSlot


class BuildStateResponse(BaseModel):
    player_class: Optional[str] = None
    stats: Optional[BuildStats] = None
    weapons: list[WeaponSlot] = Field(default_factory=list)
    talismans: list[str] = Field(default_factory=list)
    spirit_ash: Optional[str] = None
    target_bosses: list[str] = Field(default_factory=list)
    playstyle: Optional[str] = None


class BuildStateUpdate(BaseModel):
    player_class: Optional[str] = None
    stats: Optional[BuildStats] = None
    weapons: Optional[list[WeaponSlot]] = None
    talismans: Optional[list[str]] = None
    spirit_ash: Optional[str] = None
    target_bosses: Optional[list[str]] = None
    playstyle: Optional[str] = None
