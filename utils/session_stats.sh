#!/bin/bash
# Session statistics helper for Claude Code sessions database

DB=~/.claude/db/sessions.db

if [ ! -f "$DB" ]; then
    echo "Error: Database not found at $DB"
    exit 1
fi

# Top 10 najdroższych sesji
echo "=== Top 10 najdroższych sesji ==="
sqlite3 -box "$DB" "SELECT
    substr(session_id, 1, 8) as id,
    substr(project_dir, -30) as project,
    printf('$%.2f', total_cost_usd) as cost,
    printf('%dk', total_output_tokens/1000) as tokens,
    datetime(timestamp) as last_update
FROM sessions
ORDER BY total_cost_usd DESC
LIMIT 10;"

# Suma kosztów per projekt
echo -e "\n=== Suma kosztów per projekt ==="
sqlite3 -box "$DB" "SELECT
    substr(project_dir, -40) as project,
    printf('$%.2f', SUM(total_cost_usd)) as total_cost,
    COUNT(*) as sessions,
    printf('%dk', SUM(total_output_tokens)/1000) as total_tokens
FROM sessions
GROUP BY project_dir
ORDER BY SUM(total_cost_usd) DESC;"

# Aktywne sesje dzisiaj
echo -e "\n=== Sesje dzisiaj ==="
sqlite3 -box "$DB" "SELECT
    substr(session_id, 1, 8) as id,
    model_name,
    printf('$%.2f', total_cost_usd) as cost,
    printf('%dk', total_output_tokens/1000) as tokens
FROM sessions
WHERE date(timestamp) = date('now')
ORDER BY total_cost_usd DESC;"

# Podsumowanie całkowite
echo -e "\n=== Podsumowanie całkowite ==="
sqlite3 -box "$DB" "SELECT
    COUNT(*) as total_sessions,
    printf('$%.2f', SUM(total_cost_usd)) as total_cost,
    printf('%dk', SUM(total_input_tokens)/1000) as total_in,
    printf('%dk', SUM(total_output_tokens)/1000) as total_out,
    printf('%.1fh', SUM(total_duration_ms)/3600000.0) as total_time
FROM sessions;"

# Cost & Tokens per day
echo -e "\n=== Cost & Tokens per day ==="
sqlite3 -box "$DB" "SELECT
    date(timestamp) as date,
    COUNT(*) as sessions,
    printf('$%.2f', SUM(total_cost_usd)) as cost,
    printf('%dk', SUM(total_input_tokens)/1000) as in_tokens,
    printf('%dk', SUM(total_output_tokens)/1000) as out_tokens,
    printf('%.1fh', SUM(total_duration_ms)/3600000.0) as time
FROM sessions
GROUP BY date(timestamp)
ORDER BY date(timestamp) DESC
LIMIT 30;"

# Statystyki per model
echo -e "\n=== Statystyki per model ==="
sqlite3 -box "$DB" "SELECT
    model_name,
    COUNT(*) as sessions,
    printf('$%.2f', SUM(total_cost_usd)) as total_cost,
    printf('$%.4f', AVG(total_cost_usd)) as avg_cost
FROM sessions
GROUP BY model_name
ORDER BY SUM(total_cost_usd) DESC;"
