'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import * as Model from './model.js';

const modelRevision = import.meta.url.match(/\?.*$/)?.[0] ?? '';
let cleanText = Model.cleanText;
let normalizeAgents = Model.normalizeAgents;
const modelReady = modelRevision
    ? import(`./model.js${modelRevision}`).then(module => {
        cleanText = module.cleanText;
        normalizeAgents = module.normalizeAgents;
    })
    : Promise.resolve();

export const POLL_SECONDS = 5;
const OFFLINE_RETRY_SECONDS = 60;

export class Collector {
    constructor() {
        this._herdr = GLib.find_program_in_path('herdr');
        const userBinary = GLib.build_filenamev([GLib.get_home_dir(), '.local', 'bin', 'herdr']);
        if (!this._herdr && GLib.file_test(userBinary, GLib.FileTest.IS_EXECUTABLE))
            this._herdr = userBinary;
        this._timeout = GLib.find_program_in_path('timeout');
        this._processes = new Set();
        this._servers = [{id: 'local', label: 'Local'}];
        this._retryAfter = new Map();
        this._closed = false;
    }

    close() {
        this._closed = true;
        for (const process of this._processes)
            process.send_signal(15);
        this._servers = [];
        this._retryAfter.clear();
    }

    async _readJson(args, metrics) {
        if (this._closed)
            throw new Error('Collector stopped');
        if (!this._herdr)
            throw new Error('herdr executable not found');
        if (!this._timeout)
            throw new Error('GNU timeout executable not found');
        // timeout owns a process group, including Herdr's SSH subprocesses.
        const process = Gio.Subprocess.new([this._timeout, '--kill-after=1s', '8s', this._herdr, ...args],
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE);
        this._processes.add(process);
        metrics.requests++;
        try {
            const [stdout, stderr] = await new Promise((resolve, reject) => {
                process.communicate_utf8_async(null, null, (source, result) => {
                    try {
                        const [, output, error] = source.communicate_utf8_finish(result);
                        resolve([output, error]);
                    } catch (error) {
                        reject(error);
                    }
                });
            });
            if (process.get_if_exited() && process.get_exit_status() === 124)
                throw new Error('Herdr request timed out after 8 seconds');
            if (!process.get_successful())
                throw new Error(cleanText(stderr).slice(0, 240) || 'Herdr request failed');
            const start = GLib.get_monotonic_time();
            const data = JSON.parse(stdout);
            metrics.parseMs += (GLib.get_monotonic_time() - start) / 1000;
            metrics.bytes += new TextEncoder().encode(stdout).length;
            return data;
        } finally {
            this._processes.delete(process);
        }
    }

    async readJson(args) {
        return this._readJson(args, {requests: 0, bytes: 0, parseMs: 0, totalMs: 0});
    }

    async collect() {
        await modelReady;
        const start = GLib.get_monotonic_time();
        const metrics = {requests: 0, bytes: 0, parseMs: 0, totalMs: 0};
        const errors = [];
        const ignoredMachines = [];
        let servers;
        try {
            const profiles = await this._readJson(['machine', 'list', '--json'], metrics);
            if (!Array.isArray(profiles) || profiles.some(profile =>
                typeof profile.id !== 'string' || typeof profile.label !== 'string' ||
                typeof profile.enabled !== 'boolean'))
                throw new Error('Invalid Herdr machine list');
            servers = [{id: 'local', label: 'Local'}, ...profiles.filter(profile => profile.enabled)];
            if (!this._closed)
                this._servers = servers;
        } catch (error) {
            errors.push({serverId: 'discovery', machine: 'Herdr', message: error.message});
            servers = this._servers;
        }
        const serverIds = new Set(servers.map(server => server.id));
        for (const id of this._retryAfter.keys()) {
            if (!serverIds.has(id))
                this._retryAfter.delete(id);
        }
        const reachable = servers.filter(server => {
            if ((this._retryAfter.get(server.id) ?? 0) > GLib.get_monotonic_time()) {
                ignoredMachines.push(cleanText(server.label));
                return false;
            }
            return true;
        });
        const results = await Promise.all(reachable.map(async server => {
            try {
                const prefix = server.id === 'local' ? [] : ['--machine', server.id];
                const data = await this._readJson([...prefix, 'api', 'snapshot'], metrics);
                const agents = normalizeAgents(data.result?.snapshot, server);
                this._retryAfter.delete(server.id);
                return {server, agents};
            } catch (error) {
                if (server.id === 'local')
                    errors.push({serverId: server.id, machine: 'Local', message: error.message});
                else {
                    ignoredMachines.push(cleanText(server.label));
                    if (!this._closed)
                        this._retryAfter.set(server.id, GLib.get_monotonic_time() + OFFLINE_RETRY_SECONDS * 1000000);
                }
                return {server, agents: []};
            }
        }));
        metrics.totalMs = (GLib.get_monotonic_time() - start) / 1000;
        return {agents: results.flatMap(result => result.agents), errors, ignoredMachines, metrics};
    }
}
