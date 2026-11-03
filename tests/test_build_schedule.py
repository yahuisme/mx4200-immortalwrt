"""Verify direct cron scheduling without dispatching a firmware build."""
from datetime import datetime
from pathlib import Path
import unittest
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BuildScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(
            (ROOT / '.github/workflows/MX4200.yml').read_text())

    def test_direct_three_day_cron_at_hong_kong_noon(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(triggers['schedule'], [{'cron': '0 4 */3 * *'}])
        self.assertEqual(set(triggers), {'schedule', 'workflow_dispatch'})
        local = datetime(2026, 11, 1, 4, tzinfo=ZoneInfo('UTC')).astimezone(
            ZoneInfo('Asia/Hong_Kong'))
        self.assertEqual((local.hour, local.minute), (12, 0))

    def test_build_runs_without_date_gate(self):
        self.assertEqual(set(self.workflow['jobs']), {'build'})
        build = self.workflow['jobs']['build']
        self.assertNotIn('needs', build)
        self.assertNotIn('if', build)

    def test_manual_dispatch_remains_available(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertIn('workflow_dispatch', triggers)
        self.assertIsNone(triggers['workflow_dispatch'])


if __name__ == '__main__':
    unittest.main()
