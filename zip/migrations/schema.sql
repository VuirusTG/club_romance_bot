CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER NOT NULL UNIQUE,
    username VARCHAR(255),
    first_name VARCHAR(255),
    language VARCHAR(10) NOT NULL DEFAULT 'ru',
    spoiler_level INTEGER NOT NULL DEFAULT 0,
    notifications_enabled BOOLEAN NOT NULL DEFAULT 1,
    last_active_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    slug VARCHAR(120) NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    genre VARCHAR(255),
    status VARCHAR(100) NOT NULL DEFAULT 'ongoing',
    cover_file_id VARCHAR(255),
    guide_source_name VARCHAR(255),
    guide_source_url VARCHAR(500),
    is_published BOOLEAN NOT NULL DEFAULT 1,
    views_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY,
    story_id INTEGER NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title VARCHAR(255),
    description TEXT NOT NULL DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(story_id, number)
);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    number INTEGER NOT NULL,
    title VARCHAR(255),
    summary TEXT NOT NULL DEFAULT '',
    guide_intro TEXT NOT NULL DEFAULT '',
    guide_source_name VARCHAR(255),
    guide_source_url VARCHAR(500),
    image_file_id VARCHAR(255),
    is_published BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(season_id, number)
);

CREATE TABLE IF NOT EXISTS choices (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    order_index INTEGER NOT NULL DEFAULT 0,
    scene_title VARCHAR(255),
    text TEXT NOT NULL,
    recommended_option TEXT NOT NULL,
    cost_diamonds INTEGER NOT NULL DEFAULT 0,
    consequence TEXT NOT NULL DEFAULT '',
    requirements TEXT NOT NULL DEFAULT '',
    parameter_changes TEXT NOT NULL DEFAULT '',
    character_effects TEXT NOT NULL DEFAULT '',
    future_effects TEXT NOT NULL DEFAULT '',
    tags VARCHAR(255) NOT NULL DEFAULT '',
    spoiler_level INTEGER NOT NULL DEFAULT 1,
    is_critical BOOLEAN NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS updates (
    id INTEGER PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source_name VARCHAR(255),
    source_url VARCHAR(500),
    game_version VARCHAR(50),
    image_file_id VARCHAR(255),
    is_published BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
