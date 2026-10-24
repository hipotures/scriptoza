'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export const DENSITIES = ['large', 'medium', 'compact'];

export const PROFILES = {
    large: {width: 400, font: null, title: '0.85em', titleMax: 360, padY: null, gap: null, usagePadY: 3},
    medium: {width: 320, font: '0.92em', title: '0.8em', titleMax: 280, padY: 2, gap: 10, usagePadY: 2},
    compact: {width: 260, font: '0.85em', title: '0.75em', titleMax: 220, padY: 0, gap: 8, usagePadY: 1},
};

export function configPath() {
    const base = GLib.getenv('XDG_CONFIG_HOME') || GLib.build_filenamev([GLib.get_home_dir(), '.config']);
    return GLib.build_filenamev([base, 'ai-agent-status', 'config.json']);
}

export function loadDensity(path = configPath()) {
    try {
        const [, bytes] = Gio.File.new_for_path(path).load_contents(null);
        const density = JSON.parse(new TextDecoder().decode(bytes))?.density;
        return DENSITIES.includes(density) ? density : 'large';
    } catch {
        return 'large';
    }
}

export function saveDensity(density, path = configPath()) {
    if (!DENSITIES.includes(density))
        throw new Error(`Unknown density: ${density}`);
    const file = Gio.File.new_for_path(path);
    try { file.get_parent().make_directory_with_parents(null); } catch {}
    let config = {};
    try {
        const [, bytes] = file.load_contents(null);
        config = JSON.parse(new TextDecoder().decode(bytes)) ?? {};
    } catch {}
    file.replace_contents(new TextEncoder().encode(`${JSON.stringify({...config, density}, null, 2)}\n`),
        null, false, Gio.FileCreateFlags.NONE, null);
}
