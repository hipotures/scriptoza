'use strict';

export function selectClientWindow(clients, windows) {
    const matches = windows.map(window => ({
        window,
        clients: clients.filter(client => client.ancestor_pids.includes(window.pid)),
    })).filter(match => match.clients.length > 0)
        .sort((left, right) => right.window.userTime - left.window.userTime);
    if (!matches.length)
        throw new Error('No running Herdr client found in a desktop window. Reopen the Herdr client after updating it.');
    const match = matches[0];
    if (match.clients.length !== 1)
        throw new Error('Multiple Herdr clients share this terminal window. Use a separate window for each client.');
    if (matches.filter(candidate => candidate.clients.some(client => client.pid === match.clients[0].pid)).length > 1)
        throw new Error('Multiple terminal windows share this process. Cannot identify the Herdr window.');
    return {pid: match.clients[0].pid, window: match.window.window};
}
