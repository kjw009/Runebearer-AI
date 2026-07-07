-- Migration: Add onboarding/player-profile fields to the builds table.
-- These live alongside the rest of the persistent build fields (player_class,
-- stats, weapons, ...) since BuildRepository loads/persists all of them as one
-- flat build_state dict for GraphRunner. intent/intent_queue/agent_responses are
-- deliberately NOT persisted here — they're turn-scoped LangGraph working state
-- that GraphRunner.run() always re-initialises fresh on every query, never reads
-- back from storage.
ALTER TABLE builds
ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS player_profile JSONB NOT NULL DEFAULT '{}',
ADD COLUMN IF NOT EXISTS current_level INTEGER NOT NULL DEFAULT 1;
