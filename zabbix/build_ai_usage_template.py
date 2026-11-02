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
"""
from __future__ import annotations

import argparse
import json
import sys
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
    ('total', 'tokens', 'tokens, total', '', None),
    ('input', 'tokens.input', 'tokens, input', '', None),
    ('output', 'tokens.output', 'tokens, output', '', None),
    ('cached', 'tokens.cached', 'tokens, cache read', '', None),
    ('written', 'tokens.written', 'tokens, cache write', '', None),
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
        ('reasoning', 'tokens.reasoning', 'tokens, reasoning', '', None),
        ('turns', 'turns', 'turns', '', None),
        ('tools', 'tools', 'tool calls', '', None),
        ('turnDuration', 'turn.duration', 'turn duration, avg', 's', None),
        ('firstToken', 'turn.ttft', 'turn time to first token, avg', 's', None),
        ('firstOutput', 'turn.ttfo', 'turn time to first output, avg', 's', None),
        ('toolDuration', 'tool.duration', 'tool call duration, avg', 's', None),
    ]),
}
TOTALS = [m for m in COMMON] + [('reasoning', 'tokens.reasoning', 'tokens, reasoning', '', None)]

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
    return out


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
            proto(f'ai.model.tokens[{{#AGENT}},{{#MODEL}},{w}]', f'{{#AGENTNAME}} {{#MODEL}}: tokens, total ({w})', '',
                  sum_js('{#AGENT}.tokens', model='{#MODEL}', category='total'), agent='{#AGENT}', model='{#MODEL}',
                  component='usage'),
            proto(f'ai.model.output[{{#AGENT}},{{#MODEL}},{w}]', f'{{#AGENTNAME}} {{#MODEL}}: tokens, output ({w})', '',
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
            proto(f'ai.scope.tokens[{{#BY}},{{#SCOPE}},{w}]', f'{{#BY}} {{#SCOPE}}: tokens, total ({w})', '',
                  sum_js('all.scopes', by='{#BY}', scope='{#SCOPE}', metric='tokens'), scope='{#BY}:{#SCOPE}',
                  component='usage'),
        ]}, **lost)
    return [models, scopes]


def build():
    macros = {
        '{$AI.USAGE.URL}': ('http://AI-USAGE', 'Base URL of the AI Usage (hs-usage) service, set it on the host.'),
        '{$AI.USAGE.INTERVAL}': ('5m', 'Poll interval; the service caches its Prometheus reads.'),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--import', dest='target', nargs=2, metavar=('URL', 'TOKENFILE'))
    parser.add_argument('--out', default=str(Path(__file__).with_name('ai-usage-template.json')))
    parser.add_argument('--run', action='store_true', help='write the file and import; without it nothing changes')
    args = parser.parse_args()
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
