#!/usr/bin/env python3
"""Build (and optionally import) a Zabbix template for AI coding agent usage (Claude Code, Codex).

Data: the homestack AI Usage service (hs-usage), `GET {$AI.USAGE.URL}/api/dashboard/snapshot?range=1h|24h`.
It already turns the agents' OpenTelemetry metrics in Prometheus into usage: counter resets and
per-session series, delta gauges from three collectors, estimated Codex cost. Zabbix reads that
JSON, so its numbers match the dashboard.

  AI coding agents by HTTP   totals and per agent for the last hour and day; LLD per model,
                             per machine and per project (last day)

Agent metrics are listed in AGENTS; a new agent in hs-usage needs one entry there.

  build_ai_usage_template.py                                   dry run: show what would be written/imported
  build_ai_usage_template.py --run                             write ai-usage-template.json
  build_ai_usage_template.py --import URL TOKENFILE --run      write and import (create/update)
  build_ai_usage_template.py --dashboard URL TOKENFILE --run   create/update the global dashboard "AI agents"
  build_ai_usage_template.py --backfill URL TOKENFILE --run    push past per-day (30 days) and per-3-hour (7 days)
                                                               totals into host --host (default ai-usage)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

NS = uuid.UUID('3c1f9a8e-2b7d-4e6a-9f05-7d8e1c2b3a40')
TEMPLATE = 'AI coding agents by HTTP'
GROUP = 'Templates/Applications'
WINDOWS = ('1h', '24h')
LLD_WINDOW = '24h'


def uid(*parts):
    return uuid.UUID(bytes=uuid.uuid5(NS, '|'.join(parts)).bytes, version=4).hex


def master_key(window):
    return f'ai.snapshot[{window}]'


# (summary field, item suffix, label, units, multiplier)
COMMON = [
    ('cost', 'cost', 'cost', 'USD', None),
    ('total', 'tokens', 'tokens, total', 'tok', None),
    ('input', 'tokens.input', 'tokens, input', 'tok', None),
    ('output', 'tokens.output', 'tokens, output', 'tok', None),
    ('cached', 'tokens.cached', 'tokens, cache read', 'tok', None),
    ('written', 'tokens.written', 'tokens, cache write', 'tok', None),
    ('cacheHit', 'cache.hit', 'cache hit ratio', '%', '100'),
    ('sessions', 'sessions', 'sessions', '', None),
]
AGENTS = {
    'claude': ('Claude Code', COMMON + [
        ('active', 'active', 'active time', 's', None),
        ('commits', 'commits', 'commits', '', None),
        ('added', 'lines.added', 'lines added', '', None),
        ('removed', 'lines.removed', 'lines removed', '', None),
        ('requestDuration', 'request.duration', 'API request duration, avg', 's', None),
        ('requestFirstToken', 'request.ttft', 'API request time to first token, avg', 's', None),
    ]),
    'codex': ('Codex', COMMON + [
        ('reasoning', 'tokens.reasoning', 'tokens, reasoning', 'tok', None),
        ('turns', 'turns', 'turns', '', None),
        ('tools', 'tools', 'tool calls', '', None),
        ('turnDuration', 'turn.duration', 'turn duration, avg', 's', None),
        ('firstToken', 'turn.ttft', 'turn time to first token, avg', 's', None),
        ('firstOutput', 'turn.ttfo', 'turn time to first output, avg', 's', None),
        ('toolDuration', 'tool.duration', 'tool call duration, avg', 's', None),
    ]),
}
TOTALS = [m for m in COMMON] + [('reasoning', 'tokens.reasoning', 'tokens, reasoning', 'tok', None)]

# A metric an agent does not report has value null: such samples are discarded, not errors.
NUMBER = {'type': 'MATCHES_REGEX', 'parameters': [r'^-?[0-9]'], 'error_handler': 'DISCARD_VALUE', 'error_handler_params': ''}

# Sum of the bucket points of the matching series in one dataset (equals the dashboard total).
SUM_JS = '''var d = JSON.parse(value).datasets[DATASET];
if (!d || d.state !== 'available') { throw 'dataset ' + DATASET + ' unavailable'; }
var want = FILTER, sum = 0;
d.series.forEach(function (s) {
  for (var k in want) { if (s.dimensions[k] !== want[k]) { return; } }
  s.points.forEach(function (p) { sum += p[1]; });
});
return sum;'''

MODELS_JS = '''var d = JSON.parse(value).datasets, out = [], seen = {};
AGENTS.forEach(function (a) {
  var ds = d[a[0] + '.tokens'];
  if (!ds) { return; }
  ds.series.forEach(function (s) {
    var m = s.dimensions.model;
    if (m && !seen[a[0] + '|' + m]) { seen[a[0] + '|' + m] = 1; out.push({'{#AGENT}': a[0], '{#AGENTNAME}': a[1], '{#MODEL}': m}); }
  });
});
return JSON.stringify(out);'''

SCOPES_JS = '''var d = JSON.parse(value).datasets['all.scopes'], out = [], seen = {};
if (!d || d.state !== 'available') { throw 'dataset all.scopes unavailable'; }
d.series.forEach(function (s) {
  var k = s.dimensions.by + '|' + s.dimensions.scope;
  if (!seen[k]) { seen[k] = 1; out.push({'{#BY}': s.dimensions.by, '{#SCOPE}': s.dimensions.scope}); }
});
return JSON.stringify(out);'''


# Total of the last completed UTC bucket (day or 3 hours) from the snapshot's bucket points.
BUCKET_JS = '''if (/^-?[0-9.]+(e[-+]?[0-9]+)?$/i.test(value)) { return value; }  // a pushed (backfilled) number
var d = JSON.parse(value).datasets, agents = AGENTS, measure = MEASURE, bucket = BUCKET;
var end = Math.floor(Date.now() / 1000 / bucket) * bucket, start = end - bucket, sum = 0;
agents.forEach(function (a) {
  var ds = d[a + '.' + measure];
  if (!ds || ds.state !== 'available') { throw 'dataset ' + a + '.' + measure + ' unavailable'; }
  ds.series.forEach(function (s) {
    if (measure === 'tokens' && s.dimensions.category !== 'total') { return; }
    s.points.forEach(function (p) { if (p[0] >= start && p[0] < end) { sum += p[1]; } });
  });
});
return sum;'''
MEASURES = {'cost': ('cost', 'USD'), 'tokens': ('tokens, total', 'tok')}
# key part: bucket seconds, snapshot range read live (its points must divide the bucket), poll schedule,
# snapshot range for the backfill, item name suffix. Live polls come shortly after a bucket closes.
PERIODS = {
    'daily': (86400, '7d', '0;h3m0', '30d', 'per day (UTC)'),
    '3h': (10800, '24h', '0;h/3m20', '7d', 'per 3 hours (UTC)'),
}


def period_agents(agent):
    return list(AGENTS) if agent == 'all' else [agent]


def bucket_total(datasets, agent, measure, start, end):
    """Python twin of BUCKET_JS for the backfill: sum of bucket points in [start, end)."""
    total = 0.0
    for a in period_agents(agent):
        for s in datasets[f'{a}.{measure}']['series']:
            if measure == 'tokens' and s['dimensions'].get('category') != 'total':
                continue
            total += sum(p[1] for p in s['points'] if start <= p[0] < end)
    return total


def period_items():
    out = []
    for period, (bucket, live, delay, _, suffix) in PERIODS.items():
        for agent in ['all', *AGENTS]:
            label = 'All agents' if agent == 'all' else AGENTS[agent][0]
            for measure, (name, units) in MEASURES.items():
                key = f'ai.{period}.{measure}[{agent}]'
                js = (BUCKET_JS.replace('AGENTS', json.dumps(period_agents(agent)))
                      .replace('MEASURE', json.dumps(measure)).replace('BUCKET', str(bucket)))
                out.append({'uuid': uid(TEMPLATE, 'item', key), 'name': f'{label}: {name} {suffix}', 'type': 'HTTP_AGENT',
                            'key': key, 'delay': delay, 'history': '400d', 'value_type': 'FLOAT', 'units': units,
                            'url': '{$AI.USAGE.URL}/api/dashboard/snapshot', 'timeout': '30s',
                            'query_fields': [{'name': 'range', 'value': live}], 'allow_traps': 'YES',
                            'allowed_hosts': '{$AI.PUSH.ALLOWED}',
                            'preprocessing': [{'type': 'JAVASCRIPT', 'parameters': [js]}],
                            'description': f'Total of the last completed UTC bucket ({suffix[4:-6]}). '
                                           'Accepts history.push, used to backfill past buckets.',
                            'tags': tags(agent=agent, window=period, component='cost' if measure == 'cost' else 'usage')})
    return out


def sum_js(dataset, **match):
    return SUM_JS.replace('DATASET', json.dumps(dataset)).replace('FILTER', json.dumps(match))


def tags(**pairs):
    return [{'tag': k, 'value': v} for k, v in pairs.items()]


def trigger(key, expression, name, priority, description='', proto=False):
    return {'uuid': uid(TEMPLATE, 'tproto' if proto else 'trigger', key, name), 'expression': expression,
            'name': name, 'priority': priority, 'description': description}


def master(window):
    key = master_key(window)
    return {'uuid': uid(TEMPLATE, 'item', key), 'name': f'AI Usage snapshot ({window})', 'type': 'HTTP_AGENT',
            'key': key, 'delay': '{$AI.USAGE.INTERVAL}', 'history': '0', 'value_type': 'TEXT', 'trends': '0',
            'url': '{$AI.USAGE.URL}/api/dashboard/snapshot', 'timeout': '30s',
            'query_fields': [{'name': 'range', 'value': window}],
            'description': f'Dashboard data of the last {window}; every other item depends on it.',
            'tags': tags(component='raw'),
            'triggers': [trigger(key, f'nodata(/{TEMPLATE}/{key},30m)=1',
                                 f'AI Usage API: no data for 30 minutes ({window})', 'AVERAGE')]}


def summary_item(agent, label, field, suffix, name, units, multiplier, window):
    key = f'ai.{agent}.{suffix}[{window}]'
    pre = [{'type': 'JSONPATH', 'parameters': [f"$.datasets['all.summary'].details.{'totals' if agent == 'all' else agent}.{field}.value"],
            'error_handler': 'DISCARD_VALUE', 'error_handler_params': ''}, dict(NUMBER)]
    if multiplier:
        pre.append({'type': 'MULTIPLIER', 'parameters': [multiplier]})
    return {'uuid': uid(TEMPLATE, 'item', key), 'name': f'{label}: {name} ({window})', 'type': 'DEPENDENT', 'key': key,
            'delay': '0', 'value_type': 'FLOAT', 'units': units, 'preprocessing': pre,
            'master_item': {'key': master_key(window)},
            'tags': tags(agent=agent, window=window, component='cost' if field == 'cost' else 'usage')}


def items():
    out = []
    for window in WINDOWS:
        out.append(master(window))
        for field, suffix, name, units, mult in TOTALS:
            out.append(summary_item('all', 'All agents', field, suffix, name, units, mult, window))
        for agent, (label, metrics) in AGENTS.items():
            for field, suffix, name, units, mult in metrics:
                out.append(summary_item(agent, label, field, suffix, name, units, mult, window))
    cost = next(i for i in out if i['key'] == 'ai.all.cost[24h]')
    cost['description'] = 'Claude Code cost as it reports it; Codex cost estimated by hs-usage from list prices.'
    cost['triggers'] = [trigger(cost['key'], f'last(/{TEMPLATE}/ai.all.cost[24h])>{{$AI.COST.24H.WARN}}',
                                'AI agents cost over {$AI.COST.24H.WARN} USD in the last 24h', 'WARNING')]
    return out + period_items()


def proto(key, name, units, js, **tag):
    return {'uuid': uid(TEMPLATE, 'proto', key), 'name': name, 'type': 'DEPENDENT', 'key': key, 'delay': '0',
            'value_type': 'FLOAT', 'units': units, 'master_item': {'key': master_key(LLD_WINDOW)},
            'preprocessing': [{'type': 'JAVASCRIPT', 'parameters': [js], 'error_handler': 'DISCARD_VALUE',
                               'error_handler_params': ''}],
            'tags': tags(**tag)}


def rules():
    w = LLD_WINDOW
    lost = {'lifetime_type': 'DELETE_AFTER', 'lifetime': '30d', 'enabled_lifetime_type': 'DISABLE_NEVER'}
    models = dict({
        'uuid': uid(TEMPLATE, 'rule', 'models'), 'name': 'Models', 'type': 'DEPENDENT', 'key': 'ai.model.discovery',
        'delay': '0', 'master_item': {'key': master_key(w)},
        'description': 'Models used by each agent in the last day.',
        'preprocessing': [{'type': 'JAVASCRIPT', 'parameters': [MODELS_JS.replace(
            'AGENTS', json.dumps([[a, label] for a, (label, _) in AGENTS.items()]))]}],
        'item_prototypes': [
            proto(f'ai.model.cost[{{#AGENT}},{{#MODEL}},{w}]', f'{{#AGENTNAME}} {{#MODEL}}: cost ({w})', 'USD',
                  sum_js('{#AGENT}.cost', model='{#MODEL}'), agent='{#AGENT}', model='{#MODEL}', component='cost'),
            proto(f'ai.model.tokens[{{#AGENT}},{{#MODEL}},{w}]', f'{{#AGENTNAME}} {{#MODEL}}: tokens, total ({w})', 'tok',
                  sum_js('{#AGENT}.tokens', model='{#MODEL}', category='total'), agent='{#AGENT}', model='{#MODEL}',
                  component='usage'),
            proto(f'ai.model.output[{{#AGENT}},{{#MODEL}},{w}]', f'{{#AGENTNAME}} {{#MODEL}}: tokens, output ({w})', 'tok',
                  sum_js('{#AGENT}.tokens', model='{#MODEL}', category='output'), agent='{#AGENT}', model='{#MODEL}',
                  component='usage'),
        ]}, **lost)
    scopes = dict({
        'uuid': uid(TEMPLATE, 'rule', 'scopes'), 'name': 'Machines and projects', 'type': 'DEPENDENT',
        'key': 'ai.scope.discovery', 'delay': '0', 'master_item': {'key': master_key(w)},
        'description': 'Machines (host) and projects (repository) with usage in the last day, all agents together.',
        'preprocessing': [{'type': 'JAVASCRIPT', 'parameters': [SCOPES_JS]}],
        'item_prototypes': [
            proto(f'ai.scope.cost[{{#BY}},{{#SCOPE}},{w}]', f'{{#BY}} {{#SCOPE}}: cost ({w})', 'USD',
                  sum_js('all.scopes', by='{#BY}', scope='{#SCOPE}', metric='cost'), scope='{#BY}:{#SCOPE}', component='cost'),
            proto(f'ai.scope.tokens[{{#BY}},{{#SCOPE}},{w}]', f'{{#BY}} {{#SCOPE}}: tokens, total ({w})', 'tok',
                  sum_js('all.scopes', by='{#BY}', scope='{#SCOPE}', metric='tokens'), scope='{#BY}:{#SCOPE}',
                  component='usage'),
        ]}, **lost)
    return [models, scopes]


def build():
    macros = {
        '{$AI.USAGE.URL}': ('http://AI-USAGE', 'Base URL of the AI Usage (hs-usage) service, set it on the host.'),
        '{$AI.USAGE.INTERVAL}': ('5m', 'Poll interval; the service caches its Prometheus reads.'),
        '{$AI.PUSH.ALLOWED}': ('127.0.0.1', 'Addresses allowed to push history into the per-day items (backfill).'),
        '{$AI.COST.24H.WARN}': ('150', 'Warn when all agents together cost more (USD) in the last 24h.'),
    }
    template = {'uuid': uid(TEMPLATE, 'template'), 'template': TEMPLATE, 'name': TEMPLATE,
                'description': 'Claude Code and Codex usage (tokens, cost, sessions, timings) from the homestack '
                               'AI Usage service, which reads the agents\' OpenTelemetry metrics from Prometheus.',
                'groups': [{'name': GROUP}], 'items': items(), 'discovery_rules': rules(),
                'macros': [{'macro': m, 'value': v, 'description': d} for m, (v, d) in macros.items()]}
    return {'zabbix_export': {'version': '7.0',
                              'template_groups': [{'uuid': uid('group', GROUP), 'name': GROUP}],
                              'templates': [template]}}


def api(url, token, method, params):
    body = json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode()
    req = urllib.request.Request(url.rstrip('/') + '/api_jsonrpc.php', data=body, method='POST',
                                 headers={'Content-Type': 'application/json-rpc', 'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        reply = json.load(resp)
    if 'error' in reply:
        raise SystemExit(f"{method}: {reply['error'].get('message')} {reply['error'].get('data')}")
    return reply['result']


PUSH_OFFSETS = {'daily': 3 * 3600, '3h': 20 * 60}  # stored this long after the bucket closes, near the live poll


def backfill(url, token, host, run):
    hosts = api(url, token, 'host.get', {'filter': {'host': [host]}, 'output': ['hostid'],
                                          'selectMacros': ['macro', 'value']})
    if not hosts:
        raise SystemExit(f'host {host} not found')
    macros = {m['macro']: m['value'] for m in hosts[0]['macros']}
    source = macros.get('{$AI.USAGE.URL}')
    if not source:
        raise SystemExit(f'{{$AI.USAGE.URL}} is not set on host {host}')
    pushes = []
    for period, (bucket, _, _, history, _) in PERIODS.items():
        items = api(url, token, 'item.get', {'hostids': hosts[0]['hostid'], 'search': {'key_': f'ai.{period}.'},
                                             'output': ['itemid', 'key_']})
        with urllib.request.urlopen(f"{source.rstrip('/')}/api/dashboard/snapshot?range={history}", timeout=120) as r:
            datasets = json.load(r)['datasets']
        now = int(time.time()) // bucket * bucket
        points = [p[0] for a in AGENTS for m in MEASURES for s in datasets[f'{a}.{m}']['series'] for p in s['points']]
        if not points:
            continue
        buckets = range(min(points) // bucket * bucket, now, bucket)
        for item in items:
            measure, agent = item['key_'][len(f'ai.{period}.'):-1].split('[')
            stored = api(url, token, 'history.get', {'itemids': item['itemid'], 'history': 0, 'output': ['clock'],
                                                      'time_from': buckets[0] + bucket, 'time_till': now + bucket})
            have = {(int(h['clock']) - 1) // bucket * bucket - bucket for h in stored}
            for start in buckets:
                if start in have:
                    continue
                value = bucket_total(datasets, agent, measure, start, start + bucket)
                pushes.append({'itemid': item['itemid'], 'clock': start + bucket + PUSH_OFFSETS[period], 'ns': 0,
                               'value': str(value)})
                print(f"  {time.strftime('%Y-%m-%d %H:%M', time.gmtime(start))} {item['key_']:28} {value:,.4f}")
    print(f"{'pushing' if run else 'would push'} {len(pushes)} values into {host}")
    if run and pushes:
        result = api(url, token, 'history.push', pushes)
        errors = [d for d in result.get('data', []) if 'error' in d]
        print(f"{result.get('response')}: {len(pushes) - len(errors)} accepted, {len(errors)} rejected")
        for e in errors[:5]:
            print('  ', e['error'])
        time.sleep(10)  # values pass preprocessing and the history cache before they are readable
        ids = sorted({p['itemid'] for p in pushes})
        stored = api(url, token, 'history.get', {'itemids': ids, 'history': 0, 'countOutput': True,
                                                  'time_from': min(p['clock'] for p in pushes)})
        print(f'verified in history: {stored} of {len(pushes)}')
        failing = api(url, token, 'item.get', {'itemids': ids, 'filter': {'state': 1}, 'output': ['key_', 'error']})
        for item in failing:
            print(f"  {item['key_']} not supported: {item['error'].splitlines()[0]}")


DASHBOARD = 'AI agents'
CLAUDE_COLOR, CODEX_COLOR, ALL_COLOR = 'D97757', '10A37F', '4A90D9'
INT, STR, ITEM = '0', '1', '4'


def f(kind, name, value):
    return {'type': kind, 'name': name, 'value': str(value)}


def value_widget(name, itemid, x, y, width=12, decimals=2):
    return {'type': 'item', 'name': name, 'x': x, 'y': y, 'width': width, 'height': 3, 'view_mode': '0',
            'fields': [f(ITEM, 'itemid.0', itemid), f(INT, 'show.0', 1), f(INT, 'show.1', 2), f(INT, 'show.2', 4),
                       f(STR, 'description', name), f(INT, 'decimal_places', decimals), f(INT, 'value_size', 40),
                       f(INT, 'desc_size', 12), f(INT, 'adv_conf', 1)]}


def graph_widget(name, host, series, x, y, width=36, height=5, bars=False, period=None):
    fields = [f(INT, 'legend', 1), f(INT, 'righty', 0), f(STR, 'lefty_min', 0)]
    for n, (pattern, color) in enumerate(series):
        fields += [f(STR, f'ds.{n}.hosts.0', host), f(STR, f'ds.{n}.items.0', pattern), f(STR, f'ds.{n}.color', color),
                   f(INT, f'ds.{n}.type', 3 if bars else 0), f(INT, f'ds.{n}.width', 2),
                   f(INT, f'ds.{n}.transparency', 2 if bars else 5), f(INT, f'ds.{n}.fill', 3)]
        if bars:
            fields.append(f(INT, f'ds.{n}.stacked', 1))
    if period:
        fields += [f(STR, 'time_period.from', period), f(STR, 'time_period.to', 'now')]
    return {'type': 'svggraph', 'name': name, 'x': x, 'y': y, 'width': width, 'height': height, 'view_mode': '0',
            'fields': fields}


def pie_widget(name, host, patterns, x, y, width=24, height=6):
    fields = [f(INT, 'legend', 1), f(INT, 'draw_type', 1), f(INT, 'legend_lines', 6)]
    for n, (pattern, color) in enumerate(patterns):
        fields += [f(STR, f'ds.{n}.hosts.0', host), f(STR, f'ds.{n}.items.0', pattern), f(STR, f'ds.{n}.color', color)]
    return {'type': 'piechart', 'name': name, 'x': x, 'y': y, 'width': width, 'height': height, 'view_mode': '0',
            'fields': fields}


def dashboard_widgets(host, ids):
    """Widgets of the global dashboard; ids maps item keys to item IDs on host."""
    w = [value_widget('Cost, 24h', ids['ai.all.cost[24h]'], 0, 0),
         value_widget('Claude Code cost, 24h', ids['ai.claude.cost[24h]'], 12, 0),
         value_widget('Codex cost, 24h', ids['ai.codex.cost[24h]'], 24, 0),
         value_widget('Tokens, 24h', ids['ai.all.tokens[24h]'], 36, 0, decimals=1),
         value_widget('Sessions, 24h', ids['ai.all.sessions[24h]'], 48, 0, decimals=0),
         value_widget('Cache hit, 24h', ids['ai.all.cache.hit[24h]'], 60, 0, decimals=1),
         graph_widget('Cost per 3 hours (UTC)', host,
                      [('Claude Code: cost per 3 hours (UTC)', CLAUDE_COLOR), ('Codex: cost per 3 hours (UTC)', CODEX_COLOR)],
                      0, 3, bars=True),
         graph_widget('Tokens per 3 hours (UTC)', host,
                      [('Claude Code: tokens, total per 3 hours (UTC)', CLAUDE_COLOR),
                       ('Codex: tokens, total per 3 hours (UTC)', CODEX_COLOR)], 36, 3, bars=True),
         graph_widget('Cost per day (UTC)', host,
                      [('Claude Code: cost per day (UTC)', CLAUDE_COLOR), ('Codex: cost per day (UTC)', CODEX_COLOR)],
                      0, 8, bars=True, period='now-30d'),
         graph_widget('Tokens per day (UTC)', host,
                      [('Claude Code: tokens, total per day (UTC)', CLAUDE_COLOR),
                       ('Codex: tokens, total per day (UTC)', CODEX_COLOR)], 36, 8, bars=True, period='now-30d'),
         pie_widget('Cost by model, 24h', host, [('Claude Code *: cost (24h)', CLAUDE_COLOR), ('Codex *: cost (24h)', CODEX_COLOR)], 0, 13),
         pie_widget('Cost by project, 24h', host, [('project *: cost (24h)', ALL_COLOR)], 24, 13),
         pie_widget('Cost by machine, 24h', host, [('host *: cost (24h)', ALL_COLOR)], 48, 13)]
    details = [('Claude Code active time, 24h', 'ai.claude.active[24h]', 0), ('Claude Code commits, 24h', 'ai.claude.commits[24h]', 0),
               ('Claude Code lines added, 24h', 'ai.claude.lines.added[24h]', 0),
               ('Claude Code API request, avg', 'ai.claude.request.duration[24h]', 1),
               ('Codex turns, 24h', 'ai.codex.turns[24h]', 0), ('Codex tool calls, 24h', 'ai.codex.tools[24h]', 0),
               ('Codex turn duration, avg', 'ai.codex.turn.duration[24h]', 1),
               ('Codex time to first token, avg', 'ai.codex.turn.ttft[24h]', 1)]
    w += [value_widget(name, ids[key], 9 * n, 19, width=9, decimals=d) for n, (name, key, d) in enumerate(details)]
    return w


def dashboard(url, token, host, run):
    hosts = api(url, token, 'host.get', {'filter': {'host': [host]}, 'output': ['hostid']})
    if not hosts:
        raise SystemExit(f'host {host} not found')
    items = api(url, token, 'item.get', {'hostids': hosts[0]['hostid'], 'output': ['itemid', 'key_']})
    ids = {i['key_']: i['itemid'] for i in items}
    page = {'name': 'Overview', 'widgets': dashboard_widgets(host, ids)}
    existing = api(url, token, 'dashboard.get', {'filter': {'name': [DASHBOARD]}, 'output': ['dashboardid']})
    action = 'update' if existing else 'create'
    print(f"{'would ' if not run else ''}{action} dashboard {DASHBOARD!r} ({len(page['widgets'])} widgets) for host {host}")
    if not run:
        return
    params = {'pages': [page], 'auto_start': '0'}
    if existing:
        api(url, token, 'dashboard.update', dict(params, dashboardid=existing[0]['dashboardid']))
    else:
        api(url, token, 'dashboard.create', dict(params, name=DASHBOARD, display_period=60))
    print('done')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--import', dest='target', nargs=2, metavar=('URL', 'TOKENFILE'))
    parser.add_argument('--backfill', nargs=2, metavar=('URL', 'TOKENFILE'))
    parser.add_argument('--dashboard', nargs=2, metavar=('URL', 'TOKENFILE'),
                        help='create/update the global dashboard "AI agents" for --host')
    parser.add_argument('--host', default='ai-usage', help='host for --backfill and --dashboard')
    parser.add_argument('--out', default=str(Path(__file__).with_name('ai-usage-template.json')))
    parser.add_argument('--run', action='store_true', help='write the file and import; without it nothing changes')
    args = parser.parse_args()
    if args.dashboard:
        url, tokenfile = args.dashboard
        if not args.run:
            print('DRY RUN: nothing is changed. Add --run to apply.')
        dashboard(url, Path(tokenfile).expanduser().read_text().strip(), args.host, args.run)
        return 0
    if args.backfill:
        url, tokenfile = args.backfill
        if not args.run:
            print('DRY RUN: nothing is pushed. Add --run to apply.')
        backfill(url, Path(tokenfile).expanduser().read_text().strip(), args.host, args.run)
        if not args.run:
            print('DRY RUN finished: re-run with --run to apply.')
        return 0
    export = build()
    text = json.dumps(export, indent=1, ensure_ascii=False) + '\n'
    t = export['zabbix_export']['templates'][0]
    if not args.run:
        print('DRY RUN: nothing is written or imported. Add --run to apply.')
    print(f"template: {t['name']} ({len(t['items'])} items, {len(t['discovery_rules'])} rules)")
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
        rules_ = {'template_groups': yes, 'templates': yes,
                  'items': dict(yes, deleteMissing=True), 'discoveryRules': dict(yes, deleteMissing=True),
                  'triggers': dict(yes, deleteMissing=True)}
        api(url, token, 'configuration.import', {'format': 'json', 'source': text, 'rules': rules_})
        print(f'imported {TEMPLATE} into {url}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
