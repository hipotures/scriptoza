#!/usr/bin/env python3
"""
Import historical session data from statusline.log to SQLite database.
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

# Paths
LOG_FILE = Path.home() / '.claude' / 'log' / 'statusline.log'
DB_PATH = Path.home() / '.claude' / 'db' / 'sessions.db'

def init_db():
    """Initialize SQLite database with schema (same as statusline.py)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            first_seen TEXT NOT NULL,

            -- Static fields
            model_id TEXT,
            model_name TEXT,
            project_dir TEXT,
            transcript_path TEXT,
            version TEXT,

            -- Dynamic fields
            total_cost_usd REAL,
            total_duration_ms INTEGER,
            total_api_duration_ms INTEGER,
            total_lines_added INTEGER,
            total_lines_removed INTEGER,
            total_input_tokens INTEGER,
            total_output_tokens INTEGER,
            context_window_size INTEGER,
            exceeds_200k_tokens INTEGER,

            -- Full JSON
            raw_json TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_timestamp
        ON sessions(timestamp)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_project
        ON sessions(project_dir)
    """)

    conn.commit()
    conn.close()

def parse_log_file():
    """Parse log file and return list of (timestamp, data) tuples."""
    if not LOG_FILE.exists():
        print(f"Error: Log file not found at {LOG_FILE}")
        return []

    entries = []
    current_timestamp = None
    current_json = []
    in_json = False

    with open(LOG_FILE, 'r') as f:
        for line in f:
            line = line.rstrip('\n')

            # Detect timestamp line
            if line.startswith('[') and line.endswith(']'):
                current_timestamp = line[1:-1]  # Remove brackets
                in_json = False
                current_json = []
            # Detect separator
            elif line.startswith('====='):
                # Process previous entry if exists
                if current_json and current_timestamp:
                    try:
                        json_str = '\n'.join(current_json)
                        data = json.loads(json_str)
                        entries.append((current_timestamp, data))
                    except json.JSONDecodeError:
                        pass
                current_json = []
                in_json = False
            # JSON content
            elif current_timestamp and (line.startswith('{') or in_json):
                in_json = True
                current_json.append(line)

    # Process last entry
    if current_json and current_timestamp:
        try:
            json_str = '\n'.join(current_json)
            data = json.loads(json_str)
            entries.append((current_timestamp, data))
        except json.JSONDecodeError:
            pass

    return entries

def import_session(conn, timestamp_str, data):
    """Import single session entry to database."""
    session_id = data.get('session_id')
    if not session_id:
        return False  # Skip entries without session_id

    cursor = conn.cursor()

    # Convert timestamp string to ISO format
    try:
        dt = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
        timestamp = dt.replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        timestamp = datetime.now(timezone.utc).isoformat()

    # Check if session exists to preserve first_seen
    cursor.execute("SELECT first_seen FROM sessions WHERE session_id = ?", (session_id,))
    row = cursor.fetchone()
    first_seen = row[0] if row else timestamp

    # Extract fields
    model_data = data.get('model', {})
    workspace = data.get('workspace', {})
    cost = data.get('cost', {})
    ctx = data.get('context_window', {})

    # INSERT OR REPLACE
    cursor.execute("""
        INSERT OR REPLACE INTO sessions (
            session_id, timestamp, first_seen,
            model_id, model_name, project_dir, transcript_path, version,
            total_cost_usd, total_duration_ms, total_api_duration_ms,
            total_lines_added, total_lines_removed,
            total_input_tokens, total_output_tokens, context_window_size,
            exceeds_200k_tokens, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_id, timestamp, first_seen,
        model_data.get('id'), model_data.get('display_name'),
        workspace.get('project_dir'), data.get('transcript_path'),
        data.get('version'),
        cost.get('total_cost_usd'), cost.get('total_duration_ms'),
        cost.get('total_api_duration_ms'), cost.get('total_lines_added'),
        cost.get('total_lines_removed'),
        ctx.get('total_input_tokens'), ctx.get('total_output_tokens'),
        ctx.get('context_window_size'),
        1 if data.get('exceeds_200k_tokens') else 0,
        json.dumps(data)
    ))

    return True

def main():
    print("🔍 Importowanie danych z statusline.log do SQLite...")

    # Initialize database
    print("📊 Inicjalizacja bazy danych...")
    init_db()

    # Parse log file
    print(f"📖 Parsowanie {LOG_FILE}...")
    entries = parse_log_file()
    print(f"✓ Znaleziono {len(entries)} wpisów w logu")

    if not entries:
        print("⚠️ Brak danych do zaimportowania")
        return

    # Import to database
    print("💾 Importowanie do bazy danych...")
    conn = sqlite3.connect(DB_PATH)

    sessions_seen = {}
    imported = 0
    skipped = 0

    for timestamp_str, data in entries:
        session_id = data.get('session_id')
        if import_session(conn, timestamp_str, data):
            if session_id not in sessions_seen:
                sessions_seen[session_id] = 0
            sessions_seen[session_id] += 1
            imported += 1
        else:
            skipped += 1

    conn.commit()
    conn.close()

    # Summary
    print(f"\n✅ Import zakończony!")
    print(f"   • Zaimportowano: {imported} wpisów")
    print(f"   • Pominięto: {skipped} wpisów (brak session_id)")
    print(f"   • Unikalnych sesji: {len(sessions_seen)}")

    if sessions_seen:
        print(f"\n📈 Statystyki sesji:")
        for session_id, count in sorted(sessions_seen.items(), key=lambda x: x[1], reverse=True)[:5]:
            short_id = session_id[:8]
            print(f"   • {short_id}... : {count} aktualizacji")

    print(f"\n🗄️ Baza danych: {DB_PATH}")
    print(f"📊 Uruchom: ./utils/session_stats.sh")

if __name__ == '__main__':
    main()
