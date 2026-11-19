'use strict';

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const WIDGET_VERSION = '0.0.1';

const {DENSITIES, PROFILES, SORT_DIRS, SORT_FIELDS, SORT_LABELS, loadConfig, parseServerSpec, saveAnonymize, saveDensity, saveServers, saveSort} = await import(`./config.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
const {STATES, anonymizeTorrent, formatRate, formatTorrentSubtitle, formatTorrentTooltip, normalizeTorrent, sortTorrents, summarizeTorrents} = await import(`./model.js${import.meta.url.match(/\?.*$/)?.[0] ?? ''}`);
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
        this._sortBy = this._config.sortBy;
        this._sortDir = this._config.sortDir;
        this._anonymize = this._config.anonymize;
        this._servers = this._config.servers;
        this._activeServer = this._config.activeServer;
        this._settingsOpen = false;
        this._serverEditor = null;
        this._anonSalt = Math.floor(Math.random() * 0x7fffffff);
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
            this._sortBy = latestConfig.sortBy;
            this._sortDir = latestConfig.sortDir;
            this._anonymize = latestConfig.anonymize;
            this._servers = latestConfig.servers;
            this._activeServer = latestConfig.activeServer;
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
            const torrents = rawRows.map((row, index) => normalizeTorrent(row, index));
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

    _render({torrents, error, host, port, updatedAt}, force = false) {
        this._lastData = {torrents, error, host, port, updatedAt};
        const sorted = sortTorrents(torrents, this._sortBy, this._sortDir);
        const summary = summarizeTorrents(sorted);
        if (this._serverEditor && !force) {
            this._updateFooter(summary, updatedAt);
            return;
        }
        const renderKey = JSON.stringify([
            sorted, error, host, port,
            this._density, this._sortBy, this._sortDir, this._anonymize,
            this._settingsOpen, this._serverEditor, this._servers, this._activeServer,
        ]);
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
            if (this._settingsOpen)
                this._addSettingsSection();
            this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
            this._addFooter(summary, updatedAt);
            this._updateAnimation();
            this._renderKey = renderKey;
            return;
        }

        const active = sorted.filter(torrent => torrent.state !== 'paused');
        if (active.length > 0) {
            for (const torrent of active) {
                const displayName = this._anonymize ? anonymizeTorrent(torrent, this._anonSalt).name : torrent.name;
                const dot = new St.Label({
                    text: '●',
                    style: `color: ${STATES[torrent.state].color};`,
                    accessible_name: `${displayName}: ${STATES[torrent.state].label}`,
                    y_align: Clutter.ActorAlign.CENTER,
                });
                this._panelBox.add_child(dot);
                this._panelDots.push({state: torrent.state, dot});
            }
        } else if (sorted.length > 0) {
            const dot = new St.Bin({
                width: 11,
                height: 11,
                style: 'border: 1.5px solid #9a9996; border-radius: 99px;',
                child: new St.Widget({
                    width: 3,
                    height: 3,
                    style: 'background-color: #9a9996; border-radius: 99px;',
                    x_expand: false,
                    y_expand: false,
                    x_align: Clutter.ActorAlign.CENTER,
                    y_align: Clutter.ActorAlign.CENTER,
                }),
                accessible_name: `${sorted.length} ${STATES.paused.label}`,
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'paused', dot});
        } else {
            const dot = new St.Label({
                text: '○',
                style: 'color: #9a9996;',
                accessible_name: 'No torrents',
                y_align: Clutter.ActorAlign.CENTER,
            });
            this._panelBox.add_child(dot);
            this._panelDots.push({state: 'paused', dot});
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
            const anon = this._anonymize ? anonymizeTorrent(torrent, this._anonSalt) : null;
            const displayName = anon ? anon.name : torrent.name;
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
            row.accessible_name = `${displayName}: ${STATES[torrent.state].label}`;

            const textBox = new St.BoxLayout({
                orientation: Clutter.Orientation.VERTICAL,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const nameLabel = new St.Label({
                text: displayName,
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

            const tooltip = new St.Label({text: formatTorrentTooltip(torrent), style_class: 'dash-label', visible: false});
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
                    tooltip.set_position(
                        Math.max(monitor.x, Math.min(x, monitor.x + monitor.width - width)),
                        Math.round(y + row.height + 2)
                    );
                    return GLib.SOURCE_REMOVE;
                });
            });
            row.connect('notify::mapped', cancelTooltip);
            row.connect('destroy', () => {
                cancelTooltip();
                tooltip.destroy();
            });

            section.addMenuItem(row);
            if (torrent.state === 'error')
                this._errorLabels.push(nameLabel, statusIcon);
        }

        if (!sorted.length)
            section.addMenuItem(new PopupMenu.PopupMenuItem('No torrents', {reactive: false}));

        if (this._settingsOpen)
            this._addSettingsSection();

        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._addFooter(summary, updatedAt);
        this._updateAnimation();
        this._renderKey = renderKey;
    }

    _addSettingsSection() {
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const settingsSection = new PopupMenu.PopupMenuSection();
        this._indicator.menu.addMenuItem(settingsSection);

        const pillBase = 'padding: 2px 8px; margin-left: 4px; font-size: 0.85em; border-radius: 4px;';
        const pillInactive = `${pillBase} background-color: rgba(255, 255, 255, 0.08);`;
        const pillActive = `${pillBase} background-color: rgba(53, 132, 228, 0.4); color: #ffffff; font-weight: bold;`;

        const currentServer = this._servers[this._activeServer] ?? {host: this._config.host, port: this._config.port};
        const serverRow = new PopupMenu.PopupBaseMenuItem({reactive: false});
        serverRow.add_child(new St.Label({text: 'Server', x_expand: true, y_align: Clutter.ActorAlign.CENTER}));
        if (this._servers.length > 1) {
            const prevServerBtn = new St.Button({
                child: new St.Label({text: '‹', y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: pillInactive,
                accessible_name: 'Previous server',
            });
            prevServerBtn.connect('clicked', () => {
                const idx = (this._activeServer - 1 + this._servers.length) % this._servers.length;
                this._setServers(this._servers, idx);
            });
            serverRow.add_child(prevServerBtn);
        }
        const serverBtn = new St.Button({
            child: new St.Label({
                text: `${currentServer.host}:${currentServer.port}`,
                y_align: Clutter.ActorAlign.CENTER,
                style: 'max-width: 190px;',
            }),
            can_focus: true,
            reactive: true,
            style: this._serverEditor === 'edit' ? pillActive : pillInactive,
            accessible_name: `Edit server ${currentServer.host}:${currentServer.port}`,
        });
        serverBtn.connect('clicked', () => {
            this._serverEditor = this._serverEditor === 'edit' ? null : 'edit';
            this._scheduleRender(true);
        });
        serverRow.add_child(serverBtn);
        if (this._servers.length > 1) {
            const nextServerBtn = new St.Button({
                child: new St.Label({text: '›', y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: pillInactive,
                accessible_name: 'Next server',
            });
            nextServerBtn.connect('clicked', () => {
                const idx = (this._activeServer + 1) % this._servers.length;
                this._setServers(this._servers, idx);
            });
            serverRow.add_child(nextServerBtn);
        }
        const addServerBtn = new St.Button({
            child: new St.Label({text: '+', y_align: Clutter.ActorAlign.CENTER}),
            can_focus: true,
            reactive: true,
            style: this._serverEditor === 'add' ? pillActive : pillInactive,
            accessible_name: 'Add server',
        });
        addServerBtn.connect('clicked', () => {
            this._serverEditor = this._serverEditor === 'add' ? null : 'add';
            this._scheduleRender(true);
        });
        serverRow.add_child(addServerBtn);
        if (this._servers.length > 1) {
            const removeServerBtn = new St.Button({
                child: new St.Label({text: '✕', y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: pillInactive,
                accessible_name: 'Remove server',
            });
            removeServerBtn.connect('clicked', () => {
                const nextServers = this._servers.filter((_s, i) => i !== this._activeServer);
                const nextIdx = Math.min(this._activeServer, nextServers.length - 1);
                this._serverEditor = null;
                this._setServers(nextServers, nextIdx);
            });
            serverRow.add_child(removeServerBtn);
        }
        settingsSection.addMenuItem(serverRow);

        if (this._serverEditor) {
            const editorRow = new PopupMenu.PopupBaseMenuItem({reactive: false});
            const entry = new St.Entry({
                text: this._serverEditor === 'edit' ? `${currentServer.host}:${currentServer.port}` : '',
                hint_text: 'host:port',
                can_focus: true,
                x_expand: true,
                style: 'min-width: 180px; font-size: 0.9em;',
            });
            const submit = () => {
                const parsed = parseServerSpec(entry.text);
                if (!parsed)
                    return;
                const nextServers = [...this._servers];
                let nextIdx = this._activeServer;
                if (this._serverEditor === 'add') {
                    nextServers.push(parsed);
                    nextIdx = nextServers.length - 1;
                } else {
                    nextServers[this._activeServer] = parsed;
                }
                this._serverEditor = null;
                this._setServers(nextServers, nextIdx);
            };
            entry.clutter_text.connect('activate', submit);
            const saveBtn = new St.Button({
                child: new St.Label({text: 'Save', y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: pillActive,
                accessible_name: 'Save server',
            });
            saveBtn.connect('clicked', submit);
            const cancelBtn = new St.Button({
                child: new St.Label({text: '✕', y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: pillInactive,
                accessible_name: 'Cancel',
            });
            cancelBtn.connect('clicked', () => {
                this._serverEditor = null;
                this._scheduleRender(true);
            });
            editorRow.add_child(entry);
            editorRow.add_child(saveBtn);
            editorRow.add_child(cancelBtn);
            settingsSection.addMenuItem(editorRow);
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (entry.mapped)
                    entry.grab_key_focus();
                return GLib.SOURCE_REMOVE;
            });
        }

        const sizeRow = new PopupMenu.PopupBaseMenuItem({reactive: false});
        sizeRow.add_child(new St.Label({text: 'Size', x_expand: true, y_align: Clutter.ActorAlign.CENTER}));
        const densityLabels = {large: 'Large', medium: 'Medium', compact: 'Compact'};
        for (const density of DENSITIES) {
            const btn = new St.Button({
                child: new St.Label({text: densityLabels[density], y_align: Clutter.ActorAlign.CENTER}),
                can_focus: true,
                reactive: true,
                style: density === this._density ? pillActive : pillInactive,
                accessible_name: `Size: ${densityLabels[density]}`,
            });
            btn.connect('clicked', () => this._setDensity(density));
            sizeRow.add_child(btn);
        }
        settingsSection.addMenuItem(sizeRow);

        const sortRow = new PopupMenu.PopupBaseMenuItem({reactive: false});
        sortRow.add_child(new St.Label({text: 'Sort', x_expand: true, y_align: Clutter.ActorAlign.CENTER}));
        const prevBtn = new St.Button({
            child: new St.Label({text: '‹', y_align: Clutter.ActorAlign.CENTER}),
            can_focus: true,
            reactive: true,
            style: pillInactive,
            accessible_name: 'Previous sort field',
        });
        prevBtn.connect('clicked', () => {
            const idx = SORT_FIELDS.indexOf(this._sortBy);
            const prev = SORT_FIELDS[(idx - 1 + SORT_FIELDS.length) % SORT_FIELDS.length];
            this._setSort(prev, this._sortDir);
        });
        const fieldBtn = new St.Button({
            child: new St.Label({text: SORT_LABELS[this._sortBy] ?? this._sortBy, y_align: Clutter.ActorAlign.CENTER}),
            can_focus: true,
            reactive: true,
            style: pillActive,
            accessible_name: `Sort by: ${SORT_LABELS[this._sortBy] ?? this._sortBy}`,
        });
        fieldBtn.connect('clicked', () => {
            const next = SORT_FIELDS[(SORT_FIELDS.indexOf(this._sortBy) + 1) % SORT_FIELDS.length];
            this._setSort(next, this._sortDir);
        });
        const nextBtn = new St.Button({
            child: new St.Label({text: '›', y_align: Clutter.ActorAlign.CENTER}),
            can_focus: true,
            reactive: true,
            style: pillInactive,
            accessible_name: 'Next sort field',
        });
        nextBtn.connect('clicked', () => {
            const next = SORT_FIELDS[(SORT_FIELDS.indexOf(this._sortBy) + 1) % SORT_FIELDS.length];
            this._setSort(next, this._sortDir);
        });
        const dirBtn = new St.Button({
            child: new St.Label({text: this._sortDir === 'desc' ? '↓ Desc' : '↑ Asc', y_align: Clutter.ActorAlign.CENTER}),
            can_focus: true,
            reactive: true,
            style: pillInactive,
            accessible_name: `Sort direction: ${this._sortDir}`,
        });
        dirBtn.connect('clicked', () => {
            this._setSort(this._sortBy, this._sortDir === 'asc' ? 'desc' : 'asc');
        });
        sortRow.add_child(prevBtn);
        sortRow.add_child(fieldBtn);
        sortRow.add_child(nextBtn);
        sortRow.add_child(dirBtn);
        settingsSection.addMenuItem(sortRow);

        const anonRow = new PopupMenu.PopupSwitchMenuItem('Anonymize', this._anonymize);
        anonRow.connect('toggled', (_item, state) => this._setAnonymize(state));
        settingsSection.addMenuItem(anonRow);
    }

    _addFooter(summary, updatedAt) {
        this._footer = new PopupMenu.PopupMenuItem('', {reactive: false});
        this._footer.label.add_style_class_name('rtorrent-status-footer');
        this._footer.label.x_expand = true;
        this._footer.add_child(this._buildSettingsButton());
        this._indicator.menu.addMenuItem(this._footer);
        this._updateFooter(summary, updatedAt);
    }

    _buildSettingsButton() {
        const icon = new St.Icon({icon_name: 'emblem-system-symbolic', icon_size: 16});
        const button = new St.Button({
            child: icon,
            can_focus: true,
            reactive: true,
            x_align: Clutter.ActorAlign.END,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: this._settingsOpen ? 'Close settings' : 'Open settings',
            style: this._settingsOpen
                ? 'padding: 2px 4px; margin-right: 4px; border-radius: 4px; background-color: rgba(255, 255, 255, 0.14);'
                : 'padding: 2px 4px; margin-right: 4px;',
            opacity: this._settingsOpen ? 255 : 180,
        });
        button.connect('clicked', () => {
            this._settingsOpen = !this._settingsOpen;
            if (!this._settingsOpen)
                this._serverEditor = null;
            this._scheduleRender(true);
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
            if (isOpen) {
                tooltip.hide();
            } else if (this._settingsOpen || this._serverEditor) {
                this._settingsOpen = false;
                this._serverEditor = null;
                this._scheduleRender(true);
            }
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

    _scheduleRender(force = false) {
        GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
            if (this._indicator && this._lastData)
                this._render(this._lastData, force);
            return GLib.SOURCE_REMOVE;
        });
    }

    _setServers(servers, activeServer) {
        this._servers = servers;
        this._activeServer = activeServer;
        const current = servers[activeServer];
        if (current)
            this._config = {...this._config, host: current.host, port: current.port, servers, activeServer};
        try {
            saveServers(servers, activeServer);
        } catch (error) {
            console.error(`rTorrent Status: cannot save servers: ${error.message}`);
        }
        this._scheduleRender(true);
        this._pollOnce();
    }

    _setAnonymize(anonymize) {
        const next = Boolean(anonymize);
        if (next === this._anonymize)
            return;
        this._anonymize = next;
        try {
            saveAnonymize(next);
        } catch (error) {
            console.error(`rTorrent Status: cannot save anonymize: ${error.message}`);
        }
        this._scheduleRender();
    }

    _setSort(sortBy, sortDir) {
        if (!SORT_FIELDS.includes(sortBy) || !SORT_DIRS.includes(sortDir))
            return;
        if (sortBy === this._sortBy && sortDir === this._sortDir)
            return;
        this._sortBy = sortBy;
        this._sortDir = sortDir;
        try {
            saveSort(sortBy, sortDir);
        } catch (error) {
            console.error(`rTorrent Status: cannot save sort: ${error.message}`);
        }
        this._scheduleRender();
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
        this._scheduleRender();
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
