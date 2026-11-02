import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'zabbix' / 'build_pve_templates.py'
spec = importlib.util.spec_from_file_location('build_pve_templates', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PveTemplateTests(unittest.TestCase):
    def setUp(self):
        self.export = module.build()['zabbix_export']
        self.templates = {t['name']: t for t in self.export['templates']}

    def test_three_templates(self):
        self.assertEqual(set(self.templates), {module.NODE, module.GUEST, module.CLUSTER})

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

    def test_dependent_items_point_to_master(self):
        for template in self.templates.values():
            keys = {i['key'] for i in template['items']}
            self.assertIn(module.MASTER, keys)
            for item in template['items']:
                if item['type'] == 'DEPENDENT':
                    self.assertEqual(item['master_item']['key'], module.MASTER)

    def test_dashboard_item_names(self):
        names = {i['name'] for i in self.templates[module.NODE]['items']}
        self.assertTrue({'CPU utilization', 'Memory utilization', 'Load average (1m avg)'} <= names)
        guest = {i['name'] for i in self.templates[module.GUEST]['items']}
        self.assertTrue({'CPU utilization', 'Memory utilization', 'Number of processes'} <= guest)

    def test_guest_fs_discovery_skips_image_file_systems(self):
        rule = self.templates[module.GUEST]['discovery_rules'][0]
        macros = {m['macro']: m['value'] for m in self.templates[module.GUEST]['macros']}
        self.assertRegex('squashfs', macros['{$PVE.FS.TYPE.NOT_MATCHES}'])
        self.assertNotRegex('ext4', macros['{$PVE.FS.TYPE.NOT_MATCHES}'])
        self.assertRegex('/snap/core24/1643', macros['{$PVE.FS.MOUNT.NOT_MATCHES}'])
        self.assertEqual(len(rule['filter']['conditions']), 2)

    def test_lost_hosts_are_disabled_at_once(self):
        for rule in self.templates[module.CLUSTER]['discovery_rules']:
            self.assertEqual(rule['enabled_lifetime_type'], 'DISABLE_IMMEDIATELY')
            self.assertEqual(len(rule['host_prototypes']), 1)


if __name__ == '__main__':
    unittest.main()
