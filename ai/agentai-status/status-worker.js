'use strict';

import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
import GLib from 'gi://GLib';
import GLibUnix from 'gi://GLibUnix';
import System from 'system';

import {EventMonitor} from './event-monitor.js';

const loop = new GLib.MainLoop(null, false);
const cancellable = new Gio.Cancellable();
const input = new GioUnix.InputStream({fd: 0, close_fd: false});
const output = new GioUnix.OutputStream({fd: 1, close_fd: false});
let stopped = false;
let failed = false;
let signalSource = 0;
let writing = false;
let pending = null;

function stop() {
    if (stopped)
        return;
    stopped = true;
    cancellable.cancel();
    monitor.close();
    if (signalSource)
        GLib.Source.remove(signalSource);
    signalSource = 0;
    loop.quit();
}

async function publish(data) {
    pending = data;
    if (writing || stopped)
        return;
    writing = true;
    try {
        while (pending && !stopped) {
            const bytes = new TextEncoder().encode(`${JSON.stringify(pending)}\n`);
            pending = null;
            await new Promise((resolve, reject) => {
                output.write_all_async(bytes, GLib.PRIORITY_DEFAULT, cancellable, (source, result) => {
                    try { source.write_all_finish(result); resolve(); } catch (error) { reject(error); }
                });
            });
        }
    } catch (error) {
        if (!stopped) {
            printerr(`Agent Status worker: ${error.message}`);
            failed = true;
            stop();
        }
    } finally {
        writing = false;
    }
}

const monitor = new EventMonitor(publish);
signalSource = GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, 15, () => {
    signalSource = 0;
    stop();
    return GLib.SOURCE_REMOVE;
});
// The parent owns stdin. EOF also stops bridges if the Shell disappears.
input.read_bytes_async(1, GLib.PRIORITY_DEFAULT, cancellable, (source, result) => {
    try { source.read_bytes_finish(result); } catch {}
    stop();
});
monitor.start();
loop.run();
if (failed)
    System.exit(1);
