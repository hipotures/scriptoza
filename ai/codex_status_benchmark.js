'use strict';

import GLib from 'gi://GLib';
import System from 'system';

import {Collector, POLL_SECONDS} from './codex-status/collector.js';

const loop = new GLib.MainLoop(null, false);
const collector = new Collector();

async function benchmark() {
    const samples = [];
    for (let index = 0; index < 3; index++) {
        const result = await collector.collect();
        samples.push(result.metrics);
        print(JSON.stringify({sample: index + 1, agents: result.agents.length,
            ignoredMachines: result.ignoredMachines, ...result.metrics}));
        if (index < 2) {
            await new Promise(resolve => {
                GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_SECONDS * 1000, () => {
                    resolve();
                    return GLib.SOURCE_REMOVE;
                });
            });
        }
    }
    const mean = key => samples.reduce((sum, sample) => sum + sample[key], 0) / samples.length;
    print(JSON.stringify({samples: samples.length, meanTotalMs: mean('totalMs'),
        meanParseMs: mean('parseMs'), meanBytes: mean('bytes'), meanRequests: mean('requests'),
        firstTotalMs: samples[0].totalMs,
        offlineSkippedMeanTotalMs: (samples[1].totalMs + samples[2].totalMs) / 2}));
}

let failed = false;
benchmark().catch(error => {
    printerr(error.stack);
    failed = true;
}).finally(() => {
    collector.close();
    loop.quit();
});
loop.run();
if (failed)
    System.exit(1);
