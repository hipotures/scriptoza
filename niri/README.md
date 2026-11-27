# niri (Noctalia) Plugins

Ports of the GNOME panel widgets in [`gnome/`](../gnome/README.md) to [Noctalia](https://noctalia.dev) v5, the
shell used with the niri compositor. Each directory is a Noctalia plugin written in Luau (plugin API 53):

- `rtorrent-status/` - local or remote `rtorrent` states, transfer rates, sorting, anonymization, and
  multi-server switching
- `agentai-status/` - local and remote Herdr Codex, Claude Code, and Antigravity agent states
- `agent-accounts/` - read-only Claude, Antigravity, and Codex account usage from the homestack Agent Accounts service

The rTorrent and Herdr plugins keep the GNOME look: Cairo-like colored dots in the bar and a list panel attached to the widget.
Hovering over a widget shows a read-only preview next to the bar, at the end where the status widgets sit (above a
bottom bar, below a top bar, beside a vertical bar; it follows `bar.default.position`). The preview
is a plugin-owned layer (`[[layer]] preview`), 640 px wide with smaller fonts, because the shell tooltip has a
fixed width that truncates torrent and agent names. It ignores pointer input and disappears when the pointer leaves
the widget or the widget is clicked. A left click opens the editable panel in the middle of the bar, like the
built-in Noctalia panels.

## Installation

Run this from a niri session with Noctalia running:

```bash
bash niri/install.sh                   # all plugins
bash niri/install.sh rtorrent-status   # one plugin
```

The installer:

1. Copies the plugins to `~/.local/share/scriptoza/noctalia-plugins/` (`XDG_DATA_HOME` is honored). The Herdr
   plugin also gets the status worker and icons from `gnome/agentai-status/` in its `worker/` subdirectory.
2. Registers that directory as the `scriptoza` path source (`noctalia msg plugins source list`).
3. Enables the plugins.
4. Puts the widgets at the start of the bar's `end` section, in the same order as the GNOME panel:
   rTorrent first, then Herdr, then Agent Accounts.

Set `NOCTALIA_BAR` to use a bar other than `default`. Running the installer again applies updates
without restarting the shell; it disables and re-enables each installed plugin to reload it.

During development, register the checkout itself instead:
`noctalia msg plugins source add scriptoza path "$PWD/niri"`. In that layout, the Herdr plugin reads the worker
directly from `gnome/agentai-status/`. Run `noctalia plugins lint niri/<plugin>` to check manifests.

## rTorrent Status

`rtorrent-status` has three entries:

- `service`: polls rTorrent every `pollSeconds` and publishes one snapshot to the plugin's shared state.
- `bar`: shows the dots.
- `panel`: shows the torrent list.

Noctalia plugins cannot open TCP sockets, so `rtorrent_rpc.py` (Python standard library only) speaks SCGI.
Like the GNOME extension, it automatically detects JSON-RPC, XML-RPC `d.multicall2`, and legacy XML-RPC
`d.multicall`; the detected mode is cached per server. Requirements: `python3` and `rtorrent` with SCGI enabled
(see [gnome/README.md](../gnome/README.md#requirements)).

Configuration is the same `~/.config/scriptoza/rtorrent-status.json` file used by the GNOME extension. A missing
file is created with defaults. The panel's gear opens inline settings for the server list (switch, edit, add,
remove), size, sort, and anonymization. Changes are saved to the file and polled again immediately.

Bar and panel states match the GNOME table:

- One solid dot for each non-paused torrent.
- A ring with a center dot when all torrents are paused.
- An empty ring for an empty queue.
- A slowly pulsing yellow ring when the server is unreachable.
- A blinking red dot for an error.

The hover preview lists up to 20 torrents with their progress, rates, ETA, and state, followed by the total rates
and the last update time. Unreachable servers show the server and error instead. Hovering a torrent row in the
panel shows peers, rates, uploaded bytes, and ratio. The footer shows total rates, the last
update time, and the plugin version.

```bash
noctalia msg plugin scriptoza/rtorrent-status:service all refresh   # poll now
noctalia msg panel-toggle scriptoza/rtorrent-status:panel            # open the list
```

## Herdr Agent Status

`agentai-status` runs the GNOME extension's GJS status worker. The worker handles Herdr event subscriptions,
remote SSH machines, activity tracking, and usage limits, and the plugin republishes each update. Noctalia
connects its stdin to `/dev/null`, so the plugin starts the worker with `--detached-stdin`. In that mode, the
worker stops when Noctalia sends SIGTERM on reload or disable, or when its parent process changes. A worker that
exits is reported in the panel; reload the plugin to restart it. Requirements: `gjs`, `herdr`, OpenSSH, and GNU
coreutils `timeout`.

The bar shows:

- One dot for each non-idle agent.
- A ring with a center dot when all agents are idle.
- An empty ring when there are no agents.
- A pulsing yellow ring while waiting for the local Herdr server.
- A blinking dot for a `blocked` agent.

The hover preview lists usage limits, up to 20 agents with their session title and state, and unavailable
machines. The panel lists usage limits (5-hour and weekly windows), agents sorted as in the GNOME extension, and
unavailable machines. Hovering a row shows its machine/workspace/tab/pane location. The gear cycles the density;
the setting is saved in `~/.config/ai-agent-status/config.json`, shared with GNOME.

Clicking an agent row first checks the target with `herdr agent focus --check`. It then finds the terminal window
whose title contains the client's unique `[herdr-client:<ID>]` marker in `niri msg --json windows`, focuses the
pane in that Herdr client, and confirms that the same window still matches. Finally, it focuses the window with
`niri msg action focus-window`. Failures are shown as notifications.

## Agent Accounts

`agent-accounts` shows the state of the accounts kept by the homestack Agent Accounts service. It is read-only:
the service entry sends only `GET /health/ready` and `GET /api/v1/profiles` with `curl` every `pollSeconds`
(default 60). It never starts checks, usage windows, authentication, or other provider calls, and it does not
change account data such as the last payment. Requirement: `curl`.

The bar shows one ring per shown account in the provider color (Claude orange, Antigravity blue, Codex green). A
center disc grows with the highest used percentage among the account's windows, so an empty ring means unused and a
full dot means exhausted. Accounts with errors, stale data, or disabled checks are dimmed. A pulsing yellow ring
means the service cannot be reached (for example HTTP 401 behind Pangolin authentication); a pulsing red ring means
its health check fails.

The hover preview lists each account with its plan, subscription end, and windows. The panel shows one card per
account, one below another: provider, email, plan, `Ends in` (last payment plus one month, else the provider
period end), each window with used/left percentages, a bar, and its reset time, and the last successful check. The
footer shows the service health.

Settings live in `~/.config/scriptoza/agent-accounts.json` and in the panel's gear:

- Connection: switch, edit, add, or remove service addresses (`http://limits.homestack.app:8080/` and
  `https://limits.hs.armum.eu/` by default).
- Show free accounts (`plan` equal to `free`); hidden by default.
- Account order (up/down).
- Antigravity quota group per account (Gemini by default, or Claude & GPT).

```bash
noctalia msg plugin scriptoza/agent-accounts:service all refresh   # poll now
noctalia msg panel-toggle scriptoza/agent-accounts:panel            # open the cards
```

## Differences from GNOME

- Panel sizes are fixed in each `plugin.toml` because Noctalia owns panel geometry. Density changes font sizes
  and row spacing, not the panel width.
- Row tooltips use Noctalia's hover delay instead of the fixed 600 ms delay.
- The widget summary is a hover preview layer instead of a tooltip naming the widget.
- The Codex icon follows Noctalia's dark-mode setting instead of the GNOME menu text color.
