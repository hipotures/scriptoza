'use strict';

export const STATES = {
    blocked: {label: 'Needs attention', color: '#f66151'},
    done: {label: 'Done', color: '#57e389'},
    working: {label: 'Working', color: '#62a0ea'},
    unknown: {label: 'Unknown', color: '#f8e45c'},
    idle: {label: 'Idle', color: '#b0b0b0'},
    offline: {label: 'Disconnected', color: '#777777'},
};

export const AGENT_TYPES = {
    codex: {label: 'Codex'},
    claude: {label: 'Claude Code'},
};

export function cleanText(value) {
    return String(value ?? '').replace(/\s+/g, ' ').trim();
}

export function normalizeAgents(snapshot, server) {
    if (!Array.isArray(snapshot?.agents) || !Array.isArray(snapshot.tabs) ||
        !Array.isArray(snapshot.workspaces) || !Array.isArray(snapshot.panes))
        throw new Error('Invalid Herdr snapshot');

    const tabs = new Map(snapshot.tabs.map(tab => [tab.tab_id, tab]));
    const workspaces = new Map(snapshot.workspaces.map(workspace => [workspace.workspace_id, workspace]));
    const panes = new Map(snapshot.panes.map(pane => [pane.pane_id, pane]));
    const bootId = typeof snapshot.boot_id === 'string' && snapshot.boot_id
        ? snapshot.boot_id : null;
    const agents = new Map();
    for (const agent of snapshot.agents) {
        if (!Object.hasOwn(AGENT_TYPES, agent.agent) || !panes.has(agent.pane_id))
            continue;
        const pane = panes.get(agent.pane_id);
        const tab = tabs.get(agent.tab_id);
        const workspace = workspaces.get(agent.workspace_id);
        const state = Object.hasOwn(STATES, agent.agent_status) && agent.agent_status !== 'offline'
            ? agent.agent_status : 'unknown';
        const paneName = cleanText(agent.name || pane.label || agent.pane_id.split(':').pop());
        const location = [
            cleanText(workspace?.label) || 'Unnamed workspace',
            cleanText(tab?.label ?? tab?.number) || 'Unnamed tab',
            paneName,
        ].join(':');
        const id = `${server.id}/${agent.pane_id}`;
        agents.set(id, {
            id, serverId: server.id, machine: server.label,
            paneId: agent.pane_id, bootId, state, agentType: agent.agent,
            terminalId: typeof agent.terminal_id === 'string' ? agent.terminal_id : null,
            stateChangeSeq: Number.isSafeInteger(agent.state_change_seq) && agent.state_change_seq >= 0
                ? agent.state_change_seq : 0,
            location: server.id === 'local' ? location : `${cleanText(server.label)}/${location}`,
        });
    }
    return [...agents.values()];
}

export function summarize(agents, errors = []) {
    const counts = Object.fromEntries(Object.keys(STATES).map(state => [state, 0]));
    for (const agent of agents)
        counts[agent.state]++;
    const state = Object.keys(STATES).find(key => counts[key] > 0) ??
        (errors.length > 0 ? 'offline' : 'idle');
    return {state, count: counts[state], total: agents.length, counts};
}

export function sortAgents(agents) {
    const priorities = ['blocked', 'working', 'done', 'unknown', 'offline', 'idle'];
    return [...agents].sort((left, right) =>
        priorities.indexOf(left.state) - priorities.indexOf(right.state) ||
        (['done', 'idle'].includes(left.state)
            ? (right.lastActivityAt ?? 0) - (left.lastActivityAt ?? 0) : 0) ||
        left.location.localeCompare(right.location));
}

export function trackActivity(agents, history, observedAt) {
    return agents.map(agent => {
        let previous = history.get(agent.id);
        if (previous && (previous.bootId !== agent.bootId || previous.terminalId !== agent.terminalId ||
            previous.agentType !== agent.agentType || previous.stateChangeSeq > agent.stateChangeSeq))
            previous = null;
        const active = ['working', 'blocked'].includes(agent.state);
        const changed = previous && (['working', 'blocked'].includes(previous.state) ||
            agent.stateChangeSeq > previous.stateChangeSeq);
        const lastActivityAt = active || changed ? observedAt : previous?.lastActivityAt ?? 0;
        history.set(agent.id, {...agent, lastActivityAt});
        // Active rows retain stable data while their observation time advances.
        const {stateChangeSeq, ...displayAgent} = agent;
        return {...displayAgent, lastActivityAt: ['done', 'idle'].includes(agent.state) ? lastActivityAt : 0};
    });
}
