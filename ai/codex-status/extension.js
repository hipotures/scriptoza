'use strict';

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const WIDGET_VERSION = '0.0.4';

const {Collector, POLL_SECONDS} = await import(`./collector.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {Navigator} = await import(`./navigation.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {StatusProcess} = await import(`./status-process.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {STATES, sortAgents, summarize} = await import(`./model.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);

export default class CodexStatus extends Extension {
    enable() {
        this._collector = new StatusProcess(this.dir.get_child('status-worker.js').get_path());
        this._navigationCollector = new Collector();
        this._busy = false;
        this._blinkSource = 0;
        this._pollSource = 0;
        this._indicator = new PanelMenu.Button(0.0, 'Codex agent status', false);
        this._panelBox = new St.BoxLayout({style_class: 'codex-status-panel'});
        this._panelDots = [];
        this._agentRows = [];
        this._renderKey = null;
        this._footer = null;
        this._indicator.add_child(this._panelBox);
        this._navigator = new Navigator({
            collector: this._navigationCollector,
            getWindowActors: () => global.get_window_actors(),
            activateWindow: window => Main.activateWindow(window),
            closeMenu: () => this._indicator?.menu.close(),
            notifyError: (message, error) => Main.notifyError(message, error?.message ?? String(error)),
        });
        this._indicator.menu.addMenuItem(new PopupMenu.PopupMenuItem('Checking Codex agents…', {reactive: false}));
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._indicator.visible = false;
        this._refresh();
        this._pollSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, POLL_SECONDS * 1000, () => {
            this._refresh();
            return GLib.SOURCE_CONTINUE;
        });
    }

    disable() {
        if (this._pollSource)
            GLib.Source.remove(this._pollSource);
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
        this._pollSource = 0;
        this._blinkSource = 0;
        this._navigator?.close();
        this._navigator = null;
        this._collector?.close();
        this._collector = null;
        this._navigationCollector = null;
        this._indicator?.destroy();
        this._indicator = null;
        this._panelBox = null;
        this._panelDots = [];
        this._agentRows = [];
        this._blockedDots = [];
        this._renderKey = null;
        this._footer = null;
    }

    async _refresh() {
        if (this._busy || !this._collector)
            return;
        this._busy = true;
        const collector = this._collector;
        try {
            const result = await collector.collect();
            if (this._collector === collector)
                this._render(result);
        } catch (error) {
            if (this._collector === collector) {
                console.error(`Codex Status: ${error.message}`);
                this._render({agents: [], errors: [{machine: 'Herdr', message: error.message}], metrics: null});
            }
        } finally {
            if (this._collector === collector)
                this._busy = false;
        }
    }

    _render({agents, errors, metrics}) {
        const sorted = sortAgents(agents);
        // Include navigation identities, including the server boot, so retained
        // rows cannot keep a target from an earlier server instance.
        const renderKey = JSON.stringify([sorted, errors]);
        if (renderKey === this._renderKey) {
            this._updateFooter(metrics);
            return;
        }
        const summary = summarize(agents, errors);
        this._panelBox.destroy_all_children();
        this._panelDots = [];
        const active = sorted.filter(agent => agent.state !== 'idle');
        for (const agent of active.length ? active : sorted) {
            const dot = new St.Label({text: '●', style: `color: ${STATES[agent.state].color};`,
                accessible_name: `${agent.location}: ${STATES[agent.state].label}`,
                y_align: Clutter.ActorAlign.CENTER});
            this._panelBox.add_child(dot);
            this._panelDots.push({state: agent.state, dot});
        }
        this._indicator.visible = this._panelDots.length > 0;
        this._indicator.accessible_name = `Codex: ${Object.entries(summary.counts)
            .filter(([, count]) => count > 0).map(([state, count]) => `${count} ${STATES[state].label}`).join(', ') || 'No agents'}`;
        this._indicator.menu.removeAll();
        this._blockedDots = [];
        this._agentRows = [];

        const heading = new PopupMenu.PopupMenuItem(`${summary.total} Codex agents`, {reactive: false});
        heading.label.add_style_class_name('codex-status-heading');
        this._indicator.menu.addMenuItem(heading);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const section = new PopupMenu.PopupMenuSection();
        const scroll = new St.ScrollView({style_class: 'codex-status-scroll', overlay_scrollbars: true});
        scroll.add_child(section.actor);
        const container = new PopupMenu.PopupBaseMenuItem({reactive: false});
        container.add_child(scroll);
        this._indicator.menu.addMenuItem(container);
        for (const agent of sorted) {
            const row = new PopupMenu.PopupBaseMenuItem({
                reactive: true,
                activate: true,
                hover: true,
                can_focus: true,
                style_class: 'codex-status-row',
            });
            row.x_expand = true;
            row.accessible_name = agent.location;
            // PopupBaseMenuItem closes its menu after emitting `activate`. Keep
            // the menu open until the asynchronous client and window checks
            // have both succeeded.
            row.activate = () => {
                this._navigator?.focus(agent);
            };
            this._agentRows.push({agent, row});
            const dot = new St.Label({
                text: agent.state === 'offline' ? '⊗' : '●',
                style: `color: ${STATES[agent.state].color};`,
                y_align: Clutter.ActorAlign.CENTER,
            });
            row.add_child(dot);
            row.add_child(new St.Label({text: agent.location, x_expand: true, y_align: Clutter.ActorAlign.CENTER}));
            row.add_child(new St.Label({
                text: STATES[agent.state].label,
                style: `color: ${STATES[agent.state].color};`,
                y_align: Clutter.ActorAlign.CENTER,
            }));
            section.addMenuItem(row);
            if (agent.state === 'blocked')
                this._blockedDots.push(dot);
        }
        if (!agents.length)
            section.addMenuItem(new PopupMenu.PopupMenuItem('No Codex agents found', {reactive: false}));

        for (const error of errors) {
            const row = new PopupMenu.PopupMenuItem(`${error.machine}: unavailable`, {reactive: false});
            row.label.add_style_class_name('codex-status-error');
            this._indicator.menu.addMenuItem(row);
        }
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._footer = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._footer.label.add_style_class_name('codex-status-footer');
        this._indicator.menu.addMenuItem(this._footer);
        this._updateFooter(metrics);
        this._updateAnimation();
        this._renderKey = renderKey;
    }

    _updateFooter(metrics) {
        const performance = metrics
            ? `Updated ${new Date().toLocaleTimeString()} · ${Math.round(metrics.totalMs)} ms · JSON ${metrics.parseMs.toFixed(2)} ms`
            : 'Update failed';
        this._footer.label.text = `${performance} · v${WIDGET_VERSION}`;
    }

    _updateAnimation() {
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
        this._blinkSource = 0;
        for (const {dot} of this._panelDots) {
            dot.remove_all_transitions();
            dot.opacity = 255;
        }
        if (!this._panelDots.some(({state}) => state === 'blocked'))
            return;
        let dim = false;
        this._blinkSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600, () => {
            dim = !dim;
            for (const {state, dot} of this._panelDots) {
                if (state === 'blocked')
                    dot.opacity = dim ? 70 : 255;
            }
            for (const dot of this._blockedDots)
                dot.opacity = dim ? 70 : 255;
            return GLib.SOURCE_CONTINUE;
        });
    }
}
