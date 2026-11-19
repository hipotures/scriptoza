'use strict';

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const WIDGET_VERSION = '0.0.32';
const PANEL_TOOLTIP_TEXT = 'herdr';

function createStatusDot({color, kind, accessibleName}) {
    const r = parseInt(color.slice(1, 3), 16) / 255;
    const g = parseInt(color.slice(3, 5), 16) / 255;
    const b = parseInt(color.slice(5, 7), 16) / 255;
    const area = new St.DrawingArea({
        width: 12,
        height: 12,
        accessible_name: accessibleName,
        y_align: Clutter.ActorAlign.CENTER,
    });
    area.connect('repaint', () => {
        const cr = area.get_context();
        const [w, h] = area.get_surface_size();
        const unit = Math.min(w, h);
        const cx = w / 2;
        const cy = h / 2;
        const stroke = unit * 0.11;
        const ringRadius = unit * 0.40;
        cr.setSourceRGBA(r, g, b, 1);
        if (kind === 'solid') {
            cr.arc(cx, cy, ringRadius + stroke / 2, 0, 2 * Math.PI);
            cr.fill();
        } else {
            cr.setLineWidth(stroke);
            cr.arc(cx, cy, ringRadius, 0, 2 * Math.PI);
            cr.stroke();
            if (kind === 'ring-dot') {
                cr.arc(cx, cy, unit * 0.16, 0, 2 * Math.PI);
                cr.fill();
            }
        }
        cr.$dispose();
    });
    return area;
}

const {Collector} = await import(`./collector.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {Navigator} = await import(`./navigation.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {StatusProcess} = await import(`./status-process.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {AGENT_TYPES, STATES, sortAgents, summarize} = await import(`./model.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {DENSITIES, PROFILES, loadDensity, saveDensity} = await import(`./density.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {formatUsage} = await import(`./usage-format.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);

export default class CodexStatus extends Extension {
    enable() {
        this._collector = new StatusProcess(this.dir.get_child('status-worker.js').get_path());
        this._navigationCollector = new Collector();
        this._blinkSource = 0;
        this._panelAlignIdle = 0;
        this._rightBoxSignal = 0;
        this._destroyed = false;
        this._indicator = new PanelMenu.Button(0.0, 'Herdr agent status', false);
        this._panelBox = new St.BoxLayout({style_class: 'codex-status-panel'});
        this._panelDots = [];
        this._agentRows = [];
        this._renderKey = null;
        this._footer = null;
        this._usageRows = [];
        this._usage = null;
        this._density = loadDensity();
        this._lastData = null;
        this._icons = Object.fromEntries(['openai.svg', 'openai-light.svg', 'anthropic.svg', 'antigravity.svg'].map(name =>
            [name, new Gio.FileIcon({file: this.dir.resolve_relative_path(`assets/icons/${name}`)})]));
        this._indicator.add_child(this._panelBox);
        this._setupPanelTooltip();
        this._navigator = new Navigator({
            collector: this._navigationCollector,
            getWindowActors: () => global.get_window_actors(),
            activateWindow: window => Main.activateWindow(window),
            closeMenu: () => this._indicator?.menu.close(),
            notifyError: (message, error) => Main.notifyError(message, error?.message ?? String(error)),
        });
        this._indicator.menu.addMenuItem(new PopupMenu.PopupMenuItem('Checking agents…', {reactive: false}));
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
        this._setupPanelOrder();
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
        this._destroyed = true;
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
        this._blinkSource = 0;
        if (this._panelAlignIdle)
            GLib.Source.remove(this._panelAlignIdle);
        this._panelAlignIdle = 0;
        if (this._rightBoxSignal && Main.panel._rightBox)
            Main.panel._rightBox.disconnect(this._rightBoxSignal);
        this._rightBoxSignal = 0;
        this._navigator?.close();
        this._navigator = null;
        this._collector?.close();
        this._collector = null;
        this._navigationCollector = null;
        const panelTooltip = this._panelTooltip;
        this._panelTooltip = null;
        panelTooltip?.destroy();
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
        this._lastData = null;
        this._icons = null;
    }

    _render({agents, errors, updatedAt, usage = null, waitingForServer = false}) {
        this._usage = usage;
        this._lastData = {agents, errors, updatedAt, usage, waitingForServer};
        const sorted = sortAgents(agents);
        // Include navigation identities, including the server boot, so retained
        // rows cannot keep a target from an earlier server instance.
        const renderKey = JSON.stringify([sorted, errors, waitingForServer, this._density]);
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
            const dot = createStatusDot({color: '#f8e45c', kind: 'ring', accessibleName: message});
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
        if (active.length > 0) {
            for (const agent of active) {
                const dot = createStatusDot({
                    color: STATES[agent.state].color,
                    kind: 'solid',
                    accessibleName: `${AGENT_TYPES[agent.agentType].label}: ${agent.location}: ${STATES[agent.state].label}`,
                });
                this._panelBox.add_child(dot);
                this._panelDots.push({state: agent.state, dot});
            }
        } else if (sorted.length > 0) {
            const dot = createStatusDot({
                color: '#b0b0b0',
                kind: 'ring-dot',
                accessibleName: `${sorted.length} ${STATES.idle.label}`,
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'idle', dot});
        } else {
            const dot = createStatusDot({
                color: '#b0b0b0',
                kind: 'ring',
                accessibleName: 'No agents',
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'idle', dot});
        }
        this._indicator.visible = true;
        this._indicator.accessible_name = `Agents: ${Object.entries(summary.counts)
            .filter(([, count]) => count > 0).map(([state, count]) => `${count} ${STATES[state].label}`).join(', ') || 'No agents'}`;
        this._indicator.menu.removeAll();
        this._blockedLabels = [];
        this._agentRows = [];
        this._usageRows = [];

        const profile = PROFILES[this._density];
        const usageSection = new PopupMenu.PopupMenuSection();
        this._indicator.menu.addMenuItem(usageSection);
        for (const agentType of ['claude', 'codex']) {
            const row = new PopupMenu.PopupBaseMenuItem({reactive: false, style_class: 'codex-status-usage-row'});
            row.set_style(`spacing: 8px; padding-top: ${profile.usagePadY}px; padding-bottom: ${profile.usagePadY}px; min-height: 0;`);
            row.x_expand = true;
            const icon = new St.Icon({icon_size: 16, y_align: Clutter.ActorAlign.CENTER,
                accessible_name: AGENT_TYPES[agentType].label});
            row.add_child(icon);
            this._bindIcon(row, icon, agentType);
            const label = new St.Label({y_align: Clutter.ActorAlign.CENTER});
            label.set_style('font-family: monospace; font-size: 0.85em;');
            row.add_child(label);
            usageSection.addMenuItem(row);
            this._usageRows.push({agentType, row, label});
        }
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        const section = new PopupMenu.PopupMenuSection();
        const scroll = new St.ScrollView({style_class: 'codex-status-scroll', overlay_scrollbars: true});
        scroll.set_style(`min-width: ${profile.width}px;`);
        scroll.x_expand = true;
        section.actor.x_expand = true;
        scroll.add_child(section.actor);
        const container = new PopupMenu.PopupMenuSection();
        container.actor.add_child(scroll);
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
            const rowStyle = [profile.gap !== null ? `spacing: ${profile.gap}px;` : '',
                profile.padY !== null ? `padding-top: ${profile.padY}px; padding-bottom: ${profile.padY}px;` : ''].join(' ').trim();
            if (rowStyle)
                row.set_style(rowStyle);
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
                style: `color: ${STATES[agent.state].color}; font-weight: bold;${profile.font ? ` font-size: ${profile.font};` : ''}`,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            textBox.add_child(label);
            const titleLabel = new St.Label({text: agent.sessionTitle || '',
                style: `font-size: ${profile.title}; opacity: 0.75; max-width: ${profile.titleMax}px;`,
                visible: Boolean(agent.sessionTitle)});
            textBox.add_child(titleLabel);
            row.add_child(textBox);
            const tooltip = new St.Label({text: agent.location, style_class: 'dash-label', visible: false});
            Main.uiGroup.add_child(tooltip);
            let tooltipTimeout = 0;
            const cancelTooltip = () => {
                if (tooltipTimeout) {
                    GLib.Source.remove(tooltipTimeout);
                    tooltipTimeout = 0;
                }
                tooltip.hide();
            };
            row.connect('notify::hover', () => {
                cancelTooltip();
                if (!row.hover || !this._indicator?.menu.isOpen)
                    return;
                tooltipTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 600, () => {
                    tooltipTimeout = 0;
                    if (!row.hover || !this._indicator?.menu.isOpen)
                        return GLib.SOURCE_REMOVE;
                    tooltip.visible = true;
                    Main.uiGroup.set_child_above_sibling(tooltip, null);
                    const [x, y] = row.get_transformed_position();
                    const monitor = Main.layoutManager.findMonitorForActor(row);
                    const [, natWidth] = tooltip.get_preferred_width(-1);
                    const width = Math.max(tooltip.width, natWidth);
                    tooltip.set_position(Math.max(monitor.x, Math.min(x,
                        monitor.x + monitor.width - width)), y + row.height);
                    return GLib.SOURCE_REMOVE;
                });
            });
            row.connect('notify::mapped', cancelTooltip);
            row.connect('destroy', () => {
                cancelTooltip();
                tooltip.destroy();
            });
            const statusLabel = new St.Icon({
                icon_name: STATES[agent.state].icon,
                icon_size: 16,
                style: `color: ${STATES[agent.state].color};`,
                accessible_name: STATES[agent.state].label,
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
        this._footer.label.x_expand = true;
        this._footer.add_child(this._buildDensitySwitch());
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
            } else if (agentType === 'agy') {
                name = 'antigravity.svg';
            }
            icon.gicon = this._icons[name];
        };
        row.connect('style-changed', update);
        update();
    }

    _buildDensitySwitch() {
        const icon = new St.Icon({icon_name: 'emblem-system-symbolic', icon_size: 16});
        const button = new St.Button({child: icon, can_focus: true, reactive: true,
            x_align: Clutter.ActorAlign.END, y_align: Clutter.ActorAlign.CENTER,
            accessible_name: `Density: ${this._density}`,
            style: 'padding: 0; margin-right: 8px;', opacity: 180});
        button.connect('clicked', () => {
            this._setDensity(DENSITIES[(DENSITIES.indexOf(this._density) + 1) % DENSITIES.length]);
        });
        return button;
    }

    _setupPanelTooltip() {
        const tooltip = new St.Label({text: PANEL_TOOLTIP_TEXT, style_class: 'dash-label', visible: false});
        Main.uiGroup.add_child(tooltip);
        this._panelTooltip = tooltip;
        const syncTooltip = () => {
            if (!this._indicator || !this._panelTooltip)
                return;
            const show = this._indicator.hover && this._indicator.visible && !this._indicator.menu.isOpen;
            tooltip.visible = show;
            if (show) {
                Main.uiGroup.set_child_above_sibling(tooltip, null);
                const [x, y] = this._indicator.get_transformed_position();
                const monitor = Main.layoutManager.findMonitorForActor(this._indicator);
                const [, natWidth] = tooltip.get_preferred_width(-1);
                const width = Math.max(tooltip.width, natWidth);
                const targetX = Math.round(x + (this._indicator.width - width) / 2);
                tooltip.set_position(
                    Math.max(monitor.x, Math.min(targetX, monitor.x + monitor.width - width)),
                    Math.round(y + this._indicator.height + 4)
                );
            }
        };
        this._indicator.connect('notify::hover', syncTooltip);
        this._indicator.connect('notify::mapped', () => tooltip.hide());
        this._indicator.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen)
                tooltip.hide();
        });
        this._indicator.connect('destroy', () => {
            if (this._panelTooltip === tooltip) {
                this._panelTooltip = null;
                tooltip.destroy();
            }
        });
    }

    _setupPanelOrder() {
        this._alignPanelOrder();
        if (Main.panel._rightBox) {
            this._rightBoxSignal = Main.panel._rightBox.connect('child-added', () => {
                if (this._panelAlignIdle || this._destroyed)
                    return;
                this._panelAlignIdle = GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                    this._panelAlignIdle = 0;
                    if (!this._destroyed)
                        this._alignPanelOrder();
                    return GLib.SOURCE_REMOVE;
                });
            });
        }
    }

    _alignPanelOrder() {
        const box = Main.panel._rightBox;
        if (!box)
            return;
        let index = 0;
        for (const role of ['rtorrent-status@scriptoza', 'codex-status@scriptoza']) {
            const container = Main.panel.statusArea[role]?.container;
            if (!container || container.get_parent() !== box)
                continue;
            if (box.get_child_at_index(index) !== container)
                box.set_child_at_index(container, index);
            index++;
        }
    }

    _setDensity(density) {
        if (density === this._density || !DENSITIES.includes(density))
            return;
        this._density = density;
        try {
            saveDensity(density);
        } catch (error) {
            console.error(`Agent Status: cannot save the density: ${error.message}`);
        }
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (this._indicator && this._lastData)
                this._render(this._lastData);
            return GLib.SOURCE_REMOVE;
        });
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
