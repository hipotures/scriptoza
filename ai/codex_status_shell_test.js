'use strict';

import Gio from 'gi://Gio';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const HELPER_APP_ID = 'org.scriptoza.CodexStatusWindowTest';
const HERDR_WINDOW_MARKER = '[herdr-client:client-window-test]';
const UNRELATED_WINDOW_TITLE = 'Other terminal window';

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

function windowTitle(window) {
    return window.get_title() ?? '';
}

function windowWorkspaceIndex(window) {
    return window.get_workspace().index();
}

function focusedWindow() {
    if (typeof global.display.get_focus_window === 'function')
        return global.display.get_focus_window();
    return global.display.focus_window;
}

async function waitForHelperWindows() {
    for (let attempt = 0; attempt < 50; attempt++) {
        const windows = global.get_window_actors().map(actor => actor.meta_window);
        const target = windows.find(window => windowTitle(window).includes(HERDR_WINDOW_MARKER));
        const unrelated = windows.find(window => windowTitle(window) === UNRELATED_WINDOW_TITLE);
        if (target && unrelated)
            return {target, unrelated};
        await pause(100);
    }
    throw new Error('GTK window helper did not create both test windows');
}

function startWindowHelper() {
    const source = `
imports.gi.versions.Gtk = '4.0';
const Gtk = imports.gi.Gtk;

const app = new Gtk.Application({application_id: '${HELPER_APP_ID}'});
app.connect('activate', application => {
    const windows = [
        ['Herdr Codex ${HERDR_WINDOW_MARKER}', 'Herdr target'],
        ['${UNRELATED_WINDOW_TITLE}', 'Unrelated terminal'],
    ];
    for (const [title, label] of windows) {
        const window = new Gtk.ApplicationWindow({application});
        window.set_title(title);
        window.set_default_size(320, 180);
        window.set_child(new Gtk.Label({label}));
        window.present();
    }
});
app.run([]);
`;
    return Gio.Subprocess.new(['gjs', '-c', source], Gio.SubprocessFlags.NONE);
}

async function testRealWindowActivation(extension) {
    const helper = startWindowHelper();
    try {
        const {target, unrelated} = await waitForHelperWindows();
        const manager = global.workspace_manager;
        while (manager.n_workspaces < 2)
            manager.append_new_workspace(false, global.get_current_time());
        const targetWorkspace = manager.get_workspace_by_index(0);
        const unrelatedWorkspace = manager.get_workspace_by_index(1);
        target.change_workspace(targetWorkspace);
        unrelated.change_workspace(unrelatedWorkspace);
        Main.activateWindow(unrelated);
        await pause(200);
        check(windowWorkspaceIndex(target) === targetWorkspace.index(),
            'Target window was not placed on the first workspace');
        check(windowWorkspaceIndex(unrelated) === unrelatedWorkspace.index(),
            'Unrelated window was not placed on the second workspace');
        check(manager.get_active_workspace().index() === unrelatedWorkspace.index(),
            'Test setup did not switch to the unrelated window workspace');

        const {Navigator, clientWindowToken} = await import(extension.dir.get_child('navigation.js').get_uri());
        const calls = [];
        const activatedWindows = [];
        const navigator = new Navigator({
            readJson: async args => {
                calls.push(args);
                const response = {
                    client_id: 'client-window-test',
                    window_token: clientWindowToken('client-window-test'),
                    boot_id: 'boot-1',
                };
                return args.includes('--check') ? response : {...response, focused: true};
            },
            getWindowActors: () => global.get_window_actors(),
            activateWindow: window => {
                activatedWindows.push(window);
                Main.activateWindow(window);
            },
            closeMenu: () => {},
            notifyError: (message, error) => { throw new Error(`${message}: ${error.message}`); },
        });
        const focused = await navigator.focus({
            serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1',
            location: 'Local/project:run:p3',
        });
        await pause(200);
        check(focused, 'Navigator did not acknowledge real-window focus');
        check(calls.length === 2 && calls[0].includes('--check'),
            'Navigator did not perform check and focus requests');
        check(manager.get_active_workspace().index() === targetWorkspace.index(),
            'Main.activateWindow did not switch to the target workspace');
        check(windowWorkspaceIndex(target) === targetWorkspace.index(),
            'Activating the target moved it between workspaces');
        check(windowWorkspaceIndex(unrelated) === unrelatedWorkspace.index(),
            'Activating the target moved the unrelated window');
        check(activatedWindows.length === 1 && activatedWindows[0] === target,
            'Main.activateWindow was not called with the uniquely matched Herdr window');
        const actualFocus = focusedWindow();
        if (actualFocus)
            check(actualFocus === target, 'Main.activateWindow focused the wrong window');
    } finally {
        helper.send_signal(15);
        await pause(100);
    }
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
        .map((state, index) => ({state, bootId: 'boot-1', location: `gpu/phase${index}:run:p1`}));
    agents.push({state: 'working', bootId: 'boot-1', location: 'gpu/second:run:p1'});
    const data = {agents, errors: [],
        metrics: {totalMs: 300, parseMs: 0.3}};
    for (let index = 0; index < 30; index++)
        widget._render(data);
    check(widget._indicator.menu._getMenuItems().at(-1).label.text.endsWith(' · v0.0.3'),
        'Menu footer did not display the loaded widget version');
    const retainedRows = widget._agentRows.map(({row}) => row);
    const retainedDots = widget._panelDots.map(({dot}) => dot);
    const retainedBlink = widget._blinkSource;
    widget._render({...data, agents: agents.map(agent => ({...agent})),
        metrics: {totalMs: 321, parseMs: 0.42}});
    check(widget._agentRows.every(({row}, index) => row === retainedRows[index]) &&
        widget._panelDots.every(({dot}, index) => dot === retainedDots[index]),
        'Unchanged polling rebuilt panel dots or interactive rows');
    check(widget._blinkSource === retainedBlink && widget._footer.label.text.includes('321 ms · JSON 0.42 ms'),
        'Unchanged polling restarted blinking or failed to update the footer');
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
    check(widget._agentRows.length === agents.length, 'One interactive row per agent');
    check(widget._agentRows.every(({row}) => row.reactive && row.can_focus && row.track_hover),
        'Agent rows support pointer hover and keyboard focus');
    const navigated = [];
    widget._navigator = {
        busy: false,
        focus: async agent => { navigated.push(agent.location); return false; },
        close() {},
    };
    widget._indicator.menu.open();
    widget._agentRows[0].row.hover = true;
    check(widget._agentRows[0].row.active, 'Hover highlights the whole row');
    check(widget._agentRows[0].row.has_style_pseudo_class('selected'),
        'Hover applies the native whole-row selection state');
    widget._agentRows[0].row.grab_key_focus();
    const focusedRow = widget._agentRows[0].row;
    widget._render(data);
    check(widget._agentRows[0].row === focusedRow && global.stage.get_key_focus() === focusedRow && focusedRow.active,
        'Unchanged polling lost the hovered or keyboard-focused row');
    const keyboard = global.stage.context.get_backend().get_default_seat().create_virtual_device(
        Clutter.InputDeviceType.KEYBOARD_DEVICE);
    const keyTime = GLib.get_monotonic_time();
    keyboard.notify_keyval(keyTime, Clutter.KEY_Return, Clutter.KeyState.PRESSED);
    keyboard.notify_keyval(keyTime + 1, Clutter.KEY_Return, Clutter.KeyState.RELEASED);
    const [rowX, rowY] = widget._agentRows[0].row.get_transformed_position();
    if (Number.isFinite(rowX) && Number.isFinite(rowY)) {
        const pointer = global.stage.context.get_backend().get_default_seat().create_virtual_device(
            Clutter.InputDeviceType.POINTER_DEVICE);
        const pointerTime = keyTime + 2;
        pointer.notify_absolute_motion(pointerTime, rowX + 10, rowY + 10);
        pointer.notify_button(pointerTime + 1, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.PRESSED);
        pointer.notify_button(pointerTime + 2, Clutter.BUTTON_PRIMARY, Clutter.ButtonState.RELEASED);
    } else {
        // Headless Shell can map the popup before allocating its row actors.
        widget._agentRows[0].row.activate();
    }
    await pause(50);
    check(navigated.length === 2 && widget._indicator.menu.isOpen,
        'Mouse and keyboard activation stay asynchronous and keep failures visible');
    widget._indicator.menu.close();
    let targetData = {...data, agents: [{id: 'local/w1:p3', serverId: 'local', paneId: 'w1:p3',
        bootId: 'boot-1', state: 'working', location: 'project:run:p3'}]};
    widget._render(targetData);
    for (const patch of [{bootId: 'boot-2'}, {serverId: 'gpu-id'}, {paneId: 'w2:p3'},
        {location: 'other:run:p3'}, {state: 'done'}]) {
        const previousRow = widget._agentRows[0].row;
        targetData = {...targetData, agents: [{...targetData.agents[0], ...patch}]};
        widget._render(targetData);
        check(widget._agentRows[0].row !== previousRow, 'Changed target or status retained a stale row');
        check(widget._agentRows[0].agent === targetData.agents[0], 'Row did not receive the current target');
    }
    widget._render({...targetData, errors: [{machine: 'Herdr', message: 'Unavailable'}]});
    check(widget._indicator.menu._getMenuItems().some(item => item.label?.text === 'Herdr: unavailable'),
        'Changed errors failed to update the menu');
    await testRealWindowActivation(extension);
    await Promise.all([widget._refresh(), widget._refresh()]);
    check(collector.calls === 1, 'Overlapping refreshes were not suppressed');
    const pollStarted = GLib.get_monotonic_time();
    widget._pollSource && GLib.Source.remove(widget._pollSource);
    widget._pollSource = 0;
    widget.disable();
    check(!widget._blinkSource && !widget._collector && !widget._indicator &&
        widget._renderKey === null && widget._footer === null, 'Disable leaked state');
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
