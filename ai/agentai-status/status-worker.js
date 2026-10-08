'use strict';

import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';
import GLibUnix from 'gi://GLibUnix';
import System from 'system';

import {Collector} from './collector.js';

const collector = new Collector();
const loop = new GLib.MainLoop(null, false);
const cancellable = new Gio.Cancellable();
const input = new Gio.DataInputStream({base_stream: new GioUnix.InputStream({fd: 0, close_fd: false})});
const output = new GioUnix.OutputStream({fd: 1, close_fd: false});
let stopped = false;
let failed = false;
let signalSource = 0;

function stop() {
    if (!stopped) {
        stopped = true;
        cancellable.cancel();
        collector.close();
    }
}

signalSource = GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, 15, () => {
    signalSource = 0;
    stop();
    return GLib.SOURCE_REMOVE;
});

async function run() {
    while (!stopped) {
        const line = await new Promise((resolve, reject) => {
            input.read_line_async(GLib.PRIORITY_DEFAULT, cancellable, (source, result) => {
                try { resolve(source.read_line_finish_utf8(result)[0]); } catch (error) { reject(error); }
            });
        });
        if (line === null)
            return;
        if (line !== 'collect')
            throw new Error('Invalid status collector request');
        const data = await collector.collect();
        if (stopped)
            return;
        await new Promise((resolve, reject) => {
            output.write_all_async(new TextEncoder().encode(`${JSON.stringify(data)}\n`),
                GLib.PRIORITY_DEFAULT, cancellable, (source, result) => {
                    try { source.write_all_finish(result); resolve(); } catch (error) { reject(error); }
                });
        });
    }
}

run().catch(error => {
    if (!stopped) {
        printerr(`Agent Status worker: ${error.message}`);
        failed = true;
    }
}).finally(() => {
    stop();
    if (signalSource)
        GLib.Source.remove(signalSource);
    loop.quit();
});
loop.run();
if (failed)
    System.exit(1);
