'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const DENSITIES = ['large', 'medium', 'compact'];

export const SORT_FIELDS = ['state', 'added', 'name', 'progress', 'size', 'down', 'up', 'eta'];

export const SORT_LABELS = {
    state: 'State',
    added: 'Added',
    name: 'Name',
    progress: 'Progress',
    size: 'Size',
    down: 'Down',
    up: 'Up',
    eta: 'ETA',
};

export const SORT_DIRS = ['asc', 'desc'];

export const PROFILES = {
    large: {width: 400, font: null, title: '0.85em', titleMax: 360, padY: null, gap: null},
    medium: {width: 320, font: '0.92em', title: '0.8em', titleMax: 280, padY: 2, gap: 10},
    compact: {width: 260, font: '0.85em', title: '0.75em', titleMax: 220, padY: 0, gap: 8},
};

export const DEFAULT_CONFIG = {
    name: 'rtorrent',
    host: '127.0.0.1',
    port: 5000,
    servers: [{host: '127.0.0.1', port: 5000}],
    activeServer: 0,
    pollSeconds: 3,
    density: 'large',
    sortBy: 'state',
    sortDir: 'asc',
    anonymize: false,
};

export function configPath() {
    const base = GLib.getenv('XDG_CONFIG_HOME') || GLib.build_filenamev([GLib.get_home_dir(), '.config']);
    return GLib.build_filenamev([base, 'scriptoza', 'rtorrent-status.json']);
}

function normalizeServer(entry) {
    const host = typeof entry?.host === 'string' && entry.host.trim() ? entry.host.trim() : null;
    if (!host)
        return null;
    const portNum = Number(entry?.port);
    const port = Number.isInteger(portNum) && portNum >= 1 && portNum <= 65535 ? portNum : DEFAULT_CONFIG.port;
    return {host, port};
}

export function parseServerSpec(spec) {
    const text = String(spec ?? '').trim();
    if (!text)
        return null;
    const colon = text.lastIndexOf(':');
    if (colon > 0 && !text.endsWith(']')) {
        const host = text.slice(0, colon).trim();
        const portNum = Number(text.slice(colon + 1).trim());
        if (!host || !Number.isInteger(portNum) || portNum < 1 || portNum > 65535)
            return null;
        return {host, port: portNum};
    }
    return {host: text, port: DEFAULT_CONFIG.port};
}

function normalizeConfig(raw) {
    const name = typeof raw?.name === 'string' && raw.name.trim() ? raw.name.trim() : DEFAULT_CONFIG.name;
    const fallbackServer = normalizeServer({host: raw?.host, port: raw?.port}) ?? {
        host: DEFAULT_CONFIG.host,
        port: DEFAULT_CONFIG.port,
    };
    let servers = Array.isArray(raw?.servers)
        ? raw.servers.map(normalizeServer).filter(Boolean)
        : [];
    if (!servers.length)
        servers = [fallbackServer];
    const activeRaw = Number(raw?.activeServer);
    const activeServer = Number.isInteger(activeRaw) && activeRaw >= 0 && activeRaw < servers.length ? activeRaw : 0;
    const current = servers[activeServer];
    const pollNum = Number(raw?.pollSeconds);
    const pollSeconds = Number.isFinite(pollNum) && pollNum >= 1 ? Math.round(pollNum) : DEFAULT_CONFIG.pollSeconds;
    const density = DENSITIES.includes(raw?.density) ? raw.density : DEFAULT_CONFIG.density;
    const sortBy = SORT_FIELDS.includes(raw?.sortBy) ? raw.sortBy : DEFAULT_CONFIG.sortBy;
    const sortDir = SORT_DIRS.includes(raw?.sortDir) ? raw.sortDir : DEFAULT_CONFIG.sortDir;
    const anonymize = Boolean(raw?.anonymize);
    return {
        name,
        host: current.host,
        port: current.port,
        servers,
        activeServer,
        pollSeconds,
        density,
        sortBy,
        sortDir,
        anonymize,
    };
}

function writeConfig(config, path) {
    const file = Gio.File.new_for_path(path);
    try { file.get_parent().make_directory_with_parents(null); } catch {}
    file.replace_contents(
        new TextEncoder().encode(`${JSON.stringify(config, null, 2)}\n`),
        null,
        false,
        Gio.FileCreateFlags.NONE,
        null
    );
}

export function loadConfig(path = configPath()) {
    const file = Gio.File.new_for_path(path);
    if (!file.query_exists(null)) {
        const initial = {...DEFAULT_CONFIG};
        try { writeConfig(initial, path); } catch {}
        return initial;
    }
    try {
        const [, bytes] = file.load_contents(null);
        return normalizeConfig(JSON.parse(new TextDecoder().decode(bytes)));
    } catch {
        return {...DEFAULT_CONFIG};
    }
}

function updateConfig(patch, path = configPath()) {
    let existing = {};
    try {
        const [, bytes] = Gio.File.new_for_path(path).load_contents(null);
        existing = JSON.parse(new TextDecoder().decode(bytes)) ?? {};
    } catch {}
    writeConfig({...normalizeConfig(existing), ...existing, ...patch}, path);
}

export function saveDensity(density, path = configPath()) {
    if (!DENSITIES.includes(density))
        throw new Error(`Unknown density: ${density}`);
    updateConfig({density}, path);
}

export function saveSort(sortBy, sortDir, path = configPath()) {
    if (!SORT_FIELDS.includes(sortBy))
        throw new Error(`Unknown sort field: ${sortBy}`);
    if (!SORT_DIRS.includes(sortDir))
        throw new Error(`Unknown sort direction: ${sortDir}`);
    updateConfig({sortBy, sortDir}, path);
}

export function saveAnonymize(anonymize, path = configPath()) {
    updateConfig({anonymize: Boolean(anonymize)}, path);
}

export function saveServers(servers, activeServer, path = configPath()) {
    const valid = Array.isArray(servers) ? servers.map(normalizeServer).filter(Boolean) : [];
    if (!valid.length)
        throw new Error('At least one server is required');
    const idx = Number.isInteger(activeServer) && activeServer >= 0 && activeServer < valid.length ? activeServer : 0;
    const current = valid[idx];
    updateConfig({servers: valid, activeServer: idx, host: current.host, port: current.port}, path);
}
