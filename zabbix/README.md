# Zabbix

## build_pve_templates.py

Generates Zabbix templates for Proxmox VE from data already in Prometheus: the Proxmox
built-in metric server (`job="proxmox-ve"`, `proxmox_node_*`, `proxmox_vm_*`) and
homestack-pve-agent (`job="homestack-pve-agent"`, `hs_pve_*` cgroup metrics).

| Template | Purpose |
| --- | --- |
| PVE cluster by Prometheus | One host; LLD creates a host per node (group *PVE nodes*) and per running guest (group *PVE guests*). A node or guest no longer reported is disabled at once and deleted after 30 days. |
| PVE node by Prometheus | Load average, CPU, memory (ZFS ARC counted as available), swap, network, uptime. |
| PVE guest by Prometheus | CPU and memory as shown by Proxmox, cgroup CPU and throttling, PSI pressure, OOM kills, disk I/O, network, uptime, LXC/VM file systems (snap/ISO images skipped). |

Item names match the standard Linux templates (`CPU utilization`, `Load average (1m avg)`,
`Number of processes`), so dashboard *Top hosts* widgets list nodes and guests.

Every template fetches `{$PROM.URL}/federate` once a minute; define `{$PROM.URL}` as a global
macro (Administration → Macros). Thresholds are `{$PVE.*}` macros.

```bash
python3 zabbix/build_pve_templates.py                                      # dry run
python3 zabbix/build_pve_templates.py --run                                # write pve-templates.json
python3 zabbix/build_pve_templates.py --import http://ZABBIX TOKENFILE --run  # write and import
```

Then create one host (no interface needed) with the *PVE cluster by Prometheus* template.
`pve-templates.json` can also be imported by hand under Data collection → Templates → Import.

## build_ai_usage_template.py

Generates the template *AI coding agents by HTTP*: Claude Code and Codex usage from the
homestack AI Usage service (hs-usage), `{$AI.USAGE.URL}/api/dashboard/snapshot?range=...`.
The service already handles per-session counters, the three collectors' delta gauges and the
estimated Codex cost, so the values match its dashboard.

| Items | Windows |
| --- | --- |
| All agents: cost, tokens (total, input, output, cache read/write, reasoning), cache hit ratio, sessions | rolling 1h, 24h |
| Claude Code: the same plus active time, commits, lines added/removed, API request duration and time to first token | rolling 1h, 24h |
| Codex: the same plus reasoning tokens, turns, tool calls, turn/tool durations, time to first token/output | rolling 1h, 24h |
| LLD *Models*: cost, total and output tokens per agent and model | rolling 24h |
| LLD *Machines and projects*: cost and tokens per host and per repository | rolling 24h |
| Cost and total tokens (all agents / Claude Code / Codex) | per day, 3 hours, 10 minutes |
| Sessions, cache hit, Claude Code activity and API timings, Codex turns, tools and timings; LLD cost per model, project and machine | per 3 hours, 10 minutes |

Rolling items depend on two snapshot items polled every 5 minutes. Bucket items (per day,
3 hours, 10 minutes, UTC) read their own snapshot shortly after each bucket closes and store
that bucket's value. A metric an agent does not report is skipped, not an error. Triggers: no
data from the service for 30 minutes; all agents together over `{$AI.COST.24H.WARN}` USD
(default 150) in 24 hours.

Bucket items accept `history.push`, so `--backfill` fills their past from the service: per day
from the 30-day view, per 3 hours from 7 days. Per-10-minute history is pushed in the largest
chunks a snapshot still covers (a day, 3 hours, 30 minutes, 10 minutes), one value per chunk,
so sums over any period stay right. Buckets already stored are skipped, so it can be re-run.
Pushed numbers pass the items' JavaScript unchanged. The pushing address must match
`{$AI.PUSH.ALLOWED}` on the host (default `127.0.0.1`; Zabbix sees API clients as
IPv4-mapped, e.g. `::ffff:10.0.0.0/120`). The service computes counter increases per bucket,
so totals over the same time can differ by a few percent between bucket sizes.

```bash
python3 zabbix/build_ai_usage_template.py                                         # dry run
python3 zabbix/build_ai_usage_template.py --import http://ZABBIX TOKENFILE --run     # write and import
python3 zabbix/build_ai_usage_template.py --dashboard http://ZABBIX TOKENFILE --run  # global dashboard
python3 zabbix/build_ai_usage_template.py --backfill http://ZABBIX TOKENFILE         # dry run: list past buckets
python3 zabbix/build_ai_usage_template.py --backfill http://ZABBIX TOKENFILE --run   # push them
```

Create one host (no interface) with the template and set `{$AI.USAGE.URL}` on it, import,
wait until discovery has created the per-model and per-scope items, then backfill.

`--dashboard` creates (or updates) the global dashboard *AI agents* for that host (`--host`,
default `ai-usage`). Everything on it follows the dashboard's time period: value tiles and pie
charts sum (or average) the per-10-minute items, so *Last 1 hour* works with up to about 13
minutes of delay; bars show the per-3-hour and per-day items.
