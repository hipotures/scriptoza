"""Offline GJS tests for the GNOME Codex status indicator."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


EXTENSION = Path(__file__).resolve().parents[1] / "ai" / "codex-status"


@unittest.skipUnless(shutil.which("gjs"), "GJS is required")
class CodexStatusTests(unittest.TestCase):
    def run_gjs(self, body, env=None):
        imports = f"""
import GLib from 'gi://GLib';
import System from 'system';
import {{normalizeAgents, summarize, sortAgents}} from '{(EXTENSION / 'model.js').as_uri()}';
import {{Collector, POLL_SECONDS}} from '{(EXTENSION / 'collector.js').as_uri()}';
import Gio from 'gi://Gio';
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

    def test_status_worker_spawns_once_and_preserves_machine_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "herdr"
            fake.write_text("""#!/usr/bin/python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['STATUS_REQUEST_LOG'], 'a') as log:
    log.write(' '.join(args) + '\\n')
if args[:2] == ['machine', 'list']:
    print(json.dumps([dict(id='gpu-id', label='GPU', enabled=True)]))
else:
    print(json.dumps(dict(result=dict(snapshot=dict(
        boot_id='worker-boot',
        agents=[dict(agent='codex', agent_status='done', pane_id='w1:p3',
                     tab_id='w1:t1', workspace_id='w1')],
        panes=[dict(pane_id='w1:p3')], tabs=[dict(tab_id='w1:t1', label='run')],
        workspaces=[dict(workspace_id='w1', label='project')])))))
""", encoding="utf-8")
            fake.chmod(0o755)
            env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}",
                   "STATUS_REQUEST_LOG": str(Path(directory) / "requests")}
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{EXTENSION / 'status-worker.js'}');
const launches = [];
const spawn = Gio.Subprocess.new;
Gio.Subprocess.new = (args, flags) => {{ launches.push(args); return spawn(args, flags); }};
function pause(ms) {{ return new Promise(resolve => GLib.timeout_add(GLib.PRIORITY_DEFAULT, ms,
    () => {{ resolve(); return GLib.SOURCE_REMOVE; }})); }}
(async () => {{
    let first = await worker.collect();
    const pid = worker._process.get_identifier();
    const second = await worker.collect();
    check(worker._process.get_identifier() === pid && launches.length === 1,
        'Polling spawned more processes inside the Shell instead of reusing its worker');
    check(first.agents.length === 2 && second.agents.length === 2 && second.metrics.requests === 3,
        'Worker did not preserve snapshot polling');
    check(first.agents[0].paneId === first.agents[1].paneId &&
        first.agents[0].id !== first.agents[1].id && first.agents[1].serverId === 'gpu-id' &&
        first.agents.every(agent => agent.bootId === 'worker-boot'), 'Machine or boot identities lost');
    const [, bytes] = GLib.file_get_contents(GLib.getenv('STATUS_REQUEST_LOG'));
    check(new TextDecoder().decode(bytes).trim().split('\\n').length === 6, 'Extra worker polling');
    worker.close();
    await pause(150);
    check(!worker._process && !worker._killSource && !worker._deadline &&
        !GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS), 'Disable left a worker running');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""", env=env)

    def test_failed_status_worker_does_not_respawn_on_every_poll(self):
        with tempfile.TemporaryDirectory() as directory:
            worker_file = Path(directory) / "worker.js"
            worker_file.write_text('print("invalid");', encoding="utf-8")
            self.run_gjs(f"""
const loop = new GLib.MainLoop(null, false);
const worker = new StatusProcess('{worker_file}');
const launches = [];
const spawn = Gio.Subprocess.new;
Gio.Subprocess.new = (args, flags) => {{ launches.push(args); return spawn(args, flags); }};
(async () => {{
    for (let index = 0; index < 3; index++) {{
        let failed = false;
        try {{ await worker.collect(); }} catch {{ failed = true; }}
        check(failed, 'Broken worker response was accepted');
    }}
    check(launches.length === 1 && !worker._deadline, 'Broken worker respawned on every poll');
}})().catch(error => {{ printerr(error.stack); System.exit(1); }}).finally(() => {{ worker.close(); loop.quit(); }});
loop.run();
""")

    def test_status_worker_shutdown_stops_active_command_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "herdr"
            fake.write_text("""#!/usr/bin/python3
import json, os, pathlib, signal, subprocess, sys, time
if sys.argv[1:3] == ['machine', 'list']:
    print('[]')
    sys.exit(0)
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
    const pending = worker.collect().catch(() => null);
    const pid = worker._process.get_identifier();
    const file = GLib.getenv('STATUS_CHILD_PIDS');
    for (let index = 0; index < 100 && !GLib.file_test(file, GLib.FileTest.EXISTS); index++)
        await pause(20);
    check(GLib.file_test(file, GLib.FileTest.EXISTS), 'Command fixture failed to start');
    const [, bytes] = GLib.file_get_contents(file);
    const pids = JSON.parse(new TextDecoder().decode(bytes));
    worker.close();
    await pending;
    for (let index = 0; index < 100 && worker._process; index++)
        await pause(20);
    check(!worker._process && !worker._killSource && !worker._deadline, 'Worker was not reaped');
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
    const pending = worker.collect().catch(() => null);
    const pid = worker._process.get_identifier();
    await pause(200);
    worker.close();
    await pending;
    await pause(2200);
    check(!worker._process && !worker._killSource && !worker._deadline &&
        !GLib.file_test(`/proc/${{pid}}`, GLib.FileTest.EXISTS), 'Unresponsive worker survived shutdown');
    const immediate = new StatusProcess('{EXTENSION / 'status-worker.js'}');
    const collecting = immediate.collect().catch(() => null);
    immediate.close();
    await collecting;
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
    const result = await navigator.focus({serverId: 'gpu-id', paneId: 'w2:p5', bootId: 'boot-7', location: 'GPU/project:run:p5'});
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
