'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

export class StatusProcess {
    constructor(workerPath) {
        this._workerPath = workerPath;
        this._process = null;
        this._cancellable = new Gio.Cancellable();
        this._busy = false;
        this._closed = false;
        this._failure = null;
        this._deadline = 0;
        this._killSource = 0;
    }

    _start() {
        const gjs = GLib.find_program_in_path('gjs');
        if (!gjs)
            throw new Error('GJS executable not found');
        const process = Gio.Subprocess.new([gjs, '-m', this._workerPath],
            Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE);
        this._process = process;
        this._input = new Gio.DataInputStream({base_stream: process.get_stdout_pipe()});
        this._output = process.get_stdin_pipe();
        process.wait_async(null, (source, result) => {
            source.wait_finish(result);
            if (this._killSource)
                GLib.Source.remove(this._killSource);
            this._killSource = 0;
            this._process = null;
            if (!this._closed && !this._failure)
                this._failure = new Error('Status collector exited; disable and enable the widget to retry');
            this._cancellable.cancel();
        });
    }

    _stopWorker() {
        this._cancellable.cancel();
        if (this._deadline)
            GLib.Source.remove(this._deadline);
        this._deadline = 0;
        if (!this._process || this._killSource)
            return;
        const process = this._process;
        process.send_signal(15);
        this._output.close_async(GLib.PRIORITY_DEFAULT, null, (source, result) => {
            try { source.close_finish(result); } catch {}
        });
        this._killSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 2000, () => {
            this._killSource = 0;
            process.force_exit();
            return GLib.SOURCE_REMOVE;
        });
    }

    close() {
        this._closed = true;
        this._stopWorker();
    }

    async collect() {
        if (this._closed)
            throw new Error('Collector stopped');
        if (this._failure)
            throw this._failure;
        if (this._busy)
            throw new Error('Status collection is already in progress');
        this._busy = true;
        try {
            if (!this._process)
                this._start();
            this._deadline = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 20000, () => {
                this._deadline = 0;
                this._failure = new Error('Status collector did not respond within 20 seconds');
                this._stopWorker();
                return GLib.SOURCE_REMOVE;
            });
            await new Promise((resolve, reject) => {
                this._output.write_all_async(new TextEncoder().encode('collect\n'),
                    GLib.PRIORITY_DEFAULT, this._cancellable, (source, result) => {
                        try { source.write_all_finish(result); resolve(); } catch (error) { reject(error); }
                    });
            });
            const line = await new Promise((resolve, reject) => {
                this._input.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (source, result) => {
                    try { resolve(source.read_line_finish_utf8(result)[0]); } catch (error) { reject(error); }
                });
            });
            if (line === null)
                throw new Error('Status collector closed its output unexpectedly');
            const data = JSON.parse(line);
            if (data.error)
                throw new Error(data.error);
            if (!Array.isArray(data.agents) || !Array.isArray(data.errors) || !data.metrics)
                throw new Error('Invalid status collector response');
            return data;
        } catch (error) {
            if (!this._closed) {
                this._failure ??= error;
                this._stopWorker();
            }
            throw this._failure ?? error;
        } finally {
            if (this._deadline)
                GLib.Source.remove(this._deadline);
            this._deadline = 0;
            this._busy = false;
        }
    }
}
