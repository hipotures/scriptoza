'use strict';

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const WIDGET_VERSION = '0.0.17';

const {Collector} = await import(`./collector.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {Navigator} = await import(`./navigation.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {StatusProcess} = await import(`./status-process.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {AGENT_TYPES, STATES, sortAgents, summarize} = await import(`./model.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {formatUsage} = await import(`./usage-format.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);

export default class CodexStatus extends Extension {
    enable() {
        this._collector = new StatusProcess(this.dir.get_child('status-worker.js').get_path());
        this._navigationCollector = new Collector();
        this._blinkSource = 0;
        this._indicator = new PanelMenu.Button(0.0, 'Herdr agent status', false);
        this._panelBox = new St.BoxLayout({style_class: 'codex-status-panel'});
        this._panelDots = [];
        this._agentRows = [];
        this._renderKey = null;
        this._footer = null;
        this._usageRows = [];
        this._usage = null;
        this._icons = Object.fromEntries(['openai.svg', 'openai-light.svg', 'anthropic.svg'].map(name =>
            [name, new Gio.FileIcon({file: this.dir.resolve_relative_path(`assets/icons/${name}`)})]));
        this._indicator.add_child(this._panelBox);
        this._navigator = new Navigator({
            collector: this._navigationCollector,
            getWindowActors: () => global.get_window_actors(),
            activateWindow: window => Main.activateWindow(window),
            closeMenu: () => this._indicator?.menu.close(),
            notifyError: (message, error) => Main.notifyError(message, error?.message ?? String(error)),
        });
        this._indicator.menu.addMenuItem(new PopupMenu.PopupMenuItem('Checking agents…', {reactive: false}));
        Main.panel.addToStatusArea(this.uuid, this._indicator);
        this._indicator.visible = false;
        const collector = this._collector;
        collector.start(result => {
            if (this._collector === collector)
                this._render(result);
        }, error => {
            if (this._collector === collector) {
                console.error(`Agent Status: ${error.message}`);
                this._render({agents: [], errors: [{machine: 'Herdr', message: error.message}], updatedAt: null});
            }
        });
    }

    disable() {
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
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
        this._blockedLabels = [];
        this._renderKey = null;
        this._footer = null;
        this._usageRows = [];
        this._usage = null;
        this._icons = null;
    }

    _render({agents, errors, updatedAt, usage = null, waitingForServer = false}) {
        this._usage = usage;
        const sorted = sortAgents(agents);
        // Include navigation identities, including the server boot, so retained
        // rows cannot keep a target from an earlier server instance.
        const renderKey = JSON.stringify([sorted, errors, waitingForServer]);
        if (renderKey === this._renderKey) {
            this._updateFooter(updatedAt);
            this._updateUsage();
            return;
        }
        const summary = summarize(agents, errors);
        this._panelBox.destroy_all_children();
        this._panelDots = [];
        if (waitingForServer) {
            const message = 'Waiting for the Herdr server to start';
            const dot = new St.Label({text: '○', style: 'color: #f8e45c;',
                accessible_name: message, y_align: Clutter.ActorAlign.CENTER});
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'waiting', dot});
            this._indicator.visible = true;
            this._indicator.accessible_name = message;
            this._indicator.menu.removeAll();
            this._indicator.menu.addMenuItem(new PopupMenu.PopupMenuItem(message, {reactive: false}));
            this._blockedLabels = [];
            this._agentRows = [];
            this._usageRows = [];
            this._footer = null;
            this._updateAnimation();
            this._renderKey = renderKey;
            return;
        }
        const active = sorted.filter(agent => agent.state !== 'idle');
        for (const agent of active.length ? active : sorted) {
            const dot = new St.Label({text: '●', style: `color: ${STATES[agent.state].color};`,
                accessible_name: `${AGENT_TYPES[agent.agentType].label}: ${agent.location}: ${STATES[agent.state].label}`,
                y_align: Clutter.ActorAlign.CENTER});
            this._panelBox.add_child(dot);
            this._panelDots.push({state: agent.state, dot});
        }
        this._indicator.visible = this._panelDots.length > 0;
        this._indicator.accessible_name = `Agents: ${Object.entries(summary.counts)
            .filter(([, count]) => count > 0).map(([state, count]) => `${count} ${STATES[state].label}`).join(', ') || 'No agents'}`;
        this._indicator.menu.removeAll();
        this._blockedLabels = [];
        this._agentRows = [];
        this._usageRows = [];

        const usageSection = new PopupMenu.PopupMenuSection();
        const usageContainer = new PopupMenu.PopupBaseMenuItem({reactive: false});
        usageContainer.add_child(usageSection.actor);
        for (const agentType of ['claude', 'codex']) {
            const row = new PopupMenu.PopupBaseMenuItem({reactive: false, style_class: 'codex-status-usage-row',
                style: 'spacing: 8px; padding-top: 0; padding-bottom: 0; min-height: 0;'});
            row.x_expand = true;
            const icon = new St.Icon({icon_size: 16, y_align: Clutter.ActorAlign.CENTER,
                accessible_name: AGENT_TYPES[agentType].label});
            row.add_child(icon);
            this._bindIcon(row, icon, agentType);
            const label = new St.Label({style_class: 'codex-status-usage',
                style: 'font-size: 0.85em; color: #b0b0b0;', y_align: Clutter.ActorAlign.CENTER});
            row.add_child(label);
            usageSection.addMenuItem(row);
            this._usageRows.push({agentType, row, label});
        }
        this._indicator.menu.addMenuItem(usageContainer);
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
            row.accessible_name = `${agent.displayName}: ${agent.sessionTitle ? `${agent.sessionTitle}: ` : ''}${STATES[agent.state].label}`;
            // PopupBaseMenuItem closes its menu after emitting `activate`. Keep
            // the menu open until the asynchronous client and window checks
            // have both succeeded.
            row.activate = () => {
                this._navigator?.focus(agent);
            };
            const icon = new St.Icon({icon_size: 16, y_align: Clutter.ActorAlign.CENTER,
                accessible_name: AGENT_TYPES[agent.agentType].label});
            row.add_child(icon);
            this._bindIcon(row, icon, agent.agentType);
            const textBox = new St.BoxLayout({orientation: Clutter.Orientation.VERTICAL, x_expand: true,
                y_align: Clutter.ActorAlign.CENTER});
            const label = new St.Label({
                text: agent.displayName,
                style: `color: ${STATES[agent.state].color}; font-weight: bold;`,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            textBox.add_child(label);
            const titleLabel = new St.Label({text: agent.sessionTitle || '',
                style: 'font-size: 0.85em; opacity: 0.75; max-width: 360px;',
                visible: Boolean(agent.sessionTitle)});
            textBox.add_child(titleLabel);
            row.add_child(textBox);
            const tooltip = new St.Label({text: agent.location, style_class: 'dash-label', visible: false});
            Main.uiGroup.add_child(tooltip);
            row.connect('notify::hover', () => {
                tooltip.visible = row.hover && this._indicator.menu.isOpen;
                if (tooltip.visible) {
                    const [x, y] = row.get_transformed_position();
                    const monitor = Main.layoutManager.findMonitorForActor(row);
                    tooltip.set_position(Math.max(monitor.x, Math.min(x,
                        monitor.x + monitor.width - tooltip.width)), y + row.height);
                }
            });
            row.connect('notify::mapped', () => { tooltip.hide(); });
            row.connect('destroy', () => tooltip.destroy());
            const statusLabel = new St.Label({
                text: STATES[agent.state].label,
                style: `color: ${STATES[agent.state].color};`,
                y_align: Clutter.ActorAlign.CENTER,
            });
            row.add_child(statusLabel);
            this._agentRows.push({agent, row, icon, textBox, label, titleLabel, tooltip, statusLabel});
            section.addMenuItem(row);
            if (agent.state === 'blocked')
                this._blockedLabels.push(label, statusLabel);
        }
        if (!agents.length)
            section.addMenuItem(new PopupMenu.PopupMenuItem('No agents found', {reactive: false}));

        for (const error of errors) {
            const row = new PopupMenu.PopupMenuItem(`${error.machine}: unavailable`, {reactive: false});
            row.label.add_style_class_name('codex-status-error');
            this._indicator.menu.addMenuItem(row);
        }
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._footer = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._footer.label.add_style_class_name('codex-status-footer');
        this._indicator.menu.addMenuItem(this._footer);
        this._updateFooter(updatedAt);
        this._updateUsage();
        this._updateAnimation();
        this._renderKey = renderKey;
    }

    _bindIcon(row, icon, agentType) {
        const update = () => {
            let name = 'anthropic.svg';
            if (agentType === 'codex') {
                const color = row.get_theme_node().get_foreground_color();
                const brightness = 0.2126 * color.red + 0.7152 * color.green + 0.0722 * color.blue;
                name = brightness > 128 ? 'openai-light.svg' : 'openai.svg';
            }
            icon.gicon = this._icons[name];
        };
        row.connect('style-changed', update);
        update();
    }

    _updateFooter(updatedAt) {
        if (!this._footer)
            return;
        const time = updatedAt
            ? new Date(updatedAt).toLocaleTimeString('en-GB', {
                hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
            }) : '—';
        this._footer.label.text = `Last update: ${time} · v${WIDGET_VERSION}`;
    }

    _updateUsage() {
        const now = Date.now() / 1000;
        for (const {agentType, row, label} of this._usageRows) {
            const text = formatUsage(this._usage?.[agentType], now);
            label.text = text;
            row.visible = text !== '';
        }
    }

    _updateAnimation() {
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
        this._blinkSource = 0;
        for (const {dot} of this._panelDots) {
            dot.remove_all_transitions();
            dot.opacity = 255;
        }
        const waiting = this._panelDots.some(({state}) => state === 'waiting');
        if (!waiting && !this._panelDots.some(({state}) => state === 'blocked'))
            return;
        let dim = false;
        this._blinkSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, waiting ? 1500 : 600, () => {
            dim = !dim;
            for (const {state, dot} of this._panelDots) {
                if (state === 'waiting')
                    dot.ease({opacity: dim ? 70 : 255, duration: 1200, mode: Clutter.AnimationMode.EASE_IN_OUT_SINE});
                else if (state === 'blocked')
                    dot.opacity = dim ? 70 : 255;
            }
            for (const label of this._blockedLabels)
                label.opacity = dim ? 70 : 255;
            return GLib.SOURCE_CONTINUE;
        });
    }
}
