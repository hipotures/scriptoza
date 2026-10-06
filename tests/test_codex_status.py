"""Offline GJS tests for the GNOME Codex status indicator."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


EXTENSION = Path(__file__).resolve().parents[1] / "ai" / "codex-status"


@unittest.skipUnless(shutil.which("gjs"), "GJS is required")
class CodexStatusTests(unittest.TestCase):
    def run_gjs(self, body):
        imports = f"""
import GLib from 'gi://GLib';
import System from 'system';
import {{normalizeAgents, summarize, sortAgents}} from '{(EXTENSION / 'model.js').as_uri()}';
import {{Collector, POLL_SECONDS}} from '{(EXTENSION / 'collector.js').as_uri()}';
import {{selectClientWindow}} from '{(EXTENSION / 'navigation.js').as_uri()}';
function check(condition, message) {{ if (!condition) throw new Error(message); }}
function snapshot(states = ['working']) {{
    return {{
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
                ["gjs", "-m", str(script)], capture_output=True, text=True, timeout=15
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("CRITICAL", result.stderr)

    def test_navigation_matches_terminal_process_ancestry(self):
        self.run_gjs("""
const clients = [{pid: 50, ancestor_pids: [20, 1]}, {pid: 51, ancestor_pids: [21, 1]}];
const first = {};
const second = {};
const windows = [{pid: 20, userTime: 10, window: first}, {pid: 21, userTime: 30, window: second},
    {pid: 80, userTime: 50, window: {}}];
const selected = selectClientWindow(clients, windows);
check(selected.pid === 51 && selected.window === second, 'Most recently used Herdr window');
let rejected = false;
try { selectClientWindow(clients, [{pid: 80}]); } catch { rejected = true; }
check(rejected, 'Do not raise unrelated desktop windows');
rejected = false;
try { selectClientWindow([...clients, {pid: 52, ancestor_pids: [21]}], windows); }
catch { rejected = true; }
check(rejected, 'Do not select an ambiguous client in a terminal window');
rejected = false;
try { selectClientWindow(clients, [...windows, {pid: 21, userTime: 40, window: {}}]); }
catch { rejected = true; }
check(rejected, 'Do not raise unrelated windows sharing a terminal server process');
""")

    def test_navigation_routes_to_local_client_with_explicit_remote_identity(self):
        self.run_gjs("""
const loop = new GLib.MainLoop(null, false);
const collector = new Collector();
const calls = [];
let accepted = true;
collector._readJson = async args => {
    calls.push(args);
    return args[1] === 'list' ? {clients: [{pid: 50, ancestor_pids: [20]}]} : {accepted};
};
(async () => {
    check((await collector.listClients())[0].pid === 50, 'Discover client');
    await collector.focusClient(50, {serverId: 'gpu-id', paneId: 'w1:p0'});
    check(calls[1].join(' ') === 'client focus --client-pid 50 --endpoint gpu-id --pane w1:p0',
        'Remote identity routed through local TUI, not a remote server command');
    await collector.focusClient(50, {serverId: 'local', paneId: 'w1:p0'});
    check(calls[2].includes('local'), 'Local identity remains explicit');
    accepted = false;
    let rejected = false;
    try { await collector.focusClient(50, {serverId: 'local', paneId: 'gone'}); }
    catch { rejected = true; }
    check(rejected, 'Rejected navigation must not appear successful');
    collector._readJson = async () => ({clients: [{pid: 0, ancestor_pids: []}]});
    rejected = false;
    try { await collector.listClients(); } catch { rejected = true; }
    check(rejected, 'Malformed clients rejected');
})().catch(error => { printerr(error.stack); System.exit(1); }).finally(() => { collector.close(); loop.quit(); });
loop.run();
""")

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
check(summarize([], [{machine: 'gpu'}]).state === 'offline', 'Disconnected with no agents');
""")

    def test_remote_names_and_identity_filtering(self):
        self.run_gjs("""
const data = snapshot();
data.agents.push({...data.agents[0], agent: 'claude'});
data.agents.push({...data.agents[0], pane_id: 'gone'});
data.agents.push({...data.agents[0]});
data.workspaces[0].label = 'project\n  name';
const local = normalizeAgents(data, {id: 'local', label: 'Local'});
const remote = normalizeAgents(data, {id: 'gpu-id', label: 'gpu'});
check(local.length === 1 && remote.length === 1, 'Only live Codex agents, no duplicates');
check(local[0].id !== remote[0].id, 'Machine-scoped identities');
check(remote[0].location === 'gpu/project name:run:p0', 'Remote display name');
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
    check(POLL_SECONDS === 5, 'Polling interval');
    let result = await collector.collect();
    check(result.agents.length === 2 && result.errors.length === 0, 'Local and remote Codexes');
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


if __name__ == "__main__":
    unittest.main()
