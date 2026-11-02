#!/usr/bin/env python3
"""Build (and optionally import) Zabbix templates for Proxmox VE nodes and guests from Prometheus.

Data: Proxmox's built-in metric server (job="proxmox-ve", proxmox_node_*/proxmox_vm_*) and
homestack-pve-agent (job="homestack-pve-agent", hs_pve_* cgroup metrics), both in Prometheus.

  PVE cluster by Prometheus  one host; LLD creates a host per node and per running guest
  PVE node by Prometheus     real load average, CPU, memory, ZFS ARC, network, uptime
  PVE guest by Prometheus    CPU/memory as Proxmox shows them, cgroup CPU, PSI, OOM, I/O, file systems

A guest or node that stops being reported is disabled at once and deleted after 30 days.
{$PROM.URL} is expected as a global macro (Administration > Macros).

  build_pve_templates.py                                   dry run: show what would be written/imported
  build_pve_templates.py --run                             write pve-templates.json
  build_pve_templates.py --import URL TOKENFILE --run      write and import (create/update)
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path

NS = uuid.UUID('0f5d7c52-58a6-4f5e-9d0c-3a2b1c4e7f90')
CLUSTER, NODE, GUEST = 'PVE cluster by Prometheus', 'PVE node by Prometheus', 'PVE guest by Prometheus'
GROUP = 'Templates/Virtualization'
NODE_GROUP, GUEST_GROUP = 'PVE nodes', 'PVE guests'
MASTER = 'pve.federate'


def uid(*parts):
    return uuid.UUID(bytes=uuid.uuid5(NS, '|'.join(parts)).bytes, version=4).hex


def sel(metric, **labels):
    return metric + ('{' + ','.join(f'{k}="{v}"' for k, v in labels.items()) + '}' if labels else '')


PER_SECOND = [{'type': 'CHANGE_PER_SECOND', 'parameters': ['']}]
BITS = PER_SECOND + [{'type': 'MULTIPLIER', 'parameters': ['8']}]
PERCENT = [{'type': 'MULTIPLIER', 'parameters': ['100']}]


class Builder:
    def __init__(self, template):
        self.t = template
        self.p = f'/{template}/'

    def master(self, name, matches, description):
        return {'uuid': uid(self.t, 'item', MASTER), 'name': name, 'type': 'HTTP_AGENT', 'key': MASTER, 'delay': '1m',
                'history': '0', 'value_type': 'TEXT', 'trends': '0', 'url': '{$PROM.URL}/federate',
                'query_fields': [{'name': 'match[]', 'value': m} for m in matches], 'description': description,
                'tags': [{'tag': 'component', 'value': 'raw'}],
                'triggers': [self.trigger(MASTER, f'nodata({self.p}{MASTER},5m)=1',
                                          'No data from Prometheus for 5 minutes', 'AVERAGE')]}

    def item(self, name, key, selector, *, value_type='FLOAT', units='', component='', extra=(), func=None,
             triggers=(), discard=False, description='', proto=False):
        output = ['function', func] if func else ['value', '']
        pre = [{'type': 'PROMETHEUS_PATTERN', 'parameters': [selector, *output]}]
        if discard:
            pre[0]['error_handler'] = 'DISCARD_VALUE'
        it = {'uuid': uid(self.t, 'proto' if proto else 'item', key), 'name': name, 'type': 'DEPENDENT', 'key': key,
              'delay': '0', 'value_type': value_type, 'units': units, 'description': description,
              'preprocessing': pre + list(extra), 'master_item': {'key': MASTER},
              'tags': [{'tag': 'component', 'value': component}] if component else []}
        if triggers:
            it['trigger_prototypes' if proto else 'triggers'] = [self.trigger(key, *t, proto=proto) for t in triggers]
        return it

    def calc(self, name, key, formula, units='%', component='', triggers=(), proto=False):
        it = {'uuid': uid(self.t, 'proto' if proto else 'item', key), 'name': name, 'type': 'CALCULATED',
              'key': key, 'delay': '1m', 'value_type': 'FLOAT', 'units': units, 'params': formula,
              'tags': [{'tag': 'component', 'value': component}] if component else []}
        if triggers:
            it['trigger_prototypes' if proto else 'triggers'] = [self.trigger(key, *t, proto=proto) for t in triggers]
        return it

    def trigger(self, key, expression, name, priority, description='', proto=False):
        return {'uuid': uid(self.t, 'tproto' if proto else 'trigger', key, name), 'expression': expression,
                'name': name, 'priority': priority, 'description': description}

    def last(self, key):
        return f'last({self.p}{key})'


def node_template():
    b = Builder(NODE)
    n = '{$PVE.NODE}'
    items = [
        b.master('Prometheus federate: PVE node', ['{job="proxmox-ve",node="' + n + '",__name__=~"proxmox_node_(cpustat|memory|network|uptime).*"}'],
                 'Proxmox metric-server samples of this node; every other item depends on it.'),
        b.item('Load average (1m avg)', 'pve.node.load1', 'proxmox_node_cpustat_avg1_ratio', component='cpu'),
        b.item('Load average (5m avg)', 'pve.node.load5', 'proxmox_node_cpustat_avg5_ratio', component='cpu'),
        b.item('Load average (15m avg)', 'pve.node.load15', 'proxmox_node_cpustat_avg15_ratio', component='cpu'),
        b.item('Number of CPUs', 'pve.node.cpus', 'proxmox_node_cpustat_cpus_ratio', value_type='UNSIGNED', component='cpu'),
        b.item('CPU utilization', 'pve.node.cpu', 'proxmox_node_cpustat_cpu_percent', units='%', component='cpu',
               extra=PERCENT, triggers=[(f'min({b.p}pve.node.cpu,15m)>{{$PVE.CPU.UTIL.WARN}}',
                                         'High CPU utilization (over {$PVE.CPU.UTIL.WARN}% for 15m)', 'WARNING')]),
        b.item('CPU iowait', 'pve.node.iowait', 'proxmox_node_cpustat_iowait_seconds_total', units='s/s', component='cpu',
               extra=PER_SECOND, discard=True),
        b.item('Memory total', 'pve.node.mem.total', 'proxmox_node_memory_memtotal_bytes', value_type='UNSIGNED',
               units='B', component='memory'),
        b.item('Memory available', 'pve.node.mem.avail', 'proxmox_node_memory_memavailable_bytes', value_type='UNSIGNED',
               units='B', component='memory'),
        b.item('ZFS ARC size', 'pve.node.arc', 'proxmox_node_memory_arcsize_bytes', value_type='UNSIGNED', units='B',
               component='memory', discard=True,
               description='Counted as available memory in Memory utilization: the ARC shrinks on demand.'),
        b.item('Swap used', 'pve.node.swap', 'proxmox_node_memory_swapused_bytes', value_type='UNSIGNED', units='B',
               component='memory'),
        b.calc('Memory utilization', 'pve.node.mem.util',
               '100-100*(last(//pve.node.mem.avail)+last(//pve.node.arc))/last(//pve.node.mem.total)', component='memory',
               triggers=[(f'min({b.p}pve.node.mem.util,10m)>{{$PVE.MEM.UTIL.WARN}}',
                          'High memory utilization (over {$PVE.MEM.UTIL.WARN}%)', 'WARNING')]),
        b.item('Network: bits received', 'pve.node.net.in', 'proxmox_node_network_receive_bytes_total', units='bps',
               component='network', func='sum', extra=BITS),
        b.item('Network: bits sent', 'pve.node.net.out', 'proxmox_node_network_transmit_bytes_total', units='bps',
               component='network', func='sum', extra=BITS),
        b.item('Uptime', 'pve.node.uptime', 'proxmox_node_uptime_seconds', units='uptime', component='system',
               triggers=[(f'{b.last("pve.node.uptime")}<600', 'Node has been restarted (uptime < 10m)', 'WARNING')]),
        b.calc('Load average per CPU (5m)', 'pve.node.load.percpu', 'last(//pve.node.load5)/last(//pve.node.cpus)',
               units='', component='cpu',
               triggers=[(f'min({b.p}pve.node.load.percpu,15m)>{{$PVE.LOAD.PERCPU.WARN}}',
                          'Load average is too high (per CPU load over {$PVE.LOAD.PERCPU.WARN} for 15m)', 'AVERAGE')]),
    ]
    macros = {'{$PVE.NODE}': ('', 'Node name (set by the cluster host prototype).'),
              '{$PVE.CPU.UTIL.WARN}': ('90', ''), '{$PVE.MEM.UTIL.WARN}': ('90', ''), '{$PVE.LOAD.PERCPU.WARN}': ('1.5', '')}
    return template(NODE, 'Proxmox VE node from the built-in metric server via Prometheus.', items, [], macros)


def guest_template():
    b = Builder(GUEST)
    v = '{$PVE.VMID}'
    fs_rule_items = [
        b.item('FS {#MOUNT}: total', 'pve.guest.fs.total[{#MOUNT}]', sel('hs_pve_filesystem_total_bytes', mount='{#MOUNT}'),
               value_type='UNSIGNED', units='B', component='storage', discard=True, proto=True),
        b.item('FS {#MOUNT}: used', 'pve.guest.fs.used[{#MOUNT}]', sel('hs_pve_filesystem_used_bytes', mount='{#MOUNT}'),
               value_type='UNSIGNED', units='B', component='storage', discard=True, proto=True),
        b.calc('FS {#MOUNT}: used, %', 'pve.guest.fs.pused[{#MOUNT}]',
               '100*last(//pve.guest.fs.used[{#MOUNT}])/last(//pve.guest.fs.total[{#MOUNT}])', component='storage', proto=True,
               triggers=[(f'{b.last("pve.guest.fs.pused[{#MOUNT}]")}>{{$PVE.FS.PUSED.WARN}}',
                          'File system {#MOUNT} is over {$PVE.FS.PUSED.WARN}% full', 'WARNING'),
                         (f'{b.last("pve.guest.fs.pused[{#MOUNT}]")}>{{$PVE.FS.PUSED.CRIT}}',
                          'File system {#MOUNT} is over {$PVE.FS.PUSED.CRIT}% full', 'HIGH')]),
    ]
    psi = []
    for res in ('cpu', 'memory', 'io'):
        for stall in ('some', 'full'):
            if res == 'cpu' and stall == 'full':
                continue
            psi.append(b.item(f'Pressure {res} {stall} (60s)', f'pve.guest.psi[{res},{stall}]',
                              sel('hs_pve_pressure_stall_ratio', resource=res, stall=stall, window='60s'),
                              units='%', component='pressure', extra=PERCENT, discard=True,
                              description=f'Share of time {"some" if stall == "some" else "all"} tasks waited for {res}.'))
    psi[0]['triggers'] = [b.trigger('pve.guest.psi[cpu,some]', f'min({b.p}pve.guest.psi[cpu,some],15m)>{{$PVE.PSI.CPU.WARN}}',
                                    'CPU pressure: tasks wait for CPU over {$PVE.PSI.CPU.WARN}% of the time', 'WARNING')]
    psi[2]['triggers'] = [b.trigger('pve.guest.psi[memory,full]', f'min({b.p}pve.guest.psi[memory,full],10m)>{{$PVE.PSI.MEM.WARN}}',
                                    'Memory pressure: all tasks stalled on memory over {$PVE.PSI.MEM.WARN}% of the time', 'HIGH')]
    psi[4]['triggers'] = [b.trigger('pve.guest.psi[io,full]', f'min({b.p}pve.guest.psi[io,full],15m)>{{$PVE.PSI.IO.WARN}}',
                                    'I/O pressure: all tasks stalled on I/O over {$PVE.PSI.IO.WARN}% of the time', 'WARNING')]
    items = [
        b.master('Prometheus federate: PVE guest', ['{job=~"proxmox-ve|homestack-pve-agent",vmid="' + v + '"}'],
                 'Proxmox and homestack-pve-agent samples of this guest; every other item depends on it.'),
        b.item('CPU utilization', 'pve.guest.cpu', 'proxmox_vm_cpu_percent', units='%', component='cpu', extra=PERCENT,
               description='As in the Proxmox GUI: share of the guest\'s configured CPUs.',
               triggers=[(f'min({b.p}pve.guest.cpu,15m)>{{$PVE.CPU.UTIL.WARN}}',
                          'High CPU utilization (over {$PVE.CPU.UTIL.WARN}% for 15m)', 'WARNING')]),
        b.item('Number of CPUs', 'pve.guest.cpus', 'proxmox_vm_cpus_ratio', component='cpu'),
        b.item('CPU used (cores, cgroup)', 'pve.guest.cpu.cores', 'hs_pve_cpu_usage_seconds_total', units='',
               component='cpu', extra=PER_SECOND, discard=True),
        b.item('CPU throttled', 'pve.guest.cpu.throttled', 'hs_pve_cpu_throttled_seconds_total', units='s/s',
               component='cpu', extra=PER_SECOND, discard=True),
        b.item('Memory used', 'pve.guest.mem', 'proxmox_vm_mem_bytes', value_type='UNSIGNED', units='B', component='memory'),
        b.item('Memory total', 'pve.guest.mem.max', 'proxmox_vm_maxmem_bytes', value_type='UNSIGNED', units='B', component='memory'),
        b.calc('Memory utilization', 'pve.guest.mem.util', '100*last(//pve.guest.mem)/last(//pve.guest.mem.max)',
               component='memory', triggers=[(f'min({b.p}pve.guest.mem.util,15m)>{{$PVE.MEM.UTIL.WARN}}',
                                              'High memory utilization (over {$PVE.MEM.UTIL.WARN}%)', 'WARNING')]),
        b.item('Swap used (cgroup)', 'pve.guest.swap', 'hs_pve_memory_swap_usage_bytes', value_type='UNSIGNED', units='B',
               component='memory', discard=True),
        b.item('OOM kills', 'pve.guest.oom', sel('hs_pve_memory_events_total', event='oom_kill'), value_type='UNSIGNED',
               component='memory', discard=True,
               triggers=[(f'change({b.p}pve.guest.oom)>0', 'Out-of-memory: a process was killed', 'HIGH')]),
        b.item('Number of processes', 'pve.guest.pids', 'hs_pve_pids_current', value_type='UNSIGNED', component='system', discard=True),
        b.item('Disk read', 'pve.guest.io.read', sel('hs_pve_io_bytes_total', operation='read'), units='Bps',
               component='storage', func='sum', extra=PER_SECOND, discard=True),
        b.item('Disk write', 'pve.guest.io.write', sel('hs_pve_io_bytes_total', operation='write'), units='Bps',
               component='storage', func='sum', extra=PER_SECOND, discard=True),
        b.item('Network: bits received', 'pve.guest.net.in', 'proxmox_vm_netin_bytes_total', units='bps',
               component='network', extra=BITS),
        b.item('Network: bits sent', 'pve.guest.net.out', 'proxmox_vm_netout_bytes_total', units='bps',
               component='network', extra=BITS),
        b.item('Uptime', 'pve.guest.uptime', 'proxmox_vm_uptime_seconds', units='uptime', component='system',
               triggers=[(f'{b.last("pve.guest.uptime")}<600', 'Guest has been restarted (uptime < 10m)', 'INFO')]),
        *psi,
    ]
    rules = [{'uuid': uid(GUEST, 'rule', 'fs'), 'name': 'File systems', 'type': 'DEPENDENT', 'key': 'pve.guest.fs.discovery',
              'delay': '0', 'lifetime_type': 'DELETE_IMMEDIATELY', 'master_item': {'key': MASTER},
              'filter': {'evaltype': 'AND', 'conditions': [
                  {'macro': '{#FSTYPE}', 'value': '{$PVE.FS.TYPE.NOT_MATCHES}', 'operator': 'NOT_MATCHES_REGEX',
                   'formulaid': 'A'},
                  {'macro': '{#MOUNT}', 'value': '{$PVE.FS.MOUNT.NOT_MATCHES}', 'operator': 'NOT_MATCHES_REGEX',
                   'formulaid': 'B'}]},
              'preprocessing': [{'type': 'PROMETHEUS_TO_JSON', 'parameters': ['hs_pve_filesystem_total_bytes']}],
              'lld_macro_paths': [{'lld_macro': '{#MOUNT}', 'path': '$.labels.mount'},
                                  {'lld_macro': '{#FSTYPE}', 'path': '$.labels.filesystem'}],
              'item_prototypes': fs_rule_items}]
    macros = {'{$PVE.VMID}': ('', 'Guest ID (set by the cluster host prototype).'),
              '{$PVE.CPU.UTIL.WARN}': ('90', ''), '{$PVE.MEM.UTIL.WARN}': ('95', ''),
              '{$PVE.FS.PUSED.WARN}': ('90', ''), '{$PVE.FS.PUSED.CRIT}': ('95', ''),
              '{$PVE.FS.TYPE.NOT_MATCHES}': ('^(squashfs|iso9660|udf)$', 'Read-only image file systems (snap, ISO): always 100% full.'),
              '{$PVE.FS.MOUNT.NOT_MATCHES}': ('^/snap/', ''),
              '{$PVE.PSI.CPU.WARN}': ('30', ''), '{$PVE.PSI.MEM.WARN}': ('5', ''), '{$PVE.PSI.IO.WARN}': ('20', '')}
    return template(GUEST, 'Proxmox VE VM/LXC from the built-in metric server and homestack-pve-agent via Prometheus.',
                    items, rules, macros)


def cluster_template():
    b = Builder(CLUSTER)
    lost = {'lifetime_type': 'DELETE_AFTER', 'lifetime': '30d', 'enabled_lifetime_type': 'DISABLE_IMMEDIATELY'}
    items = [b.master('Prometheus federate: PVE inventory',
                      ['{job="proxmox-ve",__name__="proxmox_node_uptime_seconds"}',
                       '{job="homestack-pve-agent",__name__="hs_pve_cpu_capacity"}'],
                      'Lists running nodes and guests for discovery.')]
    rules = [
        dict({'uuid': uid(CLUSTER, 'rule', 'nodes'), 'name': 'PVE nodes', 'type': 'DEPENDENT', 'key': 'pve.node.discovery',
              'delay': '0', 'master_item': {'key': MASTER},
              'preprocessing': [{'type': 'PROMETHEUS_TO_JSON', 'parameters': ['proxmox_node_uptime_seconds']}],
              'lld_macro_paths': [{'lld_macro': '{#NODE}', 'path': '$.labels.node'}],
              'host_prototypes': [{'uuid': uid(CLUSTER, 'hostproto', 'node'), 'host': 'pve-node-{#NODE}', 'name': '{#NODE}',
                                   'group_links': [{'group': {'name': NODE_GROUP}}],
                                   'templates': [{'name': NODE}],
                                   'macros': [{'macro': '{$PVE.NODE}', 'value': '{#NODE}'}],
                                   'tags': [{'tag': 'pve-node', 'value': '{#NODE}'}]}]}, **lost),
        dict({'uuid': uid(CLUSTER, 'rule', 'guests'), 'name': 'PVE guests', 'type': 'DEPENDENT', 'key': 'pve.guest.discovery',
              'delay': '0', 'master_item': {'key': MASTER},
              'preprocessing': [{'type': 'PROMETHEUS_TO_JSON', 'parameters': ['hs_pve_cpu_capacity']}],
              'lld_macro_paths': [{'lld_macro': m, 'path': f'$.labels.{l}'} for m, l in
                                  (('{#VMID}', 'vmid'), ('{#NAME}', 'name'), ('{#TYPE}', 'type'), ('{#NODE}', 'node'))],
              'host_prototypes': [{'uuid': uid(CLUSTER, 'hostproto', 'guest'), 'host': 'pve-guest-{#VMID}',
                                   'name': '{#NAME} ({#TYPE} {#VMID})',
                                   'group_links': [{'group': {'name': GUEST_GROUP}}],
                                   'templates': [{'name': GUEST}],
                                   'macros': [{'macro': '{$PVE.VMID}', 'value': '{#VMID}'}],
                                   'tags': [{'tag': 'pve-node', 'value': '{#NODE}'}, {'tag': 'pve-type', 'value': '{#TYPE}'}]}]},
             **lost),
    ]
    return template(CLUSTER, 'Discovers Proxmox VE nodes and running guests from Prometheus and creates a host for each.',
                    items, rules, {})


def template(name, description, items, rules, macros):
    return {'uuid': uid(name, 'template'), 'template': name, 'name': name, 'description': description,
            'groups': [{'name': GROUP}], 'items': items, 'discovery_rules': rules,
            'macros': [{'macro': m, 'value': v, 'description': d} for m, (v, d) in macros.items()]}


def build():
    return {'zabbix_export': {
        'version': '7.0',
        'template_groups': [{'uuid': uid('group', GROUP), 'name': GROUP}],
        'host_groups': [{'uuid': uid('hgroup', g), 'name': g} for g in (NODE_GROUP, GUEST_GROUP)],
        'templates': [node_template(), guest_template(), cluster_template()]}}


def api(url, token, method, params):
    body = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode()
    req = urllib.request.Request(url.rstrip('/') + '/api_jsonrpc.php', data=body, method='POST',
                                 headers={'Content-Type': 'application/json-rpc', 'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        reply = json.load(resp)
    if 'error' in reply:
        raise SystemExit(f"{method}: {reply['error'].get('message')} {reply['error'].get('data')}")
    return reply['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--import', dest='target', nargs=2, metavar=('URL', 'TOKENFILE'))
    parser.add_argument('--out', default=str(Path(__file__).with_name('pve-templates.json')))
    parser.add_argument('--run', action='store_true', help='write the file and import; without it nothing changes')
    args = parser.parse_args()
    export = build()
    text = json.dumps(export, indent=1, ensure_ascii=False) + '\n'
    templates = export['zabbix_export']['templates']
    summary = ', '.join(f"{t['name']} ({len(t['items'])} items, {len(t['discovery_rules'])} rules)" for t in templates)
    if not args.run:
        print('DRY RUN: nothing is written or imported. Add --run to apply.')
    print(f'templates: {summary}')
    print(f"{'wrote' if args.run else 'would write'} {args.out}")
    if args.target:
        print(f"{'importing' if args.run else 'would import'} into {args.target[0]}")
    if not args.run:
        print('DRY RUN finished: re-run with --run to apply.')
        return 0
    Path(args.out).write_text(text)
    if args.target:
        url, tokenfile = args.target
        token = Path(tokenfile).expanduser().read_text().strip()
        yes = {'createMissing': True, 'updateExisting': True}
        rules = {'template_groups': yes, 'host_groups': yes, 'templates': yes,
                 'items': dict(yes, deleteMissing=True), 'discoveryRules': dict(yes, deleteMissing=True),
                 'triggers': dict(yes, deleteMissing=True), 'templateLinkage': {'createMissing': True}}
        api(url, token, 'configuration.import', {'format': 'json', 'source': text, 'rules': rules})
        print(f'imported {NODE}, {GUEST}, {CLUSTER} into {url}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
