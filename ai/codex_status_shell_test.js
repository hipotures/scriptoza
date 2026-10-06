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
    const rows = [];
    function findRows(actor) {
        if (actor.has_style_class_name?.('codex-status-row'))
            rows.push(actor);
        for (const child of actor.get_children())
            findRows(child);
    }
    findRows(widget._indicator.menu.box);
    check(rows.length === agents.length && rows.every(row => row.reactive && row.can_focus),
        'Every agent row must support pointer and keyboard activation');
    const focusAgent = widget._focusAgent;
    let activated = null;
    widget._focusAgent = agent => { activated = agent; };
    rows[0].emit('activate', null);
    check(activated?.state === 'blocked', 'Clickable row must navigate to its own agent');
    widget._focusAgent = focusAgent;
    check(widget._indicator.accessible_name.includes('1 Idle'), 'Idle remains in the full agent list');
    widget._indicator.menu.open();
    await pause(700);
    check(widget._panelDots.find(({state}) => state === 'blocked').dot.opacity === 70,
        'Blocked indicator did not blink');
    check(widget._panelDots.find(({state}) => state === 'done').dot.opacity === 255,
        'Done should remain steady while blocked blinks');
    for (const {dot} of widget._panelDots.filter(({state}) => state === 'working'))
        check(dot.opacity === 255, 'Working dots should remain steady while blocked blinks');
    widget._indicator.menu.close();
    widget._render({...data, agents: agents.filter(agent => agent.state !== 'blocked')});
    check(!widget._blinkSource, 'Working agents must not start an animation timer');
    widget._render({...data, agents: [
        {state: 'idle', location: 'first:run:p1'},
        {state: 'idle', location: 'second:run:p1'},
    ]});
    check(widget._indicator.visible && widget._panelDots.length === 2,
        'All idle agents retain individual gray dots and an accessible menu');
    check(widget._panelDots.every(({state, dot}) => state === 'idle' && dot.opacity === 255),
        'Idle dots must remain steady');
    widget._render(data);
    check(widget._panelDots.every(({state}) => state !== 'idle'),
        'Idle dots disappear again when another agent starts working');
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
    await pause(4500);
    check(collector.calls === 1, 'Polled before 5 seconds');
    await pause(900);
    check(collector.calls === 2, 'Did not poll at 5 seconds');
    check(GLib.get_monotonic_time() - pollStarted >= 5000000, 'Polling cadence');
    widget.disable();
    check(!widget._pollSource && !widget._blinkSource && !widget._collector && !widget._indicator,
        'Disable did not release sources and actors');
    print('CODEX_STATUS_SHELL_TEST_PASSED');
}
