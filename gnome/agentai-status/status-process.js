'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export class StatusProcess {
    constructor(workerPath) {
        this._workerPath = workerPath;
        this._process = null;
        this._cancellable = new Gio.Cancellable();
        this._closed = false;
        this._killSource = 0;
    }

    start(onUpdate, onError) {
        if (this._process || this._closed)
            throw new Error('Status worker has already started or stopped');
        const gjs = GLib.find_program_in_path('gjs');
        if (!gjs)
            throw new Error('GJS executable not found');
        const process = Gio.Subprocess.new([gjs, '-m', this._workerPath],
            Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE);
        this._process = process;
        const input = new Gio.DataInputStream({base_stream: process.get_stdout_pipe()});
        process.wait_async(null, (source, result) => {
            source.wait_finish(result);
            if (this._killSource)
                GLib.Source.remove(this._killSource);
            this._killSource = 0;
            this._process = null;
        });
        this._read(input, onUpdate).catch(error => {
            if (!this._closed) {
                this.close();
                onError(error);
            }
        });
    }

    async _read(input, onUpdate) {
        while (!this._closed) {
            const line = await new Promise((resolve, reject) => {
                input.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (source, result) => {
                    try { resolve(source.read_line_finish_utf8(result)[0]); } catch (error) { reject(error); }
                });
            });
            if (line === null)
                throw new Error('Status worker closed its output unexpectedly; reload the widget to retry');
            const data = JSON.parse(line);
            if (!Array.isArray(data.agents) || !Array.isArray(data.errors) || !data.metrics)
                throw new Error('Invalid status worker response');
            onUpdate(data);
        }
    }

    close() {
        this._closed = true;
        this._cancellable.cancel();
        if (!this._process || this._killSource)
            return;
        const process = this._process;
        process.send_signal(15);
        process.get_stdin_pipe().close_async(GLib.PRIORITY_DEFAULT, null, (source, result) => {
            try { source.close_finish(result); } catch {}
        });
        this._killSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2000, () => {
            this._killSource = 0;
            process.force_exit();
            return GLib.SOURCE_REMOVE;
        });
    }
}
