'use strict';

export function formatRemaining(seconds) {
    const minutes = Math.max(1, Math.ceil(seconds / 60));
    if (minutes >= 1440)
        return `${Math.floor(minutes / 1440)}d`;
    if (minutes >= 60)
        return `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}m`;
    return `${minutes}m`;
}

export function formatUsage(usage, now) {
    if (!usage)
        return '';
    const parts = [];
    for (const [key, name] of [['five', '5h'], ['week', 'wk']]) {
        const window = usage[key];
        if (!window || window.resetsAt <= now)
            continue;
        const left = Math.max(0, Math.min(100, Math.round(100 - window.usedPercent)));
        parts.push(`${name} ${left}% · ${formatRemaining(window.resetsAt - now).padEnd(5)}`);
    }
    return parts.join('  ');
}
