-- Prompt Library SQLite Schema
-- Local development / snapshot version of the canonical PostgreSQL schema

-- Prompt identifiers (stable concepts)
CREATE TABLE IF NOT EXISTS prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT NOT NULL UNIQUE,
    concept TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'active', 'deprecated', 'archived')),
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Prompt style profiles
CREATE TABLE IF NOT EXISTS prompt_style_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier TEXT NOT NULL UNIQUE,
    syntax_family TEXT NOT NULL CHECK (syntax_family IN ('everyday-speech', 'comma-separated', 'booru-tags', 'enhanced-prompt', 'lisp-like', 'structured-fields', 'natural_language', 'pony-booru')),
    negative_prompt_strategy TEXT NOT NULL DEFAULT 'minimal',
    ordering_notes TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Prompt templates (model-facing positive/negative prompt pairs)
CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    style_profile_id INTEGER NOT NULL REFERENCES prompt_style_profiles(id),
    positive_template TEXT NOT NULL,
    negative_template TEXT DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(prompt_id, style_profile_id)
);

-- Wildcard definitions (reusable vocabulary lists)
CREATE TABLE IF NOT EXISTS wildcard_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wildcard_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deprecated', 'archived')),
    notes TEXT,
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Wildcard values (individual entries per definition)
CREATE TABLE IF NOT EXISTS wildcard_values (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wildcard_definition_id INTEGER NOT NULL REFERENCES wildcard_definitions(id),
    value TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(wildcard_definition_id, value)
);

-- Prompt wildcard bindings (connect prompts to wildcards)
CREATE TABLE IF NOT EXISTS prompt_wildcard_bindings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    wildcard_definition_id INTEGER NOT NULL REFERENCES wildcard_definitions(id),
    required INTEGER NOT NULL DEFAULT 0,
    default_strategy TEXT DEFAULT 'random',
    notes TEXT,
    UNIQUE(prompt_id, wildcard_definition_id)
);

-- Prompt versions (track changes over time)
CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    version INTEGER NOT NULL DEFAULT 1,
    change_type TEXT NOT NULL DEFAULT 'created',
    changed_by TEXT DEFAULT 'system',
    change_reason TEXT,
    diff_summary TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Prompt template versions
CREATE TABLE IF NOT EXISTS prompt_template_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER NOT NULL REFERENCES prompt_templates(id),
    version INTEGER NOT NULL DEFAULT 1,
    positive_template TEXT NOT NULL,
    negative_template TEXT DEFAULT '',
    change_type TEXT NOT NULL DEFAULT 'created',
    changed_by TEXT DEFAULT 'system',
    change_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Prompt sets (stable evaluation groups)
CREATE TABLE IF NOT EXISTS prompt_sets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Prompt set members (ordered membership)
CREATE TABLE IF NOT EXISTS prompt_set_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_set_id INTEGER NOT NULL REFERENCES prompt_sets(id),
    prompt_id INTEGER NOT NULL REFERENCES prompts(id),
    position INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    UNIQUE(prompt_set_id, prompt_id)
);

-- Imports (track import jobs)
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    rows_imported INTEGER DEFAULT 0,
    rows_skipped INTEGER DEFAULT 0,
    error_log TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Exports (track export jobs)
CREATE TABLE IF NOT EXISTS exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    output_file TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT 'json',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    rows_exported INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_prompts_status ON prompts(status);
CREATE INDEX IF NOT EXISTS idx_prompts_concept ON prompts(concept);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_enabled ON prompt_templates(enabled);
CREATE INDEX IF NOT EXISTS idx_prompt_wildcard_bindings_prompt ON prompt_wildcard_bindings(prompt_id);
CREATE INDEX IF NOT EXISTS idx_wildcard_values_definition ON wildcard_values(wildcard_definition_id);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_prompt ON prompt_versions(prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompt_set_members_set ON prompt_set_members(prompt_set_id);
CREATE INDEX IF NOT EXISTS idx_prompt_set_members_position ON prompt_set_members(prompt_set_id, position);
