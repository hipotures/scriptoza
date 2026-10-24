"""Offline GJS tests for the GNOME Herdr agent status indicator."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


EXTENSION = Path(__file__).resolve().parents[1] / "ai" / "agentai-status"


@unittest.skipUnless(shutil.which("gjs"), "GJS is required")
class CodexStatusTests(unittest.TestCase):
    def run_gjs(self, body, env=None):
        imports = f"""
import GLib from 'gi://GLib';
import System from 'system';
import {{normalizeAgents, summarize, sortAgents, trackActivity}} from '{(EXTENSION / 'model.js').as_uri()}';
import {{Collector}} from '{(EXTENSION / 'collector.js').as_uri()}';
import Gio from 'gi://Gio';
import {{EventMonitor}} from '{(EXTENSION / 'event-monitor.js').as_uri()}';
import {{EventStream, subscriptions, remoteCommand}} from '{(EXTENSION / 'event-stream.js').as_uri()}';
import {{parseClaudeUsage, parseCodexUsage, readCodexUsage, readClaudeUsage}} from '{(EXTENSION / 'usage.js').as_uri()}';
import {{formatUsage}} from '{(EXTENSION / 'usage-format.js').as_uri()}';
import {{loadDensity, saveDensity, PROFILES, DENSITIES}} from '{(EXTENSION / 'density.js').as_uri()}';
import {{StatusProcess}} from '{(EXTENSION / 'status-process.js').as_uri()}';
import {{Navigator, clientWindowToken, findClientWindow, focusTarget}} from '{(EXTENSION / 'navigation.js').as_uri()}';
function check(condition, message) {{ if (!condition) throw new Error(message); }}
function snapshot(states = ['working']) {{
    return {{
        boot_id: 'boot-1',
        agents: states.map((state, index) => ({{agent: 'codex', agent_status: state,
            pane_id: `w1:p${{index}}`, tab_id: 'w1:t1', workspace_id: 'w1'}})),
        panes: states.map((state, index) => ({{pane_id: `w1:p${{index}}`}})),
        tabs: [{{tab_id: 'w1:t1', label: 'run'}}],
        workspaces: [{{workspace_id: 'w1', label: 'project'}}],
    }};
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "test.js"
            script.write_text(imports + body, encoding="utf-8")
            result = subprocess.run(
                ["gjs", "-m", str(script)], capture_output=True, text=True, timeout=15,
                env=env,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("CRITICAL", result.stderr)

    def test_statuses_priority_and_unknown_values(self):
        self.run_gjs("""
const agents = normalizeAgents(snapshot(['idle', 'done', 'working', 'blocked', 'alien', '__proto__']),
    {id: 'local', label: 'Local'});
const summary = summarize(agents);
check(summary.state === 'blocked' && summary.count === 1 && summary.total === 6, 'Blocked priority');
check(summary.counts.done === 1 && summary.counts.idle === 1 && summary.counts.unknown === 2,
    'Keep done and idle distinct, normalize unknown states');
check(summarize(agents.filter(agent => agent.state !== 'blocked')).state === 'done', 'Done priority');
check(sortAgents(agents)[0].state === 'blocked', 'Sort by urgency');
check(sortAgents([...agents, {state: 'offline', location: 'offline'}]).map(agent => agent.state).join(',') ===
    'blocked,working,done,unknown,unknown,offline,idle', 'Alerts, working, remaining states, then idle');
check(summarize([], [{machine: 'gpu'}]).state === 'offline', 'Disconnected with no agents');
""")

    def test_automatic_names_and_session_titles(self):
        self.run_gjs("""
const raw = snapshot(['working', 'idle', 'working']);
raw.workspaces[0].label = 'homestack';
raw.agents[0].terminal_title_stripped = 'Define API services | homestack';
raw.agents[1].terminal_title_stripped = ' HomeStack ';
raw.agents[2].agent = 'claude';
raw.agents[2].terminal_title_stripped = 'Random character string';
const local = normalizeAgents(raw, {id: 'local', label: 'Local'});
check(local[0].displayName === 'homestack · Codex', 'Readable workspace and type');
check(local[0].sessionTitle === 'Define API services', 'Remove redundant workspace suffix');
check(local[1].sessionTitle === '', 'Hide a title that repeats the workspace');
check(local[2].displayName === 'homestack · Claude Code' &&
    local[2].sessionTitle === 'Random character string', 'Preserve automatic Claude title');
check(local[0].location === 'homestack:run:p0' && local[0].paneId === 'w1:p0',
    'Keep technical location and navigation identity');
const remote = normalizeAgents(raw, {id: 'gpu-id', label: 'gpu'});
check(remote[0].displayName === 'gpu/homestack · Codex', 'Remote names include the machine');
delete raw.agents[0].terminal_title_stripped;
check(normalizeAgents(raw, {id: 'local', label: 'Local'})[0].sessionTitle === '',
    'Missing title needs no second line');
""")

    def test_activity_sorting_preserves_working_order_and_seen_completion_time(self):
        self.run_gjs("""
const history = new Map();
const make = (id, state, seq) => ({id, serverId: 'local', terminalId: id, bootId: 'boot-1',
    agentType: 'codex', state, stateChangeSeq: seq, location: id});
trackActivity([make('A', 'idle', 9), make('Z', 'working', 1)], history, 100);
const working = trackActivity([make('Z', 'working', 1)], history, 200)[0];
check(working.lastActivityAt === 0, 'Working observations must not invalidate cached rows');
check(JSON.stringify(working) === JSON.stringify(trackActivity([make('Z', 'working', 2)], history, 250)[0]),
    'Activity sequence changes must not rebuild unchanged working rows');
const done = trackActivity([make('Z', 'done', 3)], history, 300)[0];
check(done.lastActivityAt === 300, 'Work completion time was not recorded');
const idle = trackActivity([make('Z', 'idle', 3)], history, 400)[0];
check(idle.lastActivityAt === 300, 'Marking a completion seen must not update activity');
const idleA = trackActivity([make('A', 'idle', 9)], history, 400)[0];
check(sortAgents([idleA, idle])[0].id === 'Z', 'Recently active idle agent fell below an untouched agent');
const quickTurn = trackActivity([make('A', 'idle', 11)], history, 500)[0];
check(quickTurn.lastActivityAt === 500 && sortAgents([idle, quickTurn])[0].id === 'A',
    'Work entirely between polls must count as activity');
const entries = ['working', 'blocked', 'done', 'idle', 'unknown'].flatMap(state => [
    {...make('A', state, 1), lastActivityAt: 100}, {...make('Z', state, 2), lastActivityAt: 200}]);
check(sortAgents(entries).map(agent => `${agent.state}:${agent.id}`).join(',') ===
    'blocked:A,blocked:Z,working:A,working:Z,done:Z,done:A,unknown:A,unknown:Z,idle:Z,idle:A',
    'Only done and idle may sort by activity');
check(sortAgents([{...idle, location: 'Z'}, {...idleA, lastActivityAt: 300}])[0].id === 'A',
    'Equal activity times need a stable alphabetical tie break');
""")

    def test_activity_identity_resets_and_sequence_validation(self):
        self.run_gjs("""
const history = new Map();
const raw = snapshot(['working']);
raw.agents[0].terminal_id = 'terminal-1';
raw.agents[0].state_change_seq = 10;
const local = normalizeAgents(raw, {id: 'local', label: 'Local'})[0];
const remote = normalizeAgents(raw, {id: 'gpu-id', label: 'GPU'})[0];
trackActivity([local, remote], history, 100);
check(history.size === 2, 'Same pane IDs on different machines must keep distinct activity');
const remoteIdle = trackActivity([{...remote, state: 'idle', stateChangeSeq: 11}], history, 200)[0];
check(remoteIdle.lastActivityAt === 200 && history.get(local.id).lastActivityAt === 100,
    'Remote activity leaked into local history');
for (const patch of [{bootId: 'boot-new'}, {terminalId: 'terminal-new'}, {agentType: 'claude'},
    {stateChangeSeq: 0}]) {
    const baseline = new Map(history);
    check(trackActivity([{...local, state: 'idle', ...patch}], baseline, 300)[0].lastActivityAt === 0,
        'Replaced agent inherited stale activity');
}
for (const value of [-1, '100', 1.5, Number.MAX_SAFE_INTEGER + 1]) {
    raw.agents[0].state_change_seq = value;
    check(normalizeAgents(raw, {id: 'local', label: 'Local'})[0].stateChangeSeq === 0,
        'Invalid state sequence accepted');
}
""")

    def test_collector_activity_across_machines_and_cleanup(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
let clock = 1000000;
let localState = 'working';
let remoteState = 'working';
let enabled = true;
let remoteMissing = false;
let failRemote = false;
GLib.get_monotonic_time = () => clock;
collector._readJson = async args => {
    if (args[0] === 'machine')
        return [{id: 'gpu-id', label: 'GPU', enabled}];
    const remote = args[0] === '--machine';
    if (remote && failRemote)
        throw new Error('Disconnected');
    const state = remote ? remoteState : localState;
    const data = snapshot(remote && remoteMissing ? [] : [state]);
    for (const agent of data.agents) {
        agent.terminal_id = 'same-terminal-id';
        agent.state_change_seq = state === 'working' ? 1 : 2;
    }
    return {result: {snapshot: data}};
};
(async () => {
    const first = await collector.collect();
    check(first.agents.every(agent => agent.lastActivityAt === 0), 'Active rows expose ticking timestamps');
    localState = 'idle'; clock = 2000000;
    const second = await collector.collect();
    check(second.agents[0].lastActivityAt === 2000 && second.agents[1].lastActivityAt === 0,
        'Local completion confused with same remote pane');
    remoteState = 'idle'; clock = 3000000;
    const third = await collector.collect();
    check(sortAgents(third.agents)[0].serverId === 'gpu-id', 'Most recent remote idle agent must be first');
    failRemote = true; clock = 4000000;
    await collector.collect();
    check(collector._activity.size === 2, 'Temporary remote failure must retain activity history');
    failRemote = false; collector._retryAfter.clear(); remoteMissing = true;
    await collector.collect();
    check(collector._activity.size === 1, 'Closed remote pane retained history');
    remoteMissing = false; await collector.collect(); enabled = false;
    await collector.collect();
    check(collector._activity.size === 1, 'Disabled machine retained history');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => {
    collector.close();
    check(collector._activity.size === 0, 'Disable leaked activity history');
    loop.quit();
});
loop.run();
""")

    def test_remote_names_and_identity_filtering(self):
        self.run_gjs("""
const data = snapshot();
data.agents.push({...data.agents[0], agent: 'claude', pane_id: 'w1:p9', agent_status: 'blocked'});
data.panes.push({pane_id: 'w1:p9'});
data.agents.push({...data.agents[0], agent: '__proto__'});
data.agents.push({...data.agents[0], agent: 'unsupported'});
data.agents.push({...data.agents[0], pane_id: 'gone'});
data.agents.push({...data.agents[0]});
data.workspaces[0].label = 'project\n  name';
const local = normalizeAgents(data, {id: 'local', label: 'Local'});
const remote = normalizeAgents(data, {id: 'gpu-id', label: 'gpu'});
check(local.length === 2 && remote.length === 2, 'Only live supported agents, no duplicates');
check(local[0].agentType === 'codex' && local[1].agentType === 'claude' && local[1].state === 'blocked',
    'Codex and Claude retain their types and statuses');
check(summarize(local).total === 2 && summarize(local).state === 'blocked', 'Count both agent types');
check(local[0].id !== remote[0].id, 'Machine-scoped identities');
check(local[0].bootId === 'boot-1' && remote[0].bootId === 'boot-1', 'Machine boot identity');
check(remote[0].location === 'gpu/project name:run:p0', 'Remote display name');
const oldSnapshot = snapshot();
delete oldSnapshot.boot_id;
check(normalizeAgents(oldSnapshot, {id: 'local', label: 'Local'})[0].bootId === null,
    'Older snapshots remain renderable without a boot identity');
let rejected = false;
try { normalizeAgents({}, {id: 'local'}); } catch { rejected = true; }
check(rejected, 'Malformed snapshots rejected');
""".replace("project\n  name", "project\\n  name"))

    def test_discovery_routes_enabled_machines_and_ignores_offline_agents(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
let failGpu = false;
let removeGpu = false;
const calls = [];
collector._readJson = async args => {
    calls.push(args);
    if (args[0] === 'machine')
        return removeGpu ? [] : [
            {id: 'gpu-id', label: 'gpu', enabled: true},
            {id: 'disabled-id', label: 'disabled', enabled: false},
        ];
    if (args[0] === '--machine' && failGpu)
        throw new Error('SSH disconnected');
    return {result: {snapshot: snapshot(['done'])}};
};
(async () => {
    let result = await collector.collect();
    check(result.agents.length === 2 && result.errors.length === 0, 'Local and remote Codexes');
    check(!result.waitingForServer, 'Working server leaves waiting state');
    check(calls.some(args => args.join(' ') === '--machine gpu-id api snapshot'), 'Remote routing');
    check(!calls.some(args => args.includes('disabled-id')), 'Disabled profiles skipped');
    failGpu = true;
    result = await collector.collect();
    check(!result.agents.some(agent => agent.serverId === 'gpu-id'), 'Offline machine agents omitted');
    check(result.agents.find(agent => agent.serverId === 'local').state === 'done', 'Local unaffected');
    check(result.errors.length === 0 && result.ignoredMachines[0] === 'gpu', 'Offline machine silently ignored');
    const callsBeforeRetry = calls.length;
    result = await collector.collect();
    check(calls.length === callsBeforeRetry + 2, 'Offline machine not queried again on the next poll');
    check(result.agents.length === 1 && result.ignoredMachines[0] === 'gpu', 'Offline machine still omitted');
    failGpu = false;
    collector._retryAfter.set('gpu-id', 0);
    result = await collector.collect();
    check(result.agents.every(agent => agent.state === 'done'), 'Recovery');
    removeGpu = true;
    result = await collector.collect();
    check(result.agents.length === 1, 'Removed profile removed from display');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { collector.close(); loop.quit(); });
loop.run();
""")

    def test_local_server_unavailable_skips_all_remote_requests(self):
        self.run_gjs("""
const collector = new Collector();
const calls = [];
collector._servers.push({id: 'gpu-id', label: 'gpu'});
collector._readJson = async args => {
    calls.push(args.join(' '));
    throw new Error('Local server is not running');
};
const result = await collector.collect();
check(calls.length === 1 && calls[0] === 'api snapshot', 'Only local server checked');
check(result.agents.length === 0 && result.errors[0].serverId === 'local', 'Local failure reported');
check(result.waitingForServer === true, 'Waiting state reaches the panel');
collector.close();
""")

    def test_machine_list_failure_ignores_unreachable_remote_agents(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
const server = {id: 'gpu-id', label: 'gpu'};
collector._servers.push(server);
collector._readJson = async args => {
    if (args[0] === 'machine' || args[0] === '--machine')
        throw new Error('Disconnected');
    return {result: {snapshot: snapshot(['working'])}};
};
collector.collect().then(result => {
    check(result.errors.length === 1 && result.ignoredMachines[0] === 'gpu', 'Discovery error reported, offline ignored');
    check(!result.agents.some(agent => agent.serverId === 'gpu-id'), 'Offline agents not counted');
    check(result.agents.find(agent => agent.serverId === 'local').state === 'working', 'Local still works');
}).catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { collector.close(); loop.quit(); });
loop.run();
""")

    def test_async_subprocess_json_and_shutdown_cleanup(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
collector._herdr = '/usr/bin/python3';
const metrics = {requests: 0, parseMs: 0, bytes: 0};
(async () => {
    const result = await collector._readJson(['-c', 'import json; print(json.dumps(dict(ok=True)))'], metrics);
    check(result.ok && metrics.requests === 1 && metrics.bytes > 0, 'Async JSON parsing');
    let rejected = false;
    try { await collector._readJson(['-c', 'print("invalid")'], metrics); } catch { rejected = true; }
    check(rejected && collector._processes.size === 0, 'JSON errors clean up processes');
    const pending = collector._readJson(['-c', 'import time; time.sleep(60)'], metrics);
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => { collector.close(); return GLib.SOURCE_REMOVE; });
    rejected = false;
    try { await pending; } catch { rejected = true; }
    check(rejected && collector._processes.size === 0, 'Disable cancels live processes');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { collector.close(); loop.quit(); });
loop.run();
""")

    def test_process_launches_yield_and_disable_cancels_queued_requests(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
collector._herdr = '/usr/bin/python3';
const metrics = {requests: 0, parseMs: 0, bytes: 0};
let previous = 0;
let interleaved = false;
GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
    check(metrics.requests - previous <= 1, 'Subprocess burst blocked other main-loop work');
    previous = metrics.requests;
    interleaved ||= previous > 0 && previous < 8;
    return previous === 8 ? GLib.SOURCE_REMOVE : GLib.SOURCE_CONTINUE;
});
const requests = Array.from({length: 8}, () =>
    collector._readJson(['-c', 'print("{}")'], metrics));
check(collector._processes.size === 0, 'Navigation or polling launched a process synchronously');
(async () => {
    await Promise.all(requests);
    check(interleaved, 'Queued launches did not yield to another idle source');
    const queued = collector.readJson(['-c', 'print("{}")']);
    collector.close();
    let stopped = false;
    try { await queued; } catch (error) { stopped = error.message === 'Collector stopped'; }
    check(stopped && !collector._launchSource && collector._pending.length === 0 &&
        collector._processes.size === 0, 'Disable left queued work or processes');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { collector.close(); loop.quit(); });
loop.run();
""")

    def test_request_timeout_and_disable_stop_descendant_processes(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const directory = GLib.dir_make_tmp('codex-status-test-XXXXXX');
const pidFile = `${directory}/child.pid`;
const bridge = `import pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(signum, frame):
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
pathlib.Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
`;
const collector = new Collector();
collector._herdr = '/usr/bin/python3';
const metrics = {requests: 0, parseMs: 0, bytes: 0};
function childStopped() {
    const [, bytes] = GLib.file_get_contents(pidFile);
    const pid = new TextDecoder().decode(bytes);
    check(!GLib.file_test(`/proc/${pid}`, GLib.FileTest.EXISTS), 'Child process was left running');
}
(async () => {
    const start = GLib.get_monotonic_time();
    let message = '';
    try { await collector._readJson(['-c', bridge, pidFile], metrics); } catch (error) { message = error.message; }
    check(message.includes('timed out'), 'Actual eight-second timeout');
    check(GLib.get_monotonic_time() - start < 10000000, 'Timeout blocked beyond grace period');
    childStopped();
    const pending = collector._readJson(['-c', bridge, pidFile], metrics);
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, 200, () => { collector.close(); return GLib.SOURCE_REMOVE; });
    try { await pending; } catch {}
    childStopped();
    check(collector._processes.size === 0, 'Processes removed from tracking');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => {
    collector.close(); GLib.unlink(pidFile); GLib.rmdir(directory); loop.quit();
});
loop.run();
""")

    def test_event_monitor_updates_only_changed_machine_and_reconciles_inflight_events(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const updates = [];
const streams = new Map();
const calls = [];
let localState = 'idle';
let remoteState = 'idle';
let hold = false;
let release;
const collector = new Collector();
collector._readJson = async (args, metrics) => {
    calls.push(args.join(' '));
    if (args[0] === 'machine')
        return [{id: 'gpu-id', label: 'gpu', enabled: true}];
    metrics.requests++;
    const data = snapshot([args[0] === '--machine' ? remoteState : localState]);
    if (hold && args[0] !== '--machine') {
        hold = false;
        await new Promise(resolve => { release = resolve; });
    }
    return {result: {snapshot: data}};
};
const monitor = new EventMonitor(data => updates.push(data), {collector,
    stream: (server, herdr, panes, ready, event, error) => {
        const value = {panes, ready, event, error, closed: false, close() { this.closed = true; }};
        streams.set(server.id, value);
        return value;
    }});
function pause(ms) { return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => { resolve(); return GLib.SOURCE_REMOVE; })); }
(async () => {
    monitor.start(); await pause(20);
    check(streams.size === 2 && updates.at(-1).agents.length === 2, 'Bootstrap local and remote agents');
    streams.get('local').ready(); streams.get('gpu-id').ready(); await pause(150);
    const baseline = calls.length;
    localState = 'working';
    streams.get('local').event({}); streams.get('local').event({});
    await pause(150);
    check(calls.length === baseline + 1 && calls.at(-1) === 'api snapshot',
        'Event bursts must refresh only their machine, without discovery or remote polling');
    check(updates.at(-1).agents.find(a => a.serverId === 'local').state === 'working', 'Push state');
    const stable = calls.length; await pause(150);
    check(calls.length === stable, 'Idle subscription polled snapshots');
    const updatedAt = updates.at(-1).updatedAt;
    check(Number.isSafeInteger(updatedAt) && updatedAt > 0, 'Successful snapshot needs an update time');
    await monitor._discover();
    check(updates.at(-1).updatedAt === updatedAt, 'Machine discovery must preserve the last update time');
    hold = true; streams.get('local').event({}); await pause(150);
    localState = 'blocked'; streams.get('local').event({});
    release(); await pause(30);
    check(updates.at(-1).agents.find(a => a.serverId === 'local').state === 'blocked',
        'An event arriving during a read must trigger another authoritative snapshot');
    remoteState = 'working'; streams.get('gpu-id').event({}); await pause(150);
    check(updates.at(-1).agents.find(a => a.serverId === 'gpu-id').state === 'working', 'Remote push');
    const old = streams.get('gpu-id');
    old.error(new Error('events_lost'));
    check(old.closed && updates.at(-1).agents.length === 1, 'Lost remote stream retained stale rows');
    const entry = monitor._entries.get('gpu-id');
    GLib.Source.remove(entry.timer); entry.timer = 0;
    await monitor._refresh(entry);
    check(streams.get('gpu-id') !== old && updates.at(-1).agents.length === 2, 'Resubscribe after loss');
    old.event({}); await pause(150);
    const beforeClose = calls.length;
    monitor.close(); streams.get('local').event({}); await pause(150);
    check(calls.length === beforeClose && [...streams.values()].every(s => s.closed),
        'Closed monitor retained streams or accepted late events');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { monitor.close(); loop.quit(); });
loop.run();
""")

    def test_event_monitor_rebuilds_subscriptions_and_gates_remotes_when_local_is_lost(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const updates = [];
const streams = [];
let panes = 1;
let hold = false;
let release;
let remoteQueries = 0;
const collector = new Collector();
collector._readJson = async (args, metrics) => {
    if (args[0] === 'machine')
        return [{id: 'gpu-id', label: 'gpu', enabled: true}];
    if (args[0] === '--machine') remoteQueries++;
    const data = snapshot(Array(panes).fill('working'));
    if (hold) { hold = false; await new Promise(resolve => { release = resolve; }); }
    return {result: {snapshot: data}};
};
const monitor = new EventMonitor(data => updates.push(data), {collector,
    stream: (server, herdr, ids, ready, event, error) => {
        const stream = {server, ids, event, error, closed: false, close() { this.closed = true; }};
        streams.push(stream); return stream;
    }});
function pause(ms) { return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => { resolve(); return GLib.SOURCE_REMOVE; })); }
(async () => {
    monitor.start(); await pause(20);
    panes = 2; streams[0].event({}); await pause(150);
    const local = streams.at(-1);
    check(streams[0].closed && local.ids.length === 2, 'New panes require a fresh status subscription');
    const before = remoteQueries;
    hold = true; local.event({}); await pause(150);
    local.error(new Error('connection closed'));
    release(); await pause(30);
    check(updates.at(-1).waitingForServer && updates.at(-1).agents.length === 0,
        'Inflight snapshot restored stale state after disconnect');
    check(streams.every(s => s.closed), 'Local failure left remote subscriptions alive');
    await monitor._discover();
    check(remoteQueries === before, 'Local failure must gate remote discovery');
    const entry = monitor._entries.get('local');
    GLib.Source.remove(entry.timer); entry.timer = 0;
    await monitor._refresh(entry); await pause(20);
    check(!updates.at(-1).waitingForServer && updates.at(-1).agents.length === 4,
        'Local recovery failed to rediscover remote agents');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { monitor.close(); loop.quit(); });
loop.run();
""")

    def test_event_stream_acknowledgement_loss_and_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            bridge = Path(directory) / "herdr"
            bridge.write_text("""#!/usr/bin/python3
import json, os, signal, subprocess, sys, time
request = json.loads(sys.stdin.readline())
assert request['method'] == 'events.subscribe'
assert any(item['type'] == 'pane.agent_status_changed' for item in request['params']['subscriptions'])
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(signum, frame):
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print(json.dumps({'result': {'type': 'subscription_started'}}), flush=True)
print(json.dumps({'event': 'pane.agent_status_changed', 'pids': [os.getpid(), child.pid]}), flush=True)
print(json.dumps({'error': {'code': 'events_lost'}}), flush=True)
time.sleep(60)
""", encoding="utf-8")
            bridge.chmod(0o755)
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
let ready = 0, events = 0, errors = 0, pids = [];
const stream = new EventStream({{id: 'local'}}, '{bridge}', ['w1:p0'], () => ready++,
    data => {{ events++; pids = data.pids; }}, error => {{
        check(error.message === 'events_lost', 'Subscription error was ignored'); errors++;
    }});
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    for (let index = 0; index < 150 && errors === 0; index++)
        await pause(20);
    for (let index = 0; index < 150 && pids.some(pid =>
        GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS)); index++)
        await pause(20);
    check(ready === 1 && events === 1 && errors === 1 && stream._closed && !stream._deadline,
        'Event stream must acknowledge, deliver push, and close on event loss');
    check(pids.every(pid => !GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS)),
        'Lost subscription left bridge descendants running');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ stream.close(); loop.quit(); }});
loop.run();
""")

    def test_usage_parsing_formatting_and_local_readers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").mkdir()
            (root / "runtime" / "claude-statusline-input.json").write_text(
                '{"rate_limits":{"five_hour":{"used_percentage":1,"resets_at":2000},'
                '"seven_day":{"used_percentage":64,"resets_at":900000}}}', encoding="utf-8")
            day = root / "codex" / "sessions" / "2026" / "10" / "24"
            day.mkdir(parents=True)
            event = ('{"payload":{"type":"token_count","rate_limits":{"primary":'
                     '{"used_percent":36.0,"window_minutes":300,"resets_at":1500},"secondary":'
                     '{"used_percent":68.0,"window_minutes":10080,"resets_at":800000}}}}')
            (day / "rollout-2026-10-24T01-00-00-a.jsonl").write_text(event + "\n", encoding="utf-8")
            (day / "rollout-2026-10-24T02-00-00-b.jsonl").write_text('{"payload":{}}\n', encoding="utf-8")
            self.run_gjs(f"""
const claude = readClaudeUsage('{root / "runtime"}');
check(claude.five.usedPercent === 1 && claude.week.resetsAt === 900000, 'Claude usage was not parsed');
check(readClaudeUsage('{root / "missing"}') === null, 'Missing Claude input must yield no usage');
check(parseClaudeUsage('{{"rate_limits":{{}}}}') === null, 'Empty Claude limits must yield no usage');
const codex = readCodexUsage('{root / "codex"}');
check(codex.five.usedPercent === 36 && codex.week.usedPercent === 68,
    'Codex usage must come from the newest rollout that has rate limits');
check(readCodexUsage('{root / "missing"}') === null, 'Missing Codex data must yield no usage');
const weeklyOnly = parseCodexUsage('{{"payload":{{"rate_limits":{{"primary":'
    + '{{"used_percent":10,"window_minutes":10080,"resets_at":5}}}}}}}}');
check(weeklyOnly.five === null && weeklyOnly.week.usedPercent === 10, 'Windows must be classified by length');
check(formatUsage(claude, 1000) === '5h  99% · 17m    wk  36% · 10d  ', formatUsage(claude, 1000));
check(formatUsage(claude, 2000) === 'wk  36% · 10d  ', 'Expired windows must be hidden');
check(formatUsage(null, 0) === '', 'Missing usage must format as empty');
check(formatUsage({{five: {{usedPercent: 0, resetsAt: 3 * 3600 + 12 * 60}}, week: null}}, 1) === '5h 100% · 3h12m',
    'Hours and minutes must be zero padded');
""")

    def test_density_config_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bad.json").write_text('{"density":"huge"}', encoding="utf-8")
            (root / "broken.json").write_text("{", encoding="utf-8")
            self.run_gjs(f"""
check(DENSITIES.join() === 'large,medium,compact' && DENSITIES.every(name => PROFILES[name]), 'Density profiles are incomplete');
check(loadDensity('{root / "missing.json"}') === 'large', 'Missing config must use the large density');
check(loadDensity('{root / "bad.json"}') === 'large', 'Unknown density must use the large density');
check(loadDensity('{root / "broken.json"}') === 'large', 'Broken config must use the large density');
const path = '{root / "new" / "ai-agent-status" / "config.json"}';
saveDensity('compact', path);
check(loadDensity(path) === 'compact', 'Saved density was not read back');
let failed = false;
try {{ saveDensity('huge', path); }} catch {{ failed = true; }}
check(failed && loadDensity(path) === 'compact', 'Unknown density must be rejected');
""")

    def test_status_worker_streams_updates_and_reaps_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            worker_file = Path(directory) / "worker.js"
            worker_file.write_text("""
import GLib from 'gi://GLib';
const data = {agents: [], errors: [], metrics: {totalMs: 1, parseMs: 0}};
print(JSON.stringify(data));
GLib.timeout_add(GLib.PRIORITY_DEFAULT, 50, () => {
    print(JSON.stringify({...data, agents: [{state: 'working'}]}));
    return GLib.SOURCE_REMOVE;
});
new GLib.MainLoop(null, false).run();
""", encoding="utf-8")
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{worker_file}');
const updates = [];
const launches = [];
const spawn = Gio.Subprocess.new;
Gio.Subprocess.new = (args, flags) => {{ launches.push(args); return spawn(args, flags); }};
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    worker.start(data => updates.push(data), error => {{ throw error; }});
    const pid = worker._process.get_identifier();
    for (let index = 0; index < 150 && updates.length < 2; index++)
        await pause(20);
    check(updates.length === 2 && updates[1].agents[0].state === 'working',
        'Push updates were not delivered without a collection request');
    check(launches.length === 1 && worker._process.get_identifier() === pid, 'Worker was respawned');
    worker.close();
    for (let index = 0; index < 150 && worker._process; index++)
        await pause(20);
    check(!worker._process && !worker._killSource &&
        !GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS), 'Worker survived close');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""")

    def test_failed_status_worker_reports_error_without_respawning(self):
        with tempfile.TemporaryDirectory() as directory:
            worker_file = Path(directory) / "worker.js"
            worker_file.write_text('print("invalid");', encoding="utf-8")
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{worker_file}');
let errors = 0;
worker.start(() => {{ throw new Error('Invalid response accepted'); }}, () => errors++);
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    for (let index = 0; index < 150 && (errors === 0 || worker._process); index++)
        await pause(20);
    check(errors === 1 && worker._closed && !worker._process, 'Failed worker was not stopped');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""")

    def test_status_worker_shutdown_stops_active_command_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "herdr"
            fake.write_text("""#!/usr/bin/python3
import json, os, pathlib, signal, subprocess, sys, time
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
def stop(signum, frame):
    child.wait()
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
pathlib.Path(os.environ['STATUS_CHILD_PIDS']).write_text(json.dumps([os.getpid(), child.pid]))
time.sleep(60)
""", encoding="utf-8")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                   "STATUS_CHILD_PIDS": str(Path(directory) / "pids")}
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{EXTENSION / 'status-worker.js'}');
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    worker.start(() => {{}}, error => {{ throw error; }});
    const pid = worker._process.get_identifier();
    const file = GLib.getenv('STATUS_CHILD_PIDS');
    for (let index = 0; index < 100 && !GLib.file_test(file, GLib.FileTest.EXISTS); index++)
        await pause(20);
    check(GLib.file_test(file, GLib.FileTest.EXISTS), 'Command fixture failed to start');
    const [, bytes] = GLib.file_get_contents(file);
    const pids = JSON.parse(new TextDecoder().decode(bytes));
    worker.close();
    for (let index = 0; index < 100 && [pid, ...pids].some(value =>
        GLib.file_test(`/proc/${{value}}`, GLib.FileTest.EXISTS)); index++)
        await pause(20);
    check(!worker._process && !worker._killSource, 'Worker was not reaped');
    check([pid, ...pids].every(value => !GLib.file_test(`/proc/${{value}}`, GLib.FileTest.EXISTS)),
        'Disable left worker command descendants running');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""", env=env)

    def test_status_worker_force_stops_if_it_ignores_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            worker_file = Path(directory) / "worker.js"
            worker_file.write_text("""
import GLib from 'gi://GLib';
import GLibUnix from 'gi://GLibUnix';
GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, 15, () => GLib.SOURCE_CONTINUE);
new GLib.MainLoop(null, false).run();
""", encoding="utf-8")
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{worker_file}');
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    worker.start(() => {{}}, () => {{}});
    const pid = worker._process.get_identifier();
    await pause(200);
    worker.close();
    await pause(2200);
    check(!worker._process && !worker._killSource &&
        !GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS), 'Unresponsive worker survived shutdown');
    const immediate = new StatusProcess('{EXTENSION / 'status-worker.js'}');
    immediate.start(() => {{}}, () => {{}});
    immediate.close();
    await pause(150);
    check(!immediate._process && !immediate._killSource, 'Immediate startup cancellation leaked a worker');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""")

    def test_navigation_routes_machine_and_pane_after_client_check(self):
        self.run_gjs("""
const window = {get_title: () => 'Herdr — codex [herdr-client:client-1]'};
const calls = [];
let activated = null;
let closed = false;
const navigator = new Navigator({
    readJson: async args => {
        calls.push(args);
        if (args.includes('--check'))
            return {client_id: 'client-1', window_token: clientWindowToken('client-1'), boot_id: 'boot-7'};
        return {client_id: 'client-1', window_token: clientWindowToken('client-1'), boot_id: 'boot-7', focused: true};
    },
    getWindowActors: () => [{meta_window: window}],
    activateWindow: value => { activated = value; },
    closeMenu: () => { closed = true; },
    notifyError: () => { throw new Error('unexpected navigation error'); },
});
(async () => {
    check(focusTarget({serverId: 'local', paneId: 'w1:p3'}) === 'local:w1:p3', 'Local target identity');
    check(focusTarget({serverId: 'gpu-id', paneId: 'w2:p5'}) === 'gpu-id:w2:p5', 'Remote target identity');
    check(findClientWindow([{meta_window: window}], '[herdr-client:client-1]') === window,
        'Window actor mapping');
    const result = await navigator.focus({serverId: 'gpu-id', paneId: 'w2:p5', bootId: 'boot-7',
        agentType: 'claude', location: 'GPU/project:run:p5'});
    check(result && activated === window && closed, 'Focus was acknowledged and activated');
    check(calls[0].join(' ') === 'agent focus gpu-id:w2:p5 --check --expected-boot boot-7', 'Check target and boot guard');
    check(calls[1].join(' ') === 'agent focus gpu-id:w2:p5 --client client-1 --expected-boot boot-7',
        'Focus target and boot guard');
})().catch(error => { printerr(error.stack); System.exit(1); });
""")

    def test_navigation_rejects_ambiguous_or_stale_windows_without_activation(self):
        self.run_gjs("""
const first = {get_title: () => '[herdr-client:client-2] terminal'};
const second = {get_title: () => '[herdr-client:client-2] duplicate'};
let actorList = [{meta_window: first}, {meta_window: second}];
let errors = [];
let activated = false;
const ambiguous = new Navigator({
    readJson: async () => ({client_id: 'client-2', window_token: clientWindowToken('client-2'), boot_id: 'boot-1'}),
    getWindowActors: () => actorList,
    activateWindow: () => { activated = true; },
    closeMenu: () => { throw new Error('menu must stay open'); },
    notifyError: (message, error) => errors.push(`${message}: ${error.message}`),
});
(async () => {
    check(!await ambiguous.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'}),
        'Ambiguous windows rejected');
    check(!activated && errors[0].includes('Multiple terminal windows'), 'Ambiguous activation refused');

    errors = [];
    const staleBoot = new Navigator({
        readJson: async args => ({client_id: 'client-2', window_token: clientWindowToken('client-2'),
            boot_id: args.includes('--check') ? 'boot-2' : 'boot-1'}),
        getWindowActors: () => [{meta_window: first}],
        activateWindow: () => { activated = true; },
        closeMenu: () => { throw new Error('menu must stay open'); },
        notifyError: (message, error) => errors.push(`${message}: ${error.message}`),
    });
    check(!await staleBoot.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'}),
        'Stale snapshot boot rejected');
    check(!activated && errors[0].includes('different server boot'),
        'Stale snapshot boot did not stop navigation');

    errors = [];
    const mismatch = new Navigator({
        readJson: async args => args.includes('--check')
            ? {client_id: 'client-2', window_token: clientWindowToken('client-2'), boot_id: 'boot-1'}
            : {client_id: 'other-client', window_token: clientWindowToken('other-client'), boot_id: 'boot-1'},
        getWindowActors: () => [{meta_window: first}],
        activateWindow: () => { activated = true; },
        closeMenu: () => { throw new Error('menu must stay open'); },
        notifyError: (message, error) => errors.push(`${message}: ${error.message}`),
    });
    check(!await mismatch.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'}),
        'Mismatched focus acknowledgement rejected');
    check(!activated && errors[0].includes('mismatched focus acknowledgement'),
        'Mismatched acknowledgement refused');

    errors = [];
    const failed = new Navigator({
        readJson: async args => {
            if (args.includes('--check'))
                return {client_id: 'client-2', window_token: clientWindowToken('client-2'), boot_id: 'boot-1'};
            throw new Error('client disconnected');
        },
        getWindowActors: () => [{meta_window: first}],
        activateWindow: () => { activated = true; },
        closeMenu: () => { throw new Error('menu must stay open'); },
        notifyError: (message, error) => errors.push(`${message}: ${error.message}`),
    });
    check(!await failed.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'}),
        'Asynchronous focus failure rejected');
    check(!activated && errors[0].includes('client disconnected'), 'Async failure refused');

    let reads = 0;
    errors = [];
    actorList = [{meta_window: first}];
    const stale = new Navigator({
        readJson: async args => {
            if (args.includes('--check'))
                return {client_id: 'client-2', window_token: clientWindowToken('client-2'), boot_id: 'boot-1'};
            return {client_id: 'client-2', window_token: clientWindowToken('client-2'), boot_id: 'boot-1', focused: true};
        },
        getWindowActors: () => {
            reads++;
            return reads === 1 ? [{meta_window: first}] : [{meta_window: {get_title: () => '[herdr-client:client-2] replaced'}}];
        },
        activateWindow: () => { activated = true; },
        closeMenu: () => { throw new Error('menu must stay open'); },
        notifyError: (message, error) => errors.push(`${message}: ${error.message}`),
    });
    check(!await stale.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'}), 'Stale window rejected');
    check(!activated && errors[0].includes('changed during focus'), 'Stale activation refused');
})().catch(error => { printerr(error.stack); System.exit(1); });
""")

    def test_navigation_close_after_check_does_not_issue_focus(self):
        self.run_gjs("""
let resolveCheck;
const calls = [];
    const navigator = new Navigator({
    readJson: args => {
        calls.push(args);
        return new Promise(resolve => { resolveCheck = resolve; });
    },
    getWindowActors: () => [{meta_window: {title: '[herdr-client:client-3] terminal'}}],
    activateWindow: () => { throw new Error('window must not activate'); },
    closeMenu: () => { throw new Error('menu must not close'); },
    notifyError: () => { throw new Error('close must suppress notifications'); },
});
(async () => {
    const operation = navigator.focus({serverId: 'local', paneId: 'w1:p3', bootId: 'boot-1', location: 'Local'});
    navigator.close();
    resolveCheck({client_id: 'client-3', window_token: clientWindowToken('client-3'), boot_id: 'boot-1'});
    check(!await operation, 'Closed navigation rejected');
    check(calls.length === 1 && calls[0].at(-3) === '--check' &&
        calls[0].at(-2) === '--expected-boot' && calls[0].at(-1) === 'boot-1',
        'Closed navigation did not issue focus');
})().catch(error => { printerr(error.stack); System.exit(1); });
""")

    def test_navigation_rejects_agents_without_boot_identity(self):
        self.run_gjs("""
const calls = [];
const errors = [];
const navigator = new Navigator({
    readJson: async args => { calls.push(args); throw new Error('must not run'); },
    getWindowActors: () => [],
    activateWindow: () => { throw new Error('window must not activate'); },
    closeMenu: () => { throw new Error('menu must not close'); },
    notifyError: (message, error) => errors.push(error.message),
});
(async () => {
    check(!await navigator.focus({serverId: 'local', paneId: 'w1:p3', location: 'Local'}),
        'Missing boot identity rejected');
    check(calls.length === 0 && errors[0].includes('server boot identity'),
        'Missing boot identity did not stop the CLI request');
})().catch(error => { printerr(error.stack); System.exit(1); });
""")


if __name__ == "__main__":
    unittest.main()
