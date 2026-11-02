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


# Bucket items: the value of one completed UTC bucket (a day or 3 hours), computed from the snapshot's
# bucket points. A spec says what to compute:
#   {'agg': 'sum',   'parts': [[dataset, filter], ...]}                 sum of matching points
#   {'agg': 'ratio', 'parts': [...], 'den': [...], 'scale': 100}        sum(parts) / sum(den) * scale
#   {'agg': 'wavg',  'parts': [[dataset, {}]]}                          average weighted by observations
#                                                                       (details.totalTimeline / points)
# A filter maps a dimension to a value or a list of allowed values. BUCKET_JS and bucket_value() are
# twins: Zabbix runs the first live, the backfill runs the second, so both must agree.
BUCKET_JS = '''if (/^-?[0-9.]+(e[-+]?[0-9]+)?$/i.test(value)) { return value; }  // a pushed (backfilled) number
var d = JSON.parse(value).datasets, spec = SPEC, bucket = BUCKET;
var end = Math.floor(Date.now() / 1000 / bucket) * bucket, start = end - bucket;
function ds(id) {
  if (!d[id] || d[id].state !== 'available') { throw 'dataset ' + id + ' unavailable'; }
  return d[id];
}
function match(dims, filter) {
  for (var k in filter) {
    var want = filter[k], have = dims[k];
    if (Object.prototype.toString.call(want) === '[object Array]' ? want.indexOf(have) < 0 : have !== want) { return false; }
  }
  return true;
}
function total(parts) {
  var sum = 0;
  parts.forEach(function (part) {
    ds(part[0]).series.forEach(function (s) {
      if (!match(s.dimensions, part[1])) { return; }
      s.points.forEach(function (p) { if (p[0] >= start && p[0] < end && p[1] !== null) { sum += p[1]; } });
    });
  });
  return sum;
}
if (spec.agg === 'sum') { return total(spec.parts); }
if (spec.agg === 'ratio') {
  var den = total(spec.den);
  if (!den) { throw 'no data in bucket'; }
  return total(spec.parts) / den * spec.scale;
}
var seconds = 0, count = 0;
spec.parts.forEach(function (part) {
  var x = ds(part[0]), avg = {};
  x.series.forEach(function (s) { s.points.forEach(function (p) { avg[p[0]] = p[1]; }); });
  (x.details.totalTimeline || []).forEach(function (p) {
    if (p[0] >= start && p[0] < end && avg[p[0]]) { seconds += p[1]; count += p[1] / avg[p[0]]; }
  });
});
if (!count) { throw 'no data in bucket'; }
return seconds / count;'''
# key part: bucket seconds, snapshot range read live (its points must divide the bucket), poll schedule,
# snapshot range for the backfill, item name suffix. Live polls come shortly after a bucket closes.
PERIODS = {
    'daily': (86400, '7d', '0;h3m0', '30d', 'per day (UTC)'),
    '3h': (10800, '24h', '0;h/3m20', '7d', 'per 3 hours (UTC)'),
}
TOKENS_FOR_HIT = ['cached', 'input', 'written']  # as the dashboard: cache read / (cache read + input + cache write)


def agents_of(agent):
    return list(AGENTS) if agent == 'all' else [agent]


def bucket_specs():
    """(period, item, agent) -> (name, units, spec). Cost and tokens per day and per 3 hours; the rest per 3 hours."""
    out = {}
    for agent in ['all', *AGENTS]:
        for period in PERIODS:
            out[period, 'cost', agent] = ('cost', 'USD', {'agg': 'sum', 'parts': [[f'{a}.cost', {}] for a in agents_of(agent)]})
            out[period, 'tokens', agent] = ('tokens, total', 'tok', {'agg': 'sum', 'parts': [
                [f'{a}.tokens', {'category': 'total'}] for a in agents_of(agent)]})
    out['3h', 'sessions', 'all'] = ('sessions', '', {'agg': 'sum', 'parts': [[f'{a}.sessions', {}] for a in AGENTS]})
    out['3h', 'cache.hit', 'all'] = ('cache hit ratio', '%', {
        'agg': 'ratio', 'scale': 100, 'parts': [[f'{a}.tokens', {'category': 'cached'}] for a in AGENTS],
        'den': [[f'{a}.tokens', {'category': TOKENS_FOR_HIT}] for a in AGENTS]})
    out['3h', 'active', 'claude'] = ('active time', 's', {'agg': 'sum', 'parts': [['claude.active', {}]]})
    out['3h', 'commits', 'claude'] = ('commits', '', {'agg': 'sum', 'parts': [['claude.commits', {}]]})
    out['3h', 'lines.added', 'claude'] = ('lines added', '', {'agg': 'sum', 'parts': [['claude.lines', {'kind': 'added'}]]})
    out['3h', 'request.duration', 'claude'] = ('API request duration, avg', 's', {'agg': 'wavg', 'parts': [['claude.requestDuration', {}]]})
    out['3h', 'turns', 'codex'] = ('turns', '', {'agg': 'sum', 'parts': [['codex.turns', {}]]})
    out['3h', 'tools', 'codex'] = ('tool calls', '', {'agg': 'sum', 'parts': [['codex.tools', {}]]})
    out['3h', 'turn.duration', 'codex'] = ('turn duration, avg', 's', {'agg': 'wavg', 'parts': [['codex.turnDuration', {}]]})
    out['3h', 'turn.ttft', 'codex'] = ('turn time to first token, avg', 's', {'agg': 'wavg', 'parts': [['codex.firstToken', {}]]})
    return out


def lld_spec(key):
    """Spec of a discovered per-3-hour item from its resolved key, e.g. ai.model.cost.3h[claude,claude-opus-5-5]."""
    kind, args = key[:-1].split('[', 1)
    first, second = args.split(',', 1)
    if kind == 'ai.model.cost.3h':
        return {'agg': 'sum', 'parts': [[f'{first}.cost', {'model': second}]]}
    if kind == 'ai.scope.cost.3h':
        return {'agg': 'sum', 'parts': [['all.scopes', {'by': first, 'scope': second, 'metric': 'cost'}]]}
    return None


def bucket_value(datasets, spec, start, end):
    """Python twin of BUCKET_JS; None when the bucket has nothing to average."""
    def ok(dims, flt):
        return all(dims.get(k) in v if isinstance(v, list) else dims.get(k) == v for k, v in flt.items())

    def total(parts):
        return sum(p[1] for ds_id, flt in parts for s in datasets[ds_id]['series'] if ok(s['dimensions'], flt)
                   for p in s['points'] if start <= p[0] < end and p[1] is not None)

    if spec['agg'] == 'sum':
        return total(spec['parts'])
    if spec['agg'] == 'ratio':
        den = total(spec['den'])
        return total(spec['parts']) / den * spec['scale'] if den else None
    seconds = count = 0.0
    for ds_id, _ in spec['parts']:
        x = datasets[ds_id]
        avg = {p[0]: p[1] for s in x['series'] for p in s['points']}
        for t, sec in (x.get('details') or {}).get('totalTimeline', []):
            if start <= t < end and avg.get(t):
                seconds += sec
                count += sec / avg[t]
    return seconds / count if count else None


def bucket_js(spec, bucket):
    return BUCKET_JS.replace('SPEC', json.dumps(spec)).replace('BUCKET', str(bucket))


def bucket_item(key, name, units, js, period, live, delay, **tag):
    suffix = PERIODS[period][4]
    return {'uuid': uid(TEMPLATE, 'proto' if '{#' in key else 'item', key), 'name': f'{name} {suffix}',
            'type': 'HTTP_AGENT', 'key': key, 'delay': delay, 'history': '400d', 'value_type': 'FLOAT', 'units': units,
            'url': '{$AI.USAGE.URL}/api/dashboard/snapshot', 'timeout': '30s',
            'query_fields': [{'name': 'range', 'value': live}], 'allow_traps': 'YES',
            'allowed_hosts': '{$AI.PUSH.ALLOWED}',
            'preprocessing': [{'type': 'JAVASCRIPT', 'parameters': [js], 'error_handler': 'DISCARD_VALUE',
                               'error_handler_params': ''}],
            'description': f'Value of the last completed UTC bucket ({suffix[4:-6]}). '
                           'Accepts history.push, used to backfill past buckets.',
            'tags': tags(**tag)}


def period_items():
    out = []
    for (period, item, agent), (name, units, spec) in bucket_specs().items():
        bucket, live, delay, _, _ = PERIODS[period]
        label = 'All agents' if agent == 'all' else AGENTS[agent][0]
        out.append(bucket_item(f'ai.{period}.{item}[{agent}]', f'{label}: {name}', units, bucket_js(spec, bucket),
                               period, live, delay, agent=agent, window=period,
                               component='cost' if item == 'cost' else 'usage'))
    return out


def lld_bucket_protos(kind):
    bucket, live, delay, _, _ = PERIODS['3h']
    if kind == 'model':
        spec = {'agg': 'sum', 'parts': [['{#AGENT}.cost', {'model': '{#MODEL}'}]]}
        return [bucket_item('ai.model.cost.3h[{#AGENT},{#MODEL}]', '{#AGENTNAME} {#MODEL}: cost', 'USD',
                            bucket_js(spec, bucket), '3h', live, delay, agent='{#AGENT}', model='{#MODEL}', component='cost')]
    spec = {'agg': 'sum', 'parts': [['all.scopes', {'by': '{#BY}', 'scope': '{#SCOPE}', 'metric': 'cost'}]]}
    return [bucket_item('ai.scope.cost.3h[{#BY},{#SCOPE}]', '{#BY} {#SCOPE}: cost', 'USD', bucket_js(spec, bucket),
                        '3h', live, delay, scope='{#BY}:{#SCOPE}', component='cost')]


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
            *lld_bucket_protos('model'),
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
            *lld_bucket_protos('scope'),
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
    specs = {f'ai.{period}.{item}[{agent}]': spec for (period, item, agent), (_, _, spec) in bucket_specs().items()}
    found = api(url, token, 'item.get', {'hostids': hosts[0]['hostid'], 'output': ['itemid', 'key_'],
                                         'search': {'key_': ['ai.daily.', 'ai.3h.', '.cost.3h[']}, 'searchByAny': True})
    for period, (bucket, _, _, history, _) in PERIODS.items():
        items = [(i, specs.get(i['key_']) or lld_spec(i['key_'])) for i in found
                 if i['key_'].startswith(f'ai.{period}.') or (period == '3h' and '.cost.3h[' in i['key_'])]
        with urllib.request.urlopen(f"{source.rstrip('/')}/api/dashboard/snapshot?range={history}", timeout=120) as r:
            datasets = json.load(r)['datasets']
        now = int(time.time()) // bucket * bucket
        points = [p[0] for a in AGENTS for s in datasets[f'{a}.tokens']['series'] for p in s['points']]
        if not points:
            continue
        buckets = range(min(points) // bucket * bucket, now, bucket)
        for item, spec in items:
            if spec is None:
                continue
            stored = api(url, token, 'history.get', {'itemids': item['itemid'], 'history': 0, 'output': ['clock'],
                                                      'time_from': buckets[0] + bucket, 'time_till': now + bucket})
            have = {(int(h['clock']) - 1) // bucket * bucket - bucket for h in stored}
            for start in buckets:
                if start in have:
                    continue
                value = bucket_value(datasets, spec, start, start + bucket)
                if value is None:
                    continue
                pushes.append({'itemid': item['itemid'], 'clock': start + bucket + PUSH_OFFSETS[period], 'ns': 0,
                               'value': str(value)})
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


SUM, AVG = 5, 3  # widget aggregation functions


def value_widget(name, itemid, x, y, width=12, decimals=2, size=30, agg=SUM):
    """Sum or average of a per-3-hour item over the dashboard's time period.

    Header hidden: the description under the value already names it; no change arrow (red/green
    would read a shorter request time as bad)."""
    return {'type': 'item', 'name': name, 'x': x, 'y': y, 'width': width, 'height': 3, 'view_mode': '1',
            'fields': [f(ITEM, 'itemid.0', itemid), f(INT, 'show.0', 1), f(INT, 'show.1', 2),
                       f(STR, 'description', name), f(INT, 'decimal_places', decimals), f(INT, 'value_size', size),
                       f(INT, 'desc_size', 12), f(INT, 'adv_conf', 1), f(INT, 'aggregate_function', agg),
                       f(STR, 'time_period._reference', 'DASHBOARD._timeperiod')]}


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
    # one legend column: entries carry the host name and would be cut in several columns
    fields = [f(INT, 'legend', 1), f(INT, 'draw_type', 1), f(INT, 'legend_lines', 8), f(INT, 'legend_columns', 1)]
    for n, (pattern, color) in enumerate(patterns):
        fields += [f(STR, f'ds.{n}.hosts.0', host), f(STR, f'ds.{n}.items.0', pattern), f(STR, f'ds.{n}.color', color),
                   f(INT, f'ds.{n}.aggregate_function', SUM)]
    fields.append(f(STR, 'time_period._reference', 'DASHBOARD._timeperiod'))
    return {'type': 'piechart', 'name': name, 'x': x, 'y': y, 'width': width, 'height': height, 'view_mode': '0',
            'fields': fields}


def dashboard_widgets(host, ids):
    """Widgets of the global dashboard; ids maps item keys to item IDs on host."""
    w = [value_widget('Cost', ids['ai.3h.cost[all]'], 0, 0),
         value_widget('Claude Code cost', ids['ai.3h.cost[claude]'], 12, 0),
         value_widget('Codex cost', ids['ai.3h.cost[codex]'], 24, 0),
         value_widget('Tokens', ids['ai.3h.tokens[all]'], 36, 0, decimals=1),
         value_widget('Sessions', ids['ai.3h.sessions[all]'], 48, 0, decimals=0),
         value_widget('Cache hit, avg', ids['ai.3h.cache.hit[all]'], 60, 0, decimals=1, agg=AVG),
         graph_widget('Cost per 3 hours (UTC)', host,
                      [('Claude Code: cost per 3 hours (UTC)', CLAUDE_COLOR), ('Codex: cost per 3 hours (UTC)', CODEX_COLOR)],
                      0, 3, bars=True),
         graph_widget('Tokens per 3 hours (UTC)', host,
                      [('Claude Code: tokens, total per 3 hours (UTC)', CLAUDE_COLOR),
                       ('Codex: tokens, total per 3 hours (UTC)', CODEX_COLOR)], 36, 3, bars=True),
         graph_widget('Cost per day (UTC)', host,
                      [('Claude Code: cost per day (UTC)', CLAUDE_COLOR), ('Codex: cost per day (UTC)', CODEX_COLOR)],
                      0, 8, bars=True),
         graph_widget('Tokens per day (UTC)', host,
                      [('Claude Code: tokens, total per day (UTC)', CLAUDE_COLOR),
                       ('Codex: tokens, total per day (UTC)', CODEX_COLOR)], 36, 8, bars=True),
         pie_widget('Cost by model', host, [('Claude Code *: cost per 3 hours (UTC)', CLAUDE_COLOR),
                                            ('Codex *: cost per 3 hours (UTC)', CODEX_COLOR)], 0, 13),
         pie_widget('Cost by project', host, [('project *: cost per 3 hours (UTC)', ALL_COLOR)], 24, 13),
         pie_widget('Cost by machine', host, [('host *: cost per 3 hours (UTC)', ALL_COLOR)], 48, 13)]
    details = [('Claude Code active time', 'ai.3h.active[claude]', 0, SUM),
               ('Claude Code commits', 'ai.3h.commits[claude]', 0, SUM),
               ('Claude Code lines added', 'ai.3h.lines.added[claude]', 0, SUM),
               ('Claude Code API request, avg', 'ai.3h.request.duration[claude]', 1, AVG),
               ('Codex turns', 'ai.3h.turns[codex]', 0, SUM), ('Codex tool calls', 'ai.3h.tools[codex]', 0, SUM),
               ('Codex turn duration, avg', 'ai.3h.turn.duration[codex]', 1, AVG),
               ('Codex time to first token, avg', 'ai.3h.turn.ttft[codex]', 1, AVG)]
    # two rows of four (Claude Code, Codex): eight tiles in one row are too narrow for their descriptions
    w += [value_widget(name, ids[key], 18 * (n % 4), 19 + 3 * (n // 4), width=18, decimals=d, agg=agg)
          for n, (name, key, d, agg) in enumerate(details)]
    return w


def dashboard(url, token, host, run):
    hosts = api(url, token, 'host.get', {'filter': {'host': [host]}, 'output': ['hostid', 'name']})
    if not hosts:
        raise SystemExit(f'host {host} not found')
    items = api(url, token, 'item.get', {'hostids': hosts[0]['hostid'], 'output': ['itemid', 'key_']})
    ids = {i['key_']: i['itemid'] for i in items}
    # graph and pie data sets match hosts by visible name
    page = {'name': 'Overview', 'widgets': dashboard_widgets(hosts[0]['name'], ids)}
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
