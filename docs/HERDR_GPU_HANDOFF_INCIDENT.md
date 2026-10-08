# GPU Herdr handoff incident and Codex terminal recovery

## What happened on 2026-10-08

Herdr was updated on the saved `gpu` machine (`user@gpu`). The running server
was replaced through `server live-handoff`. The replacement initially imported
all four panes, but was terminated immediately afterward. Reconnecting started
a new Herdr server, which restored the workspace and tab layout with empty
shells instead of the original terminal processes.

The old server ran under the user's `herdr.service`, configured with
`Type=simple` and `KillMode=control-group`. A handoff child inherits that
service's control group; creating a new process session does not escape it.
When the old main process exits, systemd can terminate the remaining processes
in that group. This configuration explains the replacement's immediate
termination. The Herdr log records `SIGTERM`, but does not identify its sender.

The relevant GPU server log sequence was:

| Time (UTC) | Event |
| --- | --- |
| 02:33:49.821 | Live handoff started from server PID `1788084`. |
| 02:33:49.830 | Import server PID `3412460` spawned. |
| 02:33:49.866 | Import reported ready with four panes. |
| 02:33:49.965 | Handoff completed; the old server began exiting. |
| 02:33:50.078 | Import server began shutting down after `SIGTERM`. |
| 02:33:50.134–02:33:50.167 | All four original pane sessions terminated with `Hangup`. |
| 02:33:50.612 | Ordinary server PID `3412519` started and restored the saved layout. |

Read-only inspection subsequently found one Herdr session, `default`, with
workspace `w9` rooted at `/srv/ai/research` and four tabs. There was no second
running Herdr server containing the original terminals. Running `herdr` or
`herdr session attach default` opened the restored layout; it could not recover
the terminated pane processes.

The session file and pre-incident layout snapshots still existed under
`~/.config/herdr/`. Their presence did not prove that every computation or
unsaved piece of state had survived.

## What survived outside Herdr

A separate Codex shared app-server was still running on GPU:

- PID `3003410`: `codex app-server --listen unix:// --managed-daemon`.
- PID `32343`: its daemon supervisor.
- PID `3003799`: its code-mode host.
- Installed daemon release: `0.161.0-x86_64-unknown-linux-musl`.

These were three cooperating processes, not evidence of three separate agents.
The app-server's process working directory was
`/home/user/DEV/test20261001_1`. That directory identified where the server
process was launched, not the workspaces of the conversations it served.

An initial diagnosis incorrectly concluded that research work had stopped
because the original terminal clients were gone and a single GPU process
snapshot showed no compute jobs. The user observed growing logs and continuing
work. Neither an empty Herdr agent inventory nor an instantaneous GPU process
snapshot was sufficient to establish that daemon-owned work had stopped.

## How the existing conversation was recovered

The installed Codex CLI help exposed `agents`, which browses sessions on the
shared app-server, and `--remote unix://`, which connects its UI to that server.
In a normal SSH terminal on GPU, the user ran:

```bash
/proc/3003410/exe agents --remote unix://
```

Using `/proc/3003410/exe` selected the exact executable of the already running
server. This PID is historical and must not be reused after that process exits.
With the matching Codex release installed on `PATH`, the command is:

```bash
codex agents --remote unix://
```

The user selected the existing research conversation. Its UI showed
`/srv/ai/research`, the earlier conversation history, and ongoing work. This
confirmed recovery of that conversation; it did not establish the state of
every other conversation or computation.

To put that same view back inside Herdr, the user opened a shell pane on the
**GPU endpoint**, ran the same `agents --remote unix://` command there, and
selected the same conversation. After the conversation was visible in Herdr,
the previous SSH terminal view could be closed. The user confirmed that both
the conversation and the GNOME widget's navigation to the correct pane worked.

This attached a UI to the existing daemon-owned conversation. No new task,
fork, restart, or continuation message was needed. `Esc` was not a detach key:
the working UI explicitly labeled it as an interrupt action. This recovery
was verified with a shared app-server, not with Codex's `--no-daemon` mode.

## Lessons for another incident

Check the exact Herdr session and server before attaching. If the original
pane processes have exited, attaching to the restored layout does not bring
those processes back. Inspect independent agent daemons and identify the
existing conversation before considering any restart, to avoid duplicate work.

Do not treat live handoff as safe under a systemd service with
`KillMode=control-group` without addressing replacement process ownership.
This incident was not repaired by changing the service or handoff code; the
successful recovery restored the Codex UI through its independently surviving
daemon.

Diagnostic commands during recovery only read process metadata, saved layouts,
CLI help, and server state. They did not start or stop research jobs or send
messages to the agents. The successful final check was the user's live
confirmation, not an automated test that all research data had survived.
