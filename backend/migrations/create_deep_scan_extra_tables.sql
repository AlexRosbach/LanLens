-- Migration: create tables for deep scan findings and device-host relationships

CREATE TABLE IF NOT EXISTS deep_scan_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES deep_scan_runs(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS device_host_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    host_device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    relationship_type TEXT DEFAULT 'vm_on_host',
    match_source TEXT,
    confidence INTEGER DEFAULT 50,
    observed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_confirmed_at DATETIME
);
