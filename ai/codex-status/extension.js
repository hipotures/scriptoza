'use strict';

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {Collector, POLL_SECONDS} from './collector.js';
import {STATES, sortAgents, summarize} from './model.js';

export default class CodexStatus extends Extension {
    enable() {
        this._collector = new Collector();
        this._busy = false;
        this._blinkSource = 0;
        this._pollSource = 0;
        this._indicator = new PanelMenu.Button(0.0, 'Codex agent status', false);
        this._panelBox = new St.BoxLayout({style_class: 'codex-status-panel'});
        this._panelDots = [];
        this._indicator.add_child(this._panelBox);
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
        this._collector?.close();
        this._collector = null;
        this._indicator?.destroy();
        this._indicator = null;
        this._panelBox = null;
        this._panelDots = [];
        this._blockedDots = [];
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
        const summary = summarize(agents, errors);
        this._panelBox.destroy_all_children();
        this._panelDots = [];
        for (const agent of sortAgents(agents).filter(agent => agent.state !== 'idle')) {
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
        for (const agent of sortAgents(agents)) {
            const row = new PopupMenu.PopupBaseMenuItem({reactive: false, style_class: 'codex-status-row'});
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
        const performance = metrics
            ? `Updated ${new Date().toLocaleTimeString()} · ${Math.round(metrics.totalMs)} ms · JSON ${metrics.parseMs.toFixed(2)} ms`
            : 'Update failed';
        const footer = new PopupMenu.PopupMenuItem(performance, {reactive: false});
        footer.label.add_style_class_name('codex-status-footer');
        this._indicator.menu.addMenuItem(footer);
        this._updateAnimation();
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
