'use strict';

import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

function pause(milliseconds) {
    return new Promise(resolve => {
        GLib.timeout_add(GLib.PRIORITY_DEFAULT, milliseconds, () => {
            resolve();
            return GLib.SOURCE_REMOVE;
        });
    });
}

function check(condition, message) {
    if (!condition)
        throw new Error(message);
}

export async function run() {
    await pause(1500);
    const extension = Main.extensionManager.lookup('codex-status@scriptoza');
    check(extension?.state === 1, 'Extension did not enable');
    await (await import(extension.dir.get_child('reload.js').get_uri())).reload();
    const widget = extension.stateObj;
    widget._collector.close();
    const collector = {close() {}, calls: 0, async collect() {
        this.calls++;
        await pause(200);
        return {agents: [], errors: [], metrics: null};
    }};
    widget._collector = collector;
    widget._busy = false;
    const agents = ['idle', 'working', 'done', 'blocked', 'unknown']
        .map((state, index) => ({state, location: `gpu/phase${index}:run:p1`}));
    agents.push({state: 'working', location: 'gpu/second:run:p1'});
    const data = {agents, errors: [],
        metrics: {totalMs: 300, parseMs: 0.3}};
    for (let index = 0; index < 30; index++)
        widget._render(data);
    check(widget._indicator.menu.box.get_n_children() === 5, 'Menu leaked children');
    check(widget._panelDots.length === 5 && widget._panelBox.get_n_children() === 5,
        'One dot per non-idle agent, no terminal icon or counters');
    check(widget._panelDots.filter(({state}) => state === 'working').length === 2,
        'Agents sharing the same status have separate dots');
    for (const {state, dot} of widget._panelDots)
        check(state !== 'idle' && dot.text === '●', 'Panel contains only dots, with idle hidden');
    check(widget._indicator.accessible_name.includes('1 Idle'), 'Idle remains in the full agent list');
    widget._indicator.menu.open();
    await pause(700);
    check(widget._panelDots.find(({state}) => state === 'blocked').dot.opacity === 70,
        'Blocked indicator did not blink');
    check(widget._panelDots.find(({state}) => state === 'done').dot.opacity === 255,
        'Done should remain steady while blocked blinks');
    widget._indicator.menu.close();
    check(collector.calls === 0, 'Opening the menu triggered a poll');
    await Promise.all([widget._refresh(), widget._refresh()]);
    check(collector.calls === 1, 'Overlapping refreshes were not suppressed');
    const pollStarted = GLib.get_monotonic_time();
    widget._pollSource && GLib.Source.remove(widget._pollSource);
    widget._pollSource = 0;
    widget.disable();
    check(!widget._blinkSource && !widget._collector && !widget._indicator, 'Disable leaked state');
    widget.enable();
    widget._collector.close();
    widget._collector = collector;
    widget._busy = false;
    await pause(9500);
    check(collector.calls === 1, 'Polled before 10 seconds');
    await pause(900);
    check(collector.calls === 2, 'Did not poll at 10 seconds');
    check(GLib.get_monotonic_time() - pollStarted >= 10000000, 'Polling cadence');
    widget.disable();
    check(!widget._pollSource && !widget._blinkSource && !widget._collector && !widget._indicator,
        'Disable did not release sources and actors');
    print('CODEX_STATUS_SHELL_TEST_PASSED');
}
