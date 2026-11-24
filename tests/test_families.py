"""Contracts for the optional specialist-family catalog and role boundaries."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / 'agents'

import sys
sys.path.insert(0, str(ROOT / 'lib'))
from agentkit_core import selection

EXPECTED_FAMILIES = {
    'design': ['design-ux-research', 'design-ux-architecture'],
    'seo': ['seo-aeo-foundations', 'seo-agentic-search', 'seo-ai-citations'],
    'marketing': [
        'marketing-aso', 'marketing-dev-community', 'marketing-email',
        'marketing-instagram', 'marketing-linkedin', 'marketing-publishing',
        'marketing-reddit', 'marketing-tiktok', 'marketing-x-engagement',
        'marketing-x-research',
    ],
    'product': ['product-trends', 'product-behavior', 'product-experiments'],
    'security': [
        'security-ai-code', 'security-architecture', 'security-compliance',
        'security-appsec', 'security-credentials', 'security-threat-intel',
        'security-detection',
    ],
    'tester': ['test-accessibility', 'test-api', 'test-performance', 'test-e2e'],
}
EXPECTED_EXTRA_PARENTS = {'architect', 'payments', 'workflow-optimizer', 'product'}


class FamilyCatalogTests(unittest.TestCase):
    def routing(self):
        path = AGENTS / 'routing.json'
        self.assertTrue(path.is_file(), 'agents/routing.json is missing')
        return json.loads(path.read_text(encoding='utf-8'))['families']

    def test_family_catalog_is_separate_from_required_and_dependency_rules(self):
        self.assertEqual(self.routing(), EXPECTED_FAMILIES)

        selection = json.loads((AGENTS / 'selection.json').read_text(encoding='utf-8'))
        self.assertEqual(set(selection), {'required', 'dependencies'})
        children = {child for family in self.routing().values() for child in family}
        self.assertFalse(children & set(selection['required']))
        self.assertFalse(children & {child for deps in selection['dependencies'].values() for child in deps})

    def test_catalog_has_exact_fifty_roles_and_all_sources(self):
        families = self.routing()
        children = {child for members in families.values() for child in members}
        roles = {path.stem for path in AGENTS.glob('*.md')}
        parents = roles - children
        self.assertEqual(set(families), {'design', 'seo', 'marketing', 'product', 'security', 'tester'})
        self.assertEqual(len(children), 29)
        self.assertTrue(EXPECTED_EXTRA_PARENTS <= parents)
        self.assertEqual(len(parents | children), 50)
        self.assertFalse(parents & children, 'a specialist child must not also be a parent role')
        for name in parents | children:
            with self.subTest(role=name):
                self.assertTrue((AGENTS / (name + '.md')).is_file())

    def test_parent_roles_define_scoped_child_delegation_and_report_fix_path(self):
        families = self.routing()
        for parent, children in families.items():
            source = (AGENTS / (parent + '.md')).read_text(encoding='utf-8').lower()
            with self.subTest(parent=parent):
                self.assertTrue(re.search(r'parent.{0,40}child|child.{0,40}parent', source))
                self.assertIn('approved', source)
                self.assertIn('objective', source)
                self.assertIn('acceptance', source)
                self.assertTrue(re.search(r'no (?:scope )?expansion|must not expand', source))
                self.assertTrue(re.search(r'report.{0,60}fix|fix.{0,60}report', source))

    def test_children_include_english_memory_and_learning_sections(self):
        families = self.routing()
        children = [child for members in families.values() for child in members]
        for name in children:
            body = (AGENTS / (name + '.md')).read_text(encoding='utf-8')
            lower = body.lower()
            with self.subTest(role=name):
                self.assertRegex(body, r'(?m)^#')
                self.assertRegex(lower, r'(?m)^##? .*memory')
                self.assertIn('learning', lower)
                self.assertNotRegex(body, r'[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]')
                self.assertRegex(body, r'(?m)^---\s*$')

    def test_security_children_are_defensive_and_static_or_read_only(self):
        children = self.routing()['security']
        for name in children:
            body = (AGENTS / (name + '.md')).read_text(encoding='utf-8').lower()
            with self.subTest(role=name):
                self.assertRegex(body, r'defensive|authorized|owned system')
                self.assertRegex(body, r'static|read.only|analysis only')
                self.assertRegex(body, r'fake service|test double|fixture')

    def test_specialist_e2e_and_api_roles_require_fakes(self):
        families = self.routing()
        for name in families['tester']:
            body = (AGENTS / (name + '.md')).read_text(encoding='utf-8').lower()
            with self.subTest(role=name):
                self.assertRegex(body, r'fake|fixture|stub|mock')
                self.assertRegex(body, r'failure|edge case|negative')

    def test_picker_can_select_multiple_nested_children_in_a_subset_roster(self):
        available = ('backend', 'database', 'security', 'supervisor-plan',
                     'supervisor-review', 'tester', 'test-api', 'test-e2e')
        rules = (['supervisor-plan', 'supervisor-review'],
                 {'backend': ['database', 'security', 'tester']})
        initial = selection.resolve(available, ('test-api', 'test-e2e'), rules)
        answers = iter(['7', '8', ''])
        lines = []
        result = selection.choose(
            'codex', available, initial, rules, lambda _prompt: next(answers),
            lines.append, lambda _choice, _say: [],
            families={'tester': ('test-api', 'test-e2e')},
        )
        self.assertTrue({'test-api', 'test-e2e'} <= result.active)
        self.assertIn('test-api', '\n'.join(lines))
        self.assertIn('test-e2e', '\n'.join(lines))

    def test_picker_parent_selects_family_then_allows_one_child_to_be_deselected(self):
        available = ('design', 'design-ux-research', 'design-ux-architecture', 'backend')
        rules = ([], {})
        choice = selection.resolve(
            available, ('design', 'design-ux-research', 'design-ux-architecture'), rules,
        )
        answers = iter(['1', '2', ''])
        result = selection.choose(
            'claude', available, choice, rules, lambda _prompt: next(answers),
            lambda _line: None, lambda _choice, _say: [],
            families={'design': ('design-ux-research', 'design-ux-architecture')},
        )
        self.assertEqual(result.active, {'design', 'design-ux-architecture', 'backend'})
        self.assertEqual(result.excluded, {'design-ux-research'})

    def test_saved_child_exclusions_survive_update_and_legacy_parent_exclusion(self):
        families = {'tester': ('test-api', 'test-e2e')}
        saved_manifest = {
            'excluded_agents': ['test-api'],
            'family_selection_version': selection.FAMILY_VERSION,
            'files': {'agents/test-api.md': 'owned'},
        }
        self.assertEqual(selection.restore_exclusions(saved_manifest, 'claude', families), {'test-api'})

        # Before family children existed, an excluded parent represented an opted-out group.
        legacy_manifest = {'excluded_agents': ['tester'], 'files': {'agents/backend.md': 'owned'}}
        self.assertEqual(
            selection.restore_exclusions(legacy_manifest, 'claude', families),
            {'tester', 'test-api', 'test-e2e'},
        )

    def test_dependency_reenabling_opted_out_parent_does_not_select_its_children(self):
        available = ('backend', 'security', 'security-appsec', 'database')
        rules = ([], {'backend': ['security']})
        selected = selection.resolve(available, ('security', 'security-appsec'), rules)
        self.assertIn('security', selected.active)
        self.assertNotIn('security-appsec', selected.active)
        self.assertEqual(selected.excluded, {'security', 'security-appsec'})

    def test_family_loader_rejects_missing_and_duplicate_children(self):
        with tempfile.TemporaryDirectory(prefix='agentkit-routing-') as temp:
            root = Path(temp)
            shutil.copytree(AGENTS, root / 'agents')
            path = root / 'agents/routing.json'
            families = self.routing()
            families['tester'].append('test-absent')
            path.write_text(json.dumps({'families': families}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'missing from the catalog'):
                selection.load_families(root, selection.load_rules(root))

            families = self.routing()
            families['tester'].append(families['seo'][0])
            path.write_text(json.dumps({'families': families}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'invalid or repeated'):
                selection.load_families(root, selection.load_rules(root))


if __name__ == '__main__':
    unittest.main()
