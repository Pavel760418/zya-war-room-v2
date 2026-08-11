-- WAR_ROM service DB schema (SQLite-compatible). Analytics schema prefix via table names.
-- Does NOT touch SQL Server 1C.

CREATE TABLE IF NOT EXISTS analytics_1c_storage_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metadata_name TEXT,
    storage_table_name TEXT,
    physical_table_name TEXT,
    purpose TEXT,
    source_file_name TEXT NOT NULL,
    source_file_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS ix_1c_map_active ON analytics_1c_storage_map(is_active);
CREATE INDEX IF NOT EXISTS ix_1c_map_meta ON analytics_1c_storage_map(metadata_name);
CREATE INDEX IF NOT EXISTS ix_1c_map_physical ON analytics_1c_storage_map(physical_table_name);
CREATE INDEX IF NOT EXISTS ix_1c_map_search ON analytics_1c_storage_map(metadata_name, storage_table_name, physical_table_name);

CREATE TABLE IF NOT EXISTS analytics_1c_storage_map_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_name TEXT NOT NULL,
    source_file_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    actor TEXT,
    total_rows INTEGER NOT NULL DEFAULT 0,
    inserted_rows INTEGER NOT NULL DEFAULT 0,
    updated_rows INTEGER NOT NULL DEFAULT 0,
    deactivated_rows INTEGER NOT NULL DEFAULT 0,
    skipped_rows INTEGER NOT NULL DEFAULT 0,
    import_status TEXT NOT NULL,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS analytics_semantic_entities (
    entity_code TEXT PRIMARY KEY,
    entity_name TEXT NOT NULL,
    business_description TEXT,
    c1_metadata_pattern TEXT,
    source_tables TEXT,
    grain TEXT,
    business_keys TEXT,
    date_field TEXT,
    store_field TEXT,
    warehouse_field TEXT,
    item_field TEXT,
    status TEXT NOT NULL DEFAULT 'candidate',
    validation_status TEXT NOT NULL DEFAULT 'unvalidated',
    owner TEXT,
    updated_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS analytics_cache_meta (
    cache_key TEXT PRIMARY KEY,
    updated_at TEXT NOT NULL,
    notes TEXT
);
