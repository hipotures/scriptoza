'use strict';

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const WIDGET_VERSION = '0.0.1';

const {DENSITIES, PROFILES, loadConfig, saveDensity} = await import(`./config.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {STATES, formatRate, formatTorrentSubtitle, normalizeTorrent, sortTorrents, summarizeTorrents} = await import(`./model.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {fetchTorrents} = await import(`./scgi.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);

export default class RTorrentStatus extends Extension {
    enable() {
        this._pollSource = 0;
        this._blinkSource = 0;
        this._panelAlignIdle = 0;
        this._rightBoxSignal = 0;
        this._destroyed = false;
        this._polling = false;
        this._config = loadConfig();
        this._density = this._config.density;
        this._lastData = null;
        this._renderKey = null;
        this._panelDots = [];
        this._errorLabels = [];
        this._footer = null;

        this._indicator = new PanelMenu.Button(0.0, 'rTorrent status', false);
        this._panelBox = new St.BoxLayout({style_class: 'rtorrent-status-panel'});
        this._indicator.add_child(this._panelBox);
        this._setupPanelTooltip();
        this._indicator.menu.addMenuItem(new PopupMenu.PopupMenuItem('Checking rTorrent…', {reactive: false}));
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
        this._setupPanelOrder();

        this._pollOnce();
        this._schedulePoll();
    }

    disable() {
        this._destroyed = true;
        if (this._pollSource)
            GLib.Source.remove(this._pollSource);
        this._pollSource = 0;
        if (this._blinkSource)
            GLib.Source.remove(this._blinkSource);
        this._blinkSource = 0;
        if (this._panelAlignIdle)
            GLib.Source.remove(this._panelAlignIdle);
        this._panelAlignIdle = 0;
        if (this._rightBoxSignal && Main.panel._rightBox)
            Main.panel._rightBox.disconnect(this._rightBoxSignal);
        this._rightBoxSignal = 0;
        const panelTooltip = this._panelTooltip;
        this._panelTooltip = null;
        panelTooltip?.destroy();
        this._indicator?.destroy();
        this._indicator = null;
        this._panelBox = null;
        this._panelDots = [];
        this._errorLabels = [];
        this._footer = null;
        this._renderKey = null;
        this._lastData = null;
    }

    _schedulePoll() {
        if (this._pollSource)
            GLib.Source.remove(this._pollSource);
        const interval = Math.max(1, this._config?.pollSeconds ?? 3);
        this._pollSource = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, interval, () => {
            this._pollOnce();
            return GLib.SOURCE_CONTINUE;
        });
    }

    async _pollOnce() {
        if (this._destroyed || this._polling)
            return;
        this._polling = true;
        try {
            const latestConfig = loadConfig();
            const intervalChanged = latestConfig.pollSeconds !== this._config.pollSeconds;
            this._config = latestConfig;
            this._density = latestConfig.density;
            if (this._panelTooltip)
                this._panelTooltip.text = latestConfig.name;
            if (intervalChanged && !this._destroyed)
                this._schedulePoll();

            const rawRows = await fetchTorrents({
                host: latestConfig.host,
                port: latestConfig.port,
                timeoutSeconds: Math.max(2, Math.min(10, latestConfig.pollSeconds)),
            });
            if (this._destroyed)
                return;
            const torrents = rawRows.map(normalizeTorrent);
            this._render({
                torrents,
                error: null,
                host: latestConfig.host,
                port: latestConfig.port,
                updatedAt: Date.now(),
            });
        } catch (error) {
            if (this._destroyed)
                return;
            this._render({
                torrents: [],
                error: error?.message ?? String(error),
                host: this._config.host,
                port: this._config.port,
                updatedAt: Date.now(),
            });
        } finally {
            this._polling = false;
        }
    }

    _render({torrents, error, host, port, updatedAt}) {
        this._lastData = {torrents, error, host, port, updatedAt};
        const sorted = sortTorrents(torrents);
        const summary = summarizeTorrents(sorted);
        const renderKey = JSON.stringify([sorted, error, host, port, this._density]);
        if (renderKey === this._renderKey) {
            this._updateFooter(summary, updatedAt);
            return;
        }

        this._panelBox.destroy_all_children();
        this._panelDots = [];
        this._errorLabels = [];
        this._indicator.menu.removeAll();

        if (error) {
            const message = `${host}:${port} unavailable`;
            const dot = new St.Label({
                text: '○',
                style: 'color: #f8e45c;',
                accessible_name: message,
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'waiting', dot});
            this._indicator.visible = true;
            this._indicator.accessible_name = message;

            const errorItem = new PopupMenu.PopupMenuItem(`${host}:${port}: ${error}`, {reactive: false});
            errorItem.label.add_style_class_name('rtorrent-status-error');
            this._indicator.menu.addMenuItem(errorItem);
            this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            this._addFooter(summary, updatedAt);
            this._updateAnimation();
            this._renderKey = renderKey;
            return;
        }

        const active = sorted.filter(torrent => torrent.state !== 'paused');
        const panelTorrents = active.length ? active : sorted;
        if (panelTorrents.length === 0) {
            const dot = new St.Label({
                text: '○',
                style: 'color: #9a9996;',
                accessible_name: 'No torrents',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'paused', dot});
        } else {
            for (const torrent of panelTorrents) {
                const dot = new St.Label({
                    text: '●',
                    style: `color: ${STATES[torrent.state].color};`,
                    accessible_name: `${torrent.name}: ${STATES[torrent.state].label}`,
                    y_align: Clutter.ActorAlign.CENTER,
                });
                this._panelBox.add_child(dot);
                this._panelDots.push({state: torrent.state, dot});
            }
        }
        this._indicator.visible = true;
        this._indicator.accessible_name = `rTorrent (${host}:${port}): ${Object.entries(summary.counts)
            .filter(([, count]) => count > 0)
            .map(([state, count]) => `${count} ${STATES[state].label}`)
            .join(', ') || 'No torrents'}`;

        const profile = PROFILES[this._density];
        const section = new PopupMenu.PopupMenuSection();
        const scroll = new St.ScrollView({style_class: 'rtorrent-status-scroll', overlay_scrollbars: true});
        scroll.set_style(`min-width: ${profile.width}px;`);
        scroll.x_expand = true;
        section.actor.x_expand = true;
        scroll.add_child(section.actor);

        const container = new PopupMenu.PopupMenuSection();
        container.actor.add_child(scroll);
        this._indicator.menu.addMenuItem(container);

        for (const torrent of sorted) {
            const row = new PopupMenu.PopupBaseMenuItem({
                reactive: true,
                activate: false,
                hover: true,
                can_focus: true,
                style_class: 'rtorrent-status-row',
            });
            row.x_expand = true;
            const rowStyle = [
                profile.gap !== null ? `spacing: ${profile.gap}px;` : '',
                profile.padY !== null ? `padding-top: ${profile.padY}px; padding-bottom: ${profile.padY}px;` : '',
            ].join(' ').trim();
            if (rowStyle)
                row.set_style(rowStyle);
            row.accessible_name = `${torrent.name}: ${STATES[torrent.state].label}`;

            const leftIcon = new St.Icon({
                icon_name: 'folder-download-symbolic',
                icon_size: 16,
                y_align: Clutter.ActorAlign.CENTER,
                style: 'opacity: 0.75;',
            });
            row.add_child(leftIcon);

            const textBox = new St.BoxLayout({
                orientation: Clutter.Orientation.VERTICAL,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const nameLabel = new St.Label({
                text: torrent.name,
                style: `color: ${STATES[torrent.state].color}; font-weight: bold; max-width: ${profile.titleMax}px;${profile.font ? ` font-size: ${profile.font};` : ''}`,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            textBox.add_child(nameLabel);

            const subtitleLabel = new St.Label({
                text: formatTorrentSubtitle(torrent),
                style: `font-size: ${profile.title}; opacity: 0.75; max-width: ${profile.titleMax}px;`,
            });
            textBox.add_child(subtitleLabel);
            row.add_child(textBox);

            const statusIcon = new St.Icon({
                icon_name: STATES[torrent.state].icon,
                icon_size: 16,
                style: `color: ${STATES[torrent.state].color};`,
                accessible_name: STATES[torrent.state].label,
                y_align: Clutter.ActorAlign.CENTER,
            });
            row.add_child(statusIcon);

            const tooltipText = torrent.message
                ? `${host}:${port} · ${torrent.hash}\n${torrent.message}`
                : `${host}:${port} · ${torrent.hash}`;
            const tooltip = new St.Label({text: tooltipText, style_class: 'dash-label', visible: false});
            Main.uiGroup.add_child(tooltip);
            row.connect('notify::hover', () => {
                tooltip.visible = row.hover && this._indicator.menu.isOpen;
                if (tooltip.visible) {
                    const [x, y] = row.get_transformed_position();
                    const monitor = Main.layoutManager.findMonitorForActor(row);
                    tooltip.set_position(
                        Math.max(monitor.x, Math.min(x, monitor.x + monitor.width - tooltip.width)),
                        y + row.height
                    );
                }
            });
            row.connect('notify::mapped', () => { tooltip.hide(); });
            row.connect('destroy', () => tooltip.destroy());

            section.addMenuItem(row);
            if (torrent.state === 'error')
                this._errorLabels.push(nameLabel, statusIcon);
        }

        if (!sorted.length)
            section.addMenuItem(new PopupMenu.PopupMenuItem('No torrents', {reactive: false}));

        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addFooter(summary, updatedAt);
        this._updateAnimation();
        this._renderKey = renderKey;
    }

    _addFooter(summary, updatedAt) {
        this._footer = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._footer.label.add_style_class_name('rtorrent-status-footer');
        this._footer.label.x_expand = true;
        this._footer.add_child(this._buildDensitySwitch());
        this._indicator.menu.addMenuItem(this._footer);
        this._updateFooter(summary, updatedAt);
    }

    _buildDensitySwitch() {
        const icon = new St.Icon({icon_name: 'emblem-system-symbolic', icon_size: 16});
        const button = new St.Button({
            child: icon,
            can_focus: true,
            reactive: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: `Density: ${this._density}`,
            style: 'padding: 0; margin-right: 8px;',
            opacity: 180,
        });
        button.connect('clicked', () => {
            this._setDensity(DENSITIES[(DENSITIES.indexOf(this._density) + 1) % DENSITIES.length]);
        });
        return button;
    }

    _setupPanelTooltip() {
        const tooltip = new St.Label({text: this._config.name, style_class: 'dash-label', visible: false});
        Main.uiGroup.add_child(tooltip);
        this._panelTooltip = tooltip;
        const syncTooltip = () => {
            if (!this._indicator || !this._panelTooltip)
                return;
            const show = this._indicator.hover && this._indicator.visible && !this._indicator.menu.isOpen;
            tooltip.visible = show;
            if (show) {
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
            console.error(`rTorrent Status: cannot save density: ${error.message}`);
        }
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (this._indicator && this._lastData)
                this._render(this._lastData);
            return GLib.SOURCE_REMOVE;
        });
    }

    _updateFooter(summary, updatedAt) {
        if (!this._footer)
            return;
        const time = updatedAt
            ? new Date(updatedAt).toLocaleTimeString('en-GB', {
                hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
            }) : '—';
        const down = formatRate(summary?.totalDownRate ?? 0);
        const up = formatRate(summary?.totalUpRate ?? 0);
        this._footer.label.text = `↓ ${down}  ↑ ${up} · ${time} · v${WIDGET_VERSION}`;
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
        const hasError = this._panelDots.some(({state}) => state === 'error');
        if (!waiting && !hasError)
            return;
        let dim = false;
        this._blinkSource = GLib.timeout_add(GLib.PRIORITY_DEFAULT, waiting ? 1500 : 600, () => {
            dim = !dim;
            for (const {state, dot} of this._panelDots) {
                if (state === 'waiting')
                    dot.ease({opacity: dim ? 70 : 255, duration: 1200, mode: Clutter.AnimationMode.EASE_IN_OUT_SINE});
                else if (state === 'error')
                    dot.opacity = dim ? 70 : 255;
            }
            for (const label of this._errorLabels)
                label.opacity = dim ? 70 : 255;
            return GLib.SOURCE_CONTINUE;
        });
    }
}
