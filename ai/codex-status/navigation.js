'use strict';

export function focusTarget(agent) {
    if (!agent || typeof agent.serverId !== 'string' || !agent.serverId ||
        typeof agent.paneId !== 'string' || !agent.paneId)
        throw new Error('The selected agent has no valid machine and pane identity');
    return `${agent.serverId}:${agent.paneId}`;
}

export function clientWindowToken(clientId) {
    if (typeof clientId !== 'string' || !clientId)
        throw new Error('Herdr returned an invalid client identity');
    return `[herdr-client:${clientId}]`;
}

function windowTitle(window) {
    if (typeof window?.get_title === 'function')
        return window.get_title() ?? '';
    return window?.title ?? '';
}

function sameWindow(left, right) {
    if (left === right)
        return true;
    if (typeof left?.get_stable_sequence !== 'function' ||
        typeof right?.get_stable_sequence !== 'function')
        return false;
    const leftSequence = left.get_stable_sequence();
    const rightSequence = right.get_stable_sequence();
    return leftSequence !== null && leftSequence !== undefined &&
        leftSequence === rightSequence;
}

export function findClientWindow(actors, token) {
    if (typeof token !== 'string' || !token)
        throw new Error('Herdr returned an invalid client window token');
    if (!actors)
        throw new Error('GNOME did not return its window list');
    let actorList;
    try {
        actorList = Array.from(actors);
    } catch {
        throw new Error('GNOME did not return its window list');
    }
    const matches = actorList.map(actor => actor?.meta_window ?? actor)
        .filter(window => windowTitle(window).includes(token));
    if (matches.length === 0)
        throw new Error(`Herdr client window '${token}' was not found`);
    if (matches.length > 1)
        throw new Error(`Multiple terminal windows match Herdr client '${token}'`);
    return matches[0];
}

function validateCheck(data, expectedBootId) {
    if (!data || typeof data.client_id !== 'string' || !data.client_id ||
        typeof data.window_token !== 'string' || !data.window_token ||
        typeof data.boot_id !== 'string' || !data.boot_id)
        throw new Error('Herdr returned an invalid focus check response');
    const expectedToken = clientWindowToken(data.client_id);
    if (data.window_token !== expectedToken)
        throw new Error('Herdr returned a mismatched client window token');
    if (data.boot_id !== expectedBootId)
        throw new Error('Herdr focus check returned a different server boot');
    return data;
}

export function validateFocusReply(data, expected) {
    if (!data || typeof data.client_id !== 'string' || !data.client_id ||
        typeof data.window_token !== 'string' || !data.window_token ||
        typeof data.boot_id !== 'string' || !data.boot_id)
        throw new Error('Herdr returned an invalid focus acknowledgement');
    if (data.client_id !== expected.client_id ||
        data.window_token !== expected.window_token ||
        data.boot_id !== expected.boot_id)
        throw new Error('Herdr returned a mismatched focus acknowledgement');
    return data;
}

export class Navigator {
    constructor({collector, readJson, getWindowActors, activateWindow, closeMenu, notifyError}) {
        if (!readJson && !collector?.readJson)
            throw new Error('A Herdr JSON reader is required');
        this._collector = collector ?? null;
        this._readJson = readJson ?? (args => this._collector.readJson(args));
        this._getWindowActors = getWindowActors;
        this._activateWindow = activateWindow;
        this._closeMenu = closeMenu;
        this._notifyError = notifyError;
        this._busy = false;
        this._closed = false;
    }

    get busy() {
        return this._busy;
    }

    close() {
        this._closed = true;
        this._collector?.close();
    }

    async focus(agent) {
        if (this._closed || this._busy)
            return false;
        this._busy = true;
        let operation;
        try {
            if (typeof agent?.bootId !== 'string' || !agent.bootId)
                throw new Error('The selected agent has no valid Herdr server boot identity');
            const target = focusTarget(agent);
            const checked = validateCheck(await this._readJson([
                'agent', 'focus', target, '--check', '--expected-boot', agent.bootId,
            ]), agent.bootId);
            if (this._closed)
                return false;
            const window = findClientWindow(this._getWindowActors(), checked.window_token);
            if (this._closed)
                return false;
            const result = await this._readJson([
                'agent', 'focus', target,
                '--client', checked.client_id,
                '--expected-boot', checked.boot_id,
            ]);
            if (this._closed)
                return false;
            validateFocusReply(result, checked);
            const currentWindow = findClientWindow(this._getWindowActors(), checked.window_token);
            if (!sameWindow(currentWindow, window))
                throw new Error(`Herdr client window '${checked.window_token}' changed during focus`);
            this._activateWindow(window);
            this._closeMenu();
            operation = true;
        } catch (error) {
            if (!this._closed)
                this._notifyError(`Unable to focus ${agent?.location ?? 'the selected Codex agent'}`, error);
            operation = false;
        } finally {
            this._busy = false;
        }
        return operation;
    }
}
