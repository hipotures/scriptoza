'use strict';

export const STATES = {
    error: {color: '#ff5555', icon: 'dialog-warning-symbolic', label: 'Error', rank: 0},
    hashing: {color: '#f8e45c', icon: 'view-refresh-symbolic', label: 'Hashing', rank: 1},
    downloading: {color: '#3584e4', icon: 'folder-download-symbolic', label: 'Downloading', rank: 2},
    seeding: {color: '#2ec27e', icon: 'object-select-symbolic', label: 'Seeding', rank: 3},
    paused: {color: '#9a9996', icon: 'media-playback-pause-symbolic', label: 'Paused', rank: 4},
};

const UNITS = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];

export function formatBytes(bytes) {
    const value = Number(bytes);
    if (!Number.isFinite(value) || value <= 0)
        return '0 B';
    const exp = Math.min(Math.floor(Math.log(value) / Math.log(1024)), UNITS.length - 1);
    const scaled = value / (1024 ** exp);
    const decimals = exp === 0 ? 0 : scaled >= 100 ? 0 : scaled >= 10 ? 1 : 2;
    return `${scaled.toFixed(decimals)} ${UNITS[exp]}`;
}

export function formatRate(bytesPerSec) {
    return `${formatBytes(bytesPerSec)}/s`;
}

export function formatEta(remainingBytes, downRate) {
    if (remainingBytes <= 0 || downRate <= 0)
        return '';
    const totalSeconds = Math.ceil(remainingBytes / downRate);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (days > 0)
        return `${days}d ${hours}h`;
    if (hours > 0)
        return `${hours}h ${String(minutes).padStart(2, '0')}m`;
    if (minutes > 0)
        return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
    return `${seconds}s`;
}

export function classifyState({isActive, complete, hashing, message}) {
    if (hashing > 0)
        return 'hashing';
    const isTrackerNotice = typeof message === 'string' && message.startsWith('Tracker:');
    if (message && !isTrackerNotice)
        return 'error';
    if (isActive === 1 && complete === 0)
        return 'downloading';
    if (isActive === 1 && complete === 1)
        return 'seeding';
    return 'paused';
}

export function normalizeTorrent(row, queueIndex = 0) {
    const [
        hash = '',
        name = '',
        stateFlag = 0,
        isActive = 0,
        complete = 0,
        hashing = 0,
        sizeBytes = 0,
        completedBytes = 0,
        downRate = 0,
        upRate = 0,
        rawMessage = '',
        peersConnected = 0,
        peersComplete = 0,
        peersAccounted = 0,
        upTotal = 0,
        ratioRaw = 0,
    ] = row;
    const message = typeof rawMessage === 'string' ? rawMessage.trim() : '';
    const size = Math.max(0, Number(sizeBytes) || 0);
    const completed = Math.max(0, Number(completedBytes) || 0);
    const down = Math.max(0, Number(downRate) || 0);
    const up = Math.max(0, Number(upRate) || 0);
    const peers = Math.max(0, Number(peersConnected) || 0);
    const seeders = Math.max(0, Number(peersComplete) || 0);
    const leechers = Math.max(0, Number(peersAccounted) || 0);
    const uploaded = Math.max(0, Number(upTotal) || 0);
    const ratio = Math.max(0, Number(ratioRaw) || 0) / 1000;
    const state = classifyState({
        isActive: Number(isActive) || 0,
        complete: Number(complete) || 0,
        hashing: Number(hashing) || 0,
        message,
    });
    const percent = size > 0 ? Math.min(100, (completed / size) * 100) : 0;
    const remaining = Math.max(0, size - completed);
    const etaSeconds = state === 'downloading' && remaining > 0 && down > 0 ? Math.ceil(remaining / down) : null;
    const eta = etaSeconds !== null ? formatEta(remaining, down) : '';
    return {
        hash: String(hash),
        name: String(name || hash),
        stateFlag: Number(stateFlag) || 0,
        isActive: Number(isActive) || 0,
        complete: Number(complete) || 0,
        hashing: Number(hashing) || 0,
        sizeBytes: size,
        completedBytes: completed,
        downRate: down,
        upRate: up,
        peersConnected: peers,
        seeders,
        leechers,
        upTotal: uploaded,
        ratio,
        message,
        state,
        percent,
        etaSeconds,
        eta,
        queueIndex,
    };
}

export function formatTorrentSubtitle(torrent) {
    const pct = `${torrent.percent.toFixed(1)}%`;
    const parts = [pct, `${formatBytes(torrent.completedBytes)} / ${formatBytes(torrent.sizeBytes)}`];
    if (torrent.downRate > 0)
        parts.push(`↓ ${formatRate(torrent.downRate)}`);
    if (torrent.upRate > 0)
        parts.push(`↑ ${formatRate(torrent.upRate)}`);
    if (torrent.eta)
        parts.push(torrent.eta);
    if (torrent.state === 'error' && torrent.message)
        parts.push(torrent.message);
    return parts.join(' · ');
}

export function formatTorrentTooltip(torrent) {
    const peerPart = torrent.peersConnected > 0
        ? `Peers: ${torrent.peersConnected} (${torrent.seeders} seeds · ${torrent.leechers} leechers)`
        : 'Peers: 0';
    const ratePart = `↓ ${formatRate(torrent.downRate)} · ↑ ${formatRate(torrent.upRate)}`;
    const ratioPart = `Up: ${formatBytes(torrent.upTotal)} · Ratio: ${torrent.ratio.toFixed(2)}`;
    const base = `${peerPart} · ${ratePart} · ${ratioPart}`;
    if (torrent.state === 'error' && torrent.message)
        return `${base}\n${torrent.message}`;
    return base;
}

export function sortTorrents(torrents, sortBy = 'state', sortDir = 'asc') {
    const dir = sortDir === 'desc' ? -1 : 1;
    const comparePrimary = (a, b) => {
        switch (sortBy) {
        case 'added':
            return ((a.queueIndex ?? 0) - (b.queueIndex ?? 0)) * dir;
        case 'name':
            return a.name.localeCompare(b.name) * dir;
        case 'progress':
            return (a.percent - b.percent) * dir;
        case 'size':
            return (a.sizeBytes - b.sizeBytes) * dir;
        case 'down':
            return (a.downRate - b.downRate) * dir;
        case 'up':
            return (a.upRate - b.upRate) * dir;
        case 'eta': {
            const aHas = a.etaSeconds !== null && a.etaSeconds !== undefined;
            const bHas = b.etaSeconds !== null && b.etaSeconds !== undefined;
            if (aHas !== bHas)
                return aHas ? -1 : 1;
            if (!aHas)
                return 0;
            return (a.etaSeconds - b.etaSeconds) * dir;
        }
        case 'state':
        default:
            return (STATES[a.state].rank - STATES[b.state].rank) * dir;
        }
    };
    return [...torrents].sort((a, b) =>
        comparePrimary(a, b) ||
        STATES[a.state].rank - STATES[b.state].rank ||
        a.name.localeCompare(b.name));
}

export function summarizeTorrents(torrents) {
    const counts = {error: 0, hashing: 0, downloading: 0, seeding: 0, paused: 0};
    let totalDownRate = 0;
    let totalUpRate = 0;
    for (const torrent of torrents) {
        counts[torrent.state] = (counts[torrent.state] ?? 0) + 1;
        totalDownRate += torrent.downRate;
        totalUpRate += torrent.upRate;
    }
    return {counts, totalDownRate, totalUpRate};
}

const NAME_CHARS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
const HEX_CHARS = '0123456789ABCDEF';

function seededString(seedText, salt, length, alphabet) {
    let state = (2166136261 ^ (salt >>> 0)) >>> 0;
    for (let i = 0; i < seedText.length; i++) {
        state ^= seedText.charCodeAt(i);
        state = Math.imul(state, 16777619) >>> 0;
    }
    if (state === 0)
        state = 0x9e3779b9;
    let out = '';
    for (let i = 0; i < length; i++) {
        state ^= state << 13;
        state ^= state >>> 17;
        state ^= state << 5;
        out += alphabet[(state >>> 0) % alphabet.length];
    }
    return out;
}

export function anonymizeTorrent(torrent, salt = 0) {
    const seed = `${torrent.hash || torrent.name}`;
    const nameLen = Math.max(12, Math.min(28, torrent.name.length || 16));
    const hashLen = Math.max(16, Math.min(40, torrent.hash.length || 40));
    return {
        name: seededString(`name:${seed}`, salt, nameLen, NAME_CHARS),
        hash: seededString(`hash:${seed}`, salt, hashLen, HEX_CHARS),
    };
}
