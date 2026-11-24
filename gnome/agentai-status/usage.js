'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const CLAUDE_INPUT_NAME = 'claude-statusline-input.json';
const TAIL_BYTES = 262144;
const MAX_ROLLOUTS = 5;
const WEEK_MINUTES = 7 * 24 * 60;

function window(usedPercent, resetsAt) {
    if (!Number.isFinite(usedPercent) || !Number.isFinite(resetsAt))
        return null;
    return {usedPercent, resetsAt};
}

export function parseClaudeUsage(text) {
    const limits = JSON.parse(text)?.rate_limits;
    if (!limits)
        return null;
    const five = window(limits.five_hour?.used_percentage, limits.five_hour?.resets_at);
    const week = window(limits.seven_day?.used_percentage, limits.seven_day?.resets_at);
    return five || week ? {five, week} : null;
}

export function parseCodexUsage(text) {
    const lines = text.split('\n');
    for (let index = lines.length - 1; index >= 0; index--) {
        if (!lines[index].includes('"rate_limits"'))
            continue;
        let limits;
        try { limits = JSON.parse(lines[index])?.payload?.rate_limits; } catch { continue; }
        if (!limits)
            continue;
        const usage = {five: null, week: null};
        for (const entry of [limits.primary, limits.secondary]) {
            const parsed = window(entry?.used_percent, entry?.resets_at);
            if (parsed)
                usage[entry.window_minutes >= WEEK_MINUTES ? 'week' : 'five'] = parsed;
        }
        if (usage.five || usage.week)
            return usage;
    }
    return null;
}

function listNames(directory) {
    const names = [];
    try {
        const enumerator = directory.enumerate_children('standard::name', Gio.FileQueryInfoFlags.NONE, null);
        for (let info = enumerator.next_file(null); info; info = enumerator.next_file(null))
            names.push(info.get_name());
        enumerator.close(null);
    } catch {}
    return names.sort().reverse();
}

function readTail(file) {
    const stream = file.read(null);
    try {
        const size = file.query_info('standard::size', Gio.FileQueryInfoFlags.NONE, null).get_size();
        if (size > TAIL_BYTES)
            stream.seek(size - TAIL_BYTES, GLib.SeekType.SET, null);
        return new TextDecoder().decode(stream.read_bytes(TAIL_BYTES, null).toArray());
    } finally {
        stream.close(null);
    }
}

function recentRollouts(sessions) {
    const files = [];
    for (const year of listNames(sessions)) {
        for (const month of listNames(sessions.get_child(year))) {
            for (const day of listNames(sessions.get_child(year).get_child(month))) {
                const directory = sessions.get_child(year).get_child(month).get_child(day);
                for (const name of listNames(directory)) {
                    if (name.startsWith('rollout-') && name.endsWith('.jsonl'))
                        files.push(directory.get_child(name));
                    if (files.length >= MAX_ROLLOUTS)
                        return files;
                }
            }
        }
    }
    return files;
}

export function readClaudeUsage(runtimeDir = GLib.get_user_runtime_dir()) {
    try {
        const [, bytes] = Gio.File.new_for_path(GLib.build_filenamev([runtimeDir, CLAUDE_INPUT_NAME]))
            .load_contents(null);
        return parseClaudeUsage(new TextDecoder().decode(bytes));
    } catch {
        return null;
    }
}

export function readCodexUsage(codexHome = GLib.build_filenamev([GLib.get_home_dir(), '.codex'])) {
    try {
        const sessions = Gio.File.new_for_path(GLib.build_filenamev([codexHome, 'sessions']));
        for (const file of recentRollouts(sessions)) {
            const usage = parseCodexUsage(readTail(file));
            if (usage)
                return usage;
        }
    } catch {}
    return null;
}

export class UsageMonitor {
    constructor(onUpdate, {interval = 60, readers = {claude: readClaudeUsage, codex: readCodexUsage}} = {}) {
        this._onUpdate = onUpdate;
        this._interval = interval;
        this._readers = readers;
        this._source = 0;
        this.current = {claude: null, codex: null};
    }

    start() {
        this._refresh();
        this._source = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, this._interval, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _refresh() {
        this.current = Object.fromEntries(Object.entries(this._readers).map(([name, read]) => [name, read()]));
        this._onUpdate(this.current);
    }

    close() {
        if (this._source)
            GLib.Source.remove(this._source);
        this._source = 0;
    }
}
