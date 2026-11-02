import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'zabbix' / 'build_ai_usage_template.py'
spec = importlib.util.spec_from_file_location('build_ai_usage_template', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AiUsageTemplateTests(unittest.TestCase):
    def setUp(self):
        self.export = module.build()['zabbix_export']
        self.template = self.export['templates'][0]
        self.items = {i['key']: i for i in self.template['items']}

    def test_uuids_are_unique_v4(self):
        found = []

        def walk(value):
            if isinstance(value, dict):
                if 'uuid' in value:
                    found.append(value['uuid'])
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(self.export)
        self.assertEqual(len(found), len(set(found)))
        self.assertTrue(all(len(u) == 32 and u[12] == '4' for u in found))

    def test_build_is_deterministic(self):
        self.assertEqual(json.dumps(module.build()), json.dumps(module.build()))

    def test_one_master_per_window(self):
        for window in module.WINDOWS:
            master = self.items[module.master_key(window)]
            self.assertEqual(master['type'], 'HTTP_AGENT')
            self.assertEqual(master['query_fields'], [{'name': 'range', 'value': window}])
        for item in self.items.values():
            if item['type'] == 'DEPENDENT':
                self.assertIn(item['master_item']['key'], {module.master_key(w) for w in module.WINDOWS})
                self.assertTrue(item['key'].endswith(item['master_item']['key'][len('ai.snapshot'):]))

    def test_every_agent_and_window_has_cost_and_tokens(self):
        for window in module.WINDOWS:
            for agent in ['all', *module.AGENTS]:
                self.assertIn(f'ai.{agent}.cost[{window}]', self.items)
                self.assertIn(f'ai.{agent}.tokens[{window}]', self.items)

    def test_missing_metric_is_discarded(self):
        item = self.items['ai.claude.request.duration[1h]']
        self.assertEqual([p['error_handler'] for p in item['preprocessing'][:2]], ['DISCARD_VALUE', 'DISCARD_VALUE'])
        self.assertIn('.details.claude.requestDuration.value', item['preprocessing'][0]['parameters'][0])
        self.assertIn('.details.totals.cost.value', self.items['ai.all.cost[24h]']['preprocessing'][0]['parameters'][0])

    def test_sum_script_embeds_lld_macros(self):
        script = module.sum_js('{#AGENT}.cost', model='{#MODEL}')
        self.assertIn('"{#AGENT}.cost"', script)
        self.assertIn('{"model": "{#MODEL}"}', script)

    def test_bucket_items_accept_backfill(self):
        for (period, item, agent) in module.bucket_specs():
            bucket, live, delay, history, _ = module.PERIODS[period]
            self.assertEqual(86400 % bucket, 0)
            it = self.items[f'ai.{period}.{item}[{agent}]']
            self.assertEqual(it['allow_traps'], 'YES')
            self.assertEqual(it['allowed_hosts'], '{$AI.PUSH.ALLOWED}')
            self.assertEqual(it['delay'], delay)
            self.assertIn(f'bucket = {bucket};', it['preprocessing'][0]['parameters'][0])

    def test_bucket_value(self):
        day = 86400 * 20000
        datasets = {
            'claude.cost': {'series': [{'dimensions': {'model': 'a'}, 'points': [[day - 3600, 5], [day, 1], [day + 82800, 2], [day + 86400, 7]]}]},
            'codex.cost': {'series': [{'dimensions': {'model': 'b'}, 'points': [[day + 10800, 0.5]]}]},
            'claude.tokens': {'series': [{'dimensions': {'category': c}, 'points': [[day, v]]}
                                         for c, v in (('total', 10), ('cached', 6), ('input', 1), ('written', 1), ('output', 2))]},
            'codex.tokens': {'series': []},
            'claude.requestDuration': {'series': [{'dimensions': {}, 'points': [[day, 2.0], [day + 10800, 4.0]]}],
                                       'details': {'totalTimeline': [[day, 6.0], [day + 10800, 4.0]]}},
        }
        specs = {k[1:]: v[2] for k, v in module.bucket_specs().items() if k[0] == 'daily'}
        full = (day, day + 86400)
        self.assertEqual(module.bucket_value(datasets, specs['cost', 'claude'], *full), 3)
        self.assertEqual(module.bucket_value(datasets, specs['cost', 'all'], *full), 3.5)
        self.assertEqual(module.bucket_value(datasets, specs['tokens', 'all'], *full), 10)
        hit = module.bucket_specs()['3h', 'cache.hit', 'all'][2]
        self.assertEqual(module.bucket_value(datasets, hit, *full), 75)
        wavg = {'agg': 'wavg', 'parts': [['claude.requestDuration', {}]]}
        self.assertEqual(module.bucket_value(datasets, wavg, *full), 10 / 4)  # 3 requests of 2 s, 1 of 4 s
        self.assertIsNone(module.bucket_value(datasets, wavg, day + 86400, day + 172800))
        self.assertEqual(module.lld_spec('ai.model.cost.3h[claude,claude-opus-5-5]'),
                         {'agg': 'sum', 'parts': [['claude.cost', {'model': 'claude-opus-5-5'}]]})

    def test_chunks_cover_range_coarse_to_fine(self):
        day = 86400 * 20000
        coverage = {'30d': day - 86400 * 20, '7d': day + 86400, '24h': day + 86400 + 10800, '1h': day + 86400 + 18000}
        until = day + 86400 + 18000 + 1200
        parts, lost = module.chunks(day, until, coverage)
        self.assertEqual(lost, 0)
        self.assertEqual([(r, e - s) for r, s, e in parts],
                         [('30d', 86400), ('7d', 10800)] + [('24h', 1800)] * 4 + [('1h', 600)] * 2)
        self.assertEqual(parts[0][1], day)
        self.assertEqual(parts[-1][2], until)
        late = {r: day + 1200 for r in coverage}  # nothing covers the first 20 minutes any more
        parts, lost = module.chunks(day, day + 3600, late)
        self.assertEqual(lost, 1200)
        self.assertEqual([(r, s - day, e - s) for r, s, e in parts], [('1h', 1200, 600), ('24h', 1800, 1800)])

    def test_no_private_address_in_template(self):
        text = json.dumps(self.export)
        self.assertNotIn('homestack.app', text)
        self.assertNotIn('192.168.', text)


if __name__ == '__main__':
    unittest.main()
