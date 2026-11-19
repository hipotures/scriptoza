'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const DENSITIES = ['large', 'medium', 'compact'];

export const PROFILES = {
    large: {width: 400, font: null, title: '0.85em', titleMax: 360, padY: null, gap: null},
    medium: {width: 320, font: '0.92em', title: '0.8em', titleMax: 280, padY: 2, gap: 10},
    compact: {width: 260, font: '0.85em', title: '0.75em', titleMax: 220, padY: 0, gap: 8},
};

export const DEFAULT_CONFIG = {
    name: 'rtorrent',
    host: '127.0.0.1',
    port: 5000,
    pollSeconds: 3,
    density: 'large',
};

export function configPath() {
    const base = GLib.getenv('XDG_CONFIG_HOME') || GLib.build_filenamev([GLib.get_home_dir(), '.config']);
    return GLib.build_filenamev([base, 'scriptoza', 'rtorrent-status.json']);
}

function normalizeConfig(raw) {
    const name = typeof raw?.name === 'string' && raw.name.trim() ? raw.name.trim() : DEFAULT_CONFIG.name;
    const host = typeof raw?.host === 'string' && raw.host.trim() ? raw.host.trim() : DEFAULT_CONFIG.host;
    const portNum = Number(raw?.port);
    const port = Number.isInteger(portNum) && portNum >= 1 && portNum <= 65535 ? portNum : DEFAULT_CONFIG.port;
    const pollNum = Number(raw?.pollSeconds);
    const pollSeconds = Number.isFinite(pollNum) && pollNum >= 1 ? Math.round(pollNum) : DEFAULT_CONFIG.pollSeconds;
    const density = DENSITIES.includes(raw?.density) ? raw.density : DEFAULT_CONFIG.density;
    return {name, host, port, pollSeconds, density};
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

export function saveDensity(density, path = configPath()) {
    if (!DENSITIES.includes(density))
        throw new Error(`Unknown density: ${density}`);
    let existing = {};
    try {
        const [, bytes] = Gio.File.new_for_path(path).load_contents(null);
        existing = JSON.parse(new TextDecoder().decode(bytes)) ?? {};
    } catch {}
    writeConfig({...normalizeConfig(existing), ...existing, density}, path);
}
