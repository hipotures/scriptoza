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

    def test_period_items_accept_backfill(self):
        for period, (bucket, live, delay, history, _) in module.PERIODS.items():
            self.assertEqual(86400 % bucket, 0)
            for agent in ['all', *module.AGENTS]:
                for measure in module.MEASURES:
                    item = self.items[f'ai.{period}.{measure}[{agent}]']
                    self.assertEqual(item['allow_traps'], 'YES')
                    self.assertEqual(item['allowed_hosts'], '{$AI.PUSH.ALLOWED}')
                    self.assertEqual(item['delay'], delay)
                    self.assertIn(f'bucket = {bucket};', item['preprocessing'][0]['parameters'][0])

    def test_daily_total_sums_one_utc_day(self):
        day = 86400 * 20000
        datasets = {
            'claude.cost': {'series': [{'dimensions': {'model': 'a'}, 'points': [[day - 3600, 5], [day, 1], [day + 82800, 2], [day + 86400, 7]]}]},
            'codex.cost': {'series': [{'dimensions': {'model': 'b'}, 'points': [[day + 10800, 0.5]]}]},
            'claude.tokens': {'series': [{'dimensions': {'category': 'total'}, 'points': [[day, 10]]},
                                         {'dimensions': {'category': 'output'}, 'points': [[day, 3]]}]},
            'codex.tokens': {'series': []},
        }
        self.assertEqual(module.bucket_total(datasets, 'claude', 'cost', day, day + 86400), 3)
        self.assertEqual(module.bucket_total(datasets, 'all', 'cost', day, day + 86400), 3.5)
        self.assertEqual(module.bucket_total(datasets, 'all', 'tokens', day, day + 86400), 10)

    def test_dashboard_uses_existing_items_and_fits_grid(self):
        names = {i['name'] for i in self.template['items']}
        keys = {i['key'] for i in self.template['items']}
        widgets = module.dashboard_widgets('ai-usage', {k: '1' for k in keys})
        for w in widgets:
            self.assertLessEqual(w['x'] + w['width'], 72)
            for field in w['fields']:
                if field['name'].startswith('ds.') and field['name'].endswith('.items.0') and '*' not in field['value']:
                    self.assertIn(field['value'], names)
        self.assertRaises(KeyError, module.dashboard_widgets, 'ai-usage', {})

    def test_no_private_address_in_template(self):
        text = json.dumps(self.export)
        self.assertNotIn('homestack.app', text)
        self.assertNotIn('192.168.', text)


if __name__ == '__main__':
    unittest.main()
