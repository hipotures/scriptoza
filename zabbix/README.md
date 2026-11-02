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
