'use strict';

import GLib from 'gi://GLib';
import {Collector} from './collector.js';
import {EventStream} from './event-stream.js';
import {normalizeAgents, trackActivity} from './model.js';

export class EventMonitor {
    constructor(onUpdate, {collector = new Collector(), stream = (...args) => new EventStream(...args)} = {}) {
        this._collector = collector;
        this._stream = stream;
        this._onUpdate = onUpdate;
        this._entries = new Map();
        this._history = new Map();
        this._closed = false;
        this._updatedAt = null;
        this._discovering = false;
        this._discoveryError = null;
        this._discoverySource = 0;
    }

    start() {
        this._add({id: 'local', label: 'Local'});
        this._discoverySource = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 60, () => {
            this._discover();
            return GLib.SOURCE_CONTINUE;
        });
    }

    _add(server) {
        const entry = {server, agents: [], stream: null, panes: null, busy: false,
            dirty: false, timer: 0, online: false, removed: false, epoch: 0};
        this._entries.set(server.id, entry);
        this._refresh(entry);
    }

    async _discover() {
        if (this._closed || this._discovering || !this._entries.get('local')?.online)
            return;
        this._discovering = true;
        try {
            const profiles = await this._collector.readJson(['machine', 'list', '--json']);
            if (!Array.isArray(profiles) || profiles.some(server => typeof server.id !== 'string' ||
                typeof server.label !== 'string' || typeof server.enabled !== 'boolean'))
                throw new Error('Invalid Herdr machine list');
            if (this._closed || !this._entries.get('local')?.online)
                return;
            this._discoveryError = null;
            const wanted = new Map(profiles.filter(server => server.enabled).map(({id, label, target, session}) =>
                [id, {id, label, target, session}]));
            for (const [id, entry] of this._entries) {
                if (id === 'local')
                    continue;
                const next = wanted.get(id);
                if (!next || JSON.stringify(next) !== JSON.stringify(entry.server)) {
                    this._remove(entry);
                    this._entries.delete(id);
                }
            }
            for (const server of wanted.values()) {
                if (!this._entries.has(server.id))
                    this._add(server);
            }
            this._publish();
        } catch (error) {
            this._discoveryError = {serverId: 'discovery', machine: 'Herdr', message: error.message};
            this._publish();
        } finally {
            this._discovering = false;
        }
    }

    _invalidate(entry) {
        if (this._closed || entry.removed)
            return;
        entry.dirty = true;
        if (entry.busy || entry.timer)
            return;
        // Coalesce bursts of title, lifecycle and status events from one server.
        entry.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 100, () => {
            entry.timer = 0;
            this._refresh(entry);
            return GLib.SOURCE_REMOVE;
        });
    }

    async _refresh(entry) {
        if (this._closed || entry.removed || entry.busy)
            return;
        entry.busy = true;
        const wasOnline = entry.online;
        const epoch = entry.epoch;
        const start = GLib.get_monotonic_time();
        const metrics = {requests: 0, bytes: 0, parseMs: 0, totalMs: 0};
        try {
            do {
                entry.dirty = false;
                const prefix = entry.server.id === 'local' ? [] : ['--machine', entry.server.id];
                const data = await this._collector._readJson([...prefix, 'api', 'snapshot'], metrics);
                if (this._closed || entry.removed || entry.epoch !== epoch)
                    return;
                const snapshot = data.result?.snapshot;
                const agents = normalizeAgents(snapshot, entry.server);
                entry.agents = trackActivity(agents, this._history, GLib.get_monotonic_time() / 1000);
                const ids = new Set(agents.map(agent => agent.id));
                for (const [id, previous] of this._history) {
                    if (previous.serverId === entry.server.id && !ids.has(id))
                        this._history.delete(id);
                }
                entry.online = true;
                entry.error = null;
                const panes = snapshot.panes.map(pane => pane.pane_id).sort();
                if (!entry.stream || JSON.stringify(panes) !== JSON.stringify(entry.panes)) {
                    entry.stream?.close();
                    entry.panes = panes;
                    const generation = {};
                    entry.generation = generation;
                    entry.stream = this._stream(entry.server, this._collector._herdr, panes,
                        () => { if (entry.generation === generation) this._invalidate(entry); },
                        () => { if (entry.generation === generation) this._invalidate(entry); },
                        error => {
                            if (entry.generation === generation && !entry.removed && !this._closed)
                                this._failed(entry, error);
                        });
                }
                metrics.totalMs = (GLib.get_monotonic_time() - start) / 1000;
                this._updatedAt = Date.now();
                this._publish(metrics);
            } while (entry.dirty && !this._closed && !entry.removed);
            if (entry.server.id === 'local' && !wasOnline)
                this._discover();
        } catch (error) {
            if (!this._closed && !entry.removed)
                this._failed(entry, error);
        } finally {
            entry.busy = false;
        }
    }

    _failed(entry, error) {
        entry.epoch++;
        entry.generation = null;
        entry.stream?.close();
        entry.stream = null;
        entry.online = false;
        entry.agents = [];
        entry.error = error.message;
        if (entry.timer)
            GLib.Source.remove(entry.timer);
        const local = entry.server.id === 'local';
        if (local) {
            for (const [id, remote] of this._entries) {
                if (id !== 'local') {
                    this._remove(remote);
                    this._entries.delete(id);
                }
            }
        }
        this._publish();
        entry.timer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, local ? 3 : 60, () => {
            if (entry.busy)
                return GLib.SOURCE_CONTINUE;
            entry.timer = 0;
            this._refresh(entry);
            return GLib.SOURCE_REMOVE;
        });
    }

    _publish(metrics = {requests: 0, bytes: 0, parseMs: 0, totalMs: 0}) {
        if (this._closed)
            return;
        const local = this._entries.get('local');
        const errors = local?.error ? [{serverId: 'local', machine: 'Local', message: local.error}] : [];
        if (this._discoveryError)
            errors.push(this._discoveryError);
        this._onUpdate({agents: [...this._entries.values()].flatMap(entry => entry.agents), errors,
            metrics, updatedAt: this._updatedAt, waitingForServer: !local?.online,
            ignoredMachines: [...this._entries.values()].filter(entry => !entry.online &&
                entry.server.id !== 'local').map(entry => entry.server.label)});
    }

    _remove(entry) {
        entry.removed = true;
        entry.stream?.close();
        if (entry.timer)
            GLib.Source.remove(entry.timer);
        for (const [id, agent] of this._history) {
            if (agent.serverId === entry.server.id)
                this._history.delete(id);
        }
    }

    close() {
        this._closed = true;
        if (this._discoverySource)
            GLib.Source.remove(this._discoverySource);
        this._discoverySource = 0;
        for (const entry of this._entries.values())
            this._remove(entry);
        this._entries.clear();
        this._history.clear();
        this._collector.close();
    }
}
