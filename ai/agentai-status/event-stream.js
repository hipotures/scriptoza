'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const LIFECYCLE = ['pane.created', 'pane.closed', 'pane.exited', 'pane.agent_detected',
    'pane.updated', 'pane.moved', 'workspace.renamed', 'tab.renamed'];

export function subscriptions(paneIds) {
    return [...LIFECYCLE.map(type => ({type})), ...paneIds.map(pane_id =>
        ({type: 'pane.agent_status_changed', pane_id}))];
}

function quote(value) {
    return `'${value.replaceAll("'", "'\\''")}'`;
}

export function remoteCommand(server) {
    if (!/^[a-f0-9]{32}$/.test(server.id) || typeof server.target !== 'string' ||
        !server.target || server.target.startsWith('-') || typeof server.session !== 'string')
        throw new Error('Invalid saved SSH machine');
    const stateHome = GLib.getenv('XDG_STATE_HOME') || `${GLib.get_home_dir()}/.local/state`;
    const path = `${stateHome}/herdr/client/ssh-metadata/${server.id}.json`;
    const [, bytes] = GLib.file_get_contents(path);
    const cache = JSON.parse(new TextDecoder().decode(bytes));
    if (cache.version !== 1 || cache.target !== server.target || cache.session !== server.session ||
        !['linux', 'macos'].includes(cache.metadata?.os) ||
        !cache.metadata.executable?.startsWith('/'))
        throw new Error('Missing POSIX Herdr SSH metadata; reconnect this machine with Herdr');
    const config = GLib.canonicalize_filename(GLib.getenv('HERDR_CONFIG_PATH') ||
        `${GLib.getenv('XDG_CONFIG_HOME') || `${GLib.get_home_dir()}/.config`}/herdr/config.toml`, null);
    const checksum = new GLib.Checksum(GLib.ChecksumType.SHA256);
    checksum.update(new TextEncoder().encode(`${config}\0${server.target}`));
    const uid = Gio.File.new_for_path('/proc/self').query_info('unix::uid',
        Gio.FileQueryInfoFlags.NONE, null).get_attribute_uint32('unix::uid');
    const controlDir = `/tmp/hssh-${uid}`;
    const info = Gio.File.new_for_path(controlDir).query_info('unix::uid,unix::mode,standard::type',
        Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    if (info.get_file_type() !== Gio.FileType.DIRECTORY ||
        info.get_attribute_uint32('unix::uid') !== uid ||
        (info.get_attribute_uint32('unix::mode') & 0o077) !== 0)
        throw new Error('Unsafe Herdr SSH control directory');
    // Use the same namespace and target hash as Herdr's managed OpenSSH pool.
    const controlPath = `${controlDir}/${checksum.get_string().slice(0, 24)}-%C`;
    return ['ssh', '-T', '-S', controlPath, '-o', 'ControlMaster=no', '-o', 'BatchMode=yes',
        '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3', server.target,
        `exec ${quote(cache.metadata.executable)} --session ${quote(server.session)} remote-api-bridge`];
}

export class EventStream {
    constructor(server, herdr, paneIds, onReady, onEvent, onError) {
        this._closed = false;
        this._cancellable = new Gio.Cancellable();
        this._process = null;
        this._deadline = 0;
        this._run(server, herdr, paneIds, onReady, onEvent).catch(error => {
            if (!this._closed) {
                this.close();
                onError(error);
            }
        });
    }

    async _run(server, herdr, paneIds, onReady, onEvent) {
        const command = server.id === 'local' ? [herdr, 'remote-api-bridge'] : remoteCommand(server);
        // timeout owns the entire bridge/SSH process group, without an idle deadline.
        const process = Gio.Subprocess.new(['timeout', '--kill-after=1s', '0', ...command],
            Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        this._process = process;
        this._deadline = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 10000, () => {
            this._deadline = 0;
            this._cancellable.cancel();
            return GLib.SOURCE_REMOVE;
        });
        const request = JSON.stringify({id: 'widget-events', method: 'events.subscribe',
            params: {subscriptions: subscriptions(paneIds)}});
        const output = process.get_stdin_pipe();
        await new Promise((resolve, reject) => {
            output.write_all_async(new TextEncoder().encode(`${request}\n`), GLib.PRIORITY_DEFAULT,
                this._cancellable, (source, result) => {
                    try { source.write_all_finish(result); resolve(); } catch (error) { reject(error); }
                });
        });
        const input = new Gio.DataInputStream({base_stream: process.get_stdout_pipe()});
        let ready = false;
        while (!this._closed) {
            const line = await new Promise((resolve, reject) => {
                input.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (source, result) => {
                    try { resolve(source.read_line_finish_utf8(result)[0]); } catch (error) { reject(error); }
                });
            });
            if (line === null)
                throw new Error('Herdr event connection closed');
            const data = JSON.parse(line);
            if (data.error)
                throw new Error(data.error.code || data.error.message || 'Herdr event subscription failed');
            if (!ready) {
                if (data.result?.type !== 'subscription_started')
                    throw new Error('Invalid Herdr subscription acknowledgement');
                ready = true;
                GLib.Source.remove(this._deadline);
                this._deadline = 0;
                onReady();
            } else {
                onEvent(data);
            }
        }
    }

    close() {
        this._closed = true;
        this._cancellable.cancel();
        if (this._deadline)
            GLib.Source.remove(this._deadline);
        this._deadline = 0;
        this._process?.send_signal(15);
        this._process?.wait_async(null, (source, result) => source.wait_finish(result));
        this._process = null;
    }
}
