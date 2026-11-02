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
homestack AI Usage service (hs-usage). Two HTTP agent items read
`{$AI.USAGE.URL}/api/dashboard/snapshot?range=1h` and `range=24h` every 5 minutes; the
service already handles per-session counters, the three collectors' delta gauges and the
estimated Codex cost, so the values match its dashboard.

| Items | Windows |
| --- | --- |
| All agents: cost, tokens (total, input, output, cache read/write, reasoning), cache hit ratio, sessions | 1h, 24h |
| Claude Code: the same plus active time, commits, lines added/removed, API request duration and time to first token | 1h, 24h |
| Codex: the same plus reasoning tokens, turns, tool calls, turn/tool durations, time to first token/output | 1h, 24h |
| LLD *Models*: cost, total and output tokens per agent and model | 24h |
| LLD *Machines and projects*: cost and tokens per host and per repository | 24h |
| Per day and per 3 hours (UTC buckets): cost and total tokens, all agents / Claude Code / Codex | 1d, 3h |

A metric an agent does not report is skipped, not an error. Triggers: no data from the
service for 30 minutes; all agents together over `{$AI.COST.24H.WARN}` USD (default 150)
in 24 hours.

Zabbix stores values from the import on. Past buckets can be pushed into the per-day and
per-3-hour items (`history.push`; 30 days of days and 7 days of 3-hour buckets, the finest the
service returns); days already stored are skipped, so
it can be re-run. Pushed numbers pass the items' JavaScript unchanged. The pushing address must match `{$AI.PUSH.ALLOWED}` on the host (default
`127.0.0.1`; Zabbix sees API clients as IPv4-mapped, e.g. `::ffff:10.0.0.0/120`).

```bash
python3 zabbix/build_ai_usage_template.py                                      # dry run
python3 zabbix/build_ai_usage_template.py --import http://ZABBIX TOKENFILE --run  # write and import
python3 zabbix/build_ai_usage_template.py --dashboard http://ZABBIX TOKENFILE --run  # global dashboard
python3 zabbix/build_ai_usage_template.py --backfill http://ZABBIX TOKENFILE      # dry run: list past days
python3 zabbix/build_ai_usage_template.py --backfill http://ZABBIX TOKENFILE --run  # push them
```

Then create one host (no interface) with the template and set `{$AI.USAGE.URL}` on it.

`--dashboard URL TOKENFILE --run` creates (or updates) the global dashboard *AI agents* for
that host (`--host`, default `ai-usage`): cost, tokens, sessions and cache hit of the last day,
cost and tokens per 3 hours (bars, following the dashboard time period), per day (30 days), cost by model, project
and machine, and the main Claude Code and Codex activity figures.
