CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    player_name  TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS builds (
    session_id    UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    player_class  TEXT,
    stats         JSONB,
    weapons       JSONB NOT NULL DEFAULT '[]',
    talismans     JSONB NOT NULL DEFAULT '[]',
    spirit_ash    TEXT,
    target_bosses JSONB NOT NULL DEFAULT '[]',
    playstyle     TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
