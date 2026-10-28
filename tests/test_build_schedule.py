"""Exercise the real schedule gate without dispatching a firmware build."""
from datetime import datetime, timedelta
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]


class BuildScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(
            (ROOT / '.github/workflows/MX4200.yml').read_text())

    def evaluate(self, event, instant):
        gate = self.workflow['jobs'].get('schedule')
        self.assertIsNotNone(gate, 'continuous three-day schedule gate is missing')
        run = gate['steps'][0]['run']
        code = run.split("python3 - <<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            with patch.dict(os.environ, GITHUB_EVENT_NAME=event,
                            GITHUB_OUTPUT=str(output)), patch('datetime.datetime', Clock):
                exec(compile(code, '<workflow schedule>', 'exec'), {})
            return output.read_text().strip() == 'build=true'

    def test_hong_kong_noon_and_build_dependency(self):
        triggers = self.workflow.get('on', self.workflow.get(True))
        self.assertEqual(triggers['schedule'], [{'cron': '0 4 * * *'}])
        self.assertIn('workflow_dispatch', triggers)
        self.assertEqual(set(triggers), {'schedule', 'workflow_dispatch'})
        build = self.workflow['jobs']['build']
        self.assertEqual(build['needs'], 'schedule')
        self.assertEqual(build['if'], "needs.schedule.outputs.build == 'true'")
        self.assertEqual(self.workflow['jobs']['schedule']['outputs']['build'],
                         '${{ steps.due.outputs.build }}')
        self.assertEqual(self.workflow['jobs']['schedule']['steps'][0]['id'], 'due')
        local = datetime(2026, 10, 29, 4, tzinfo=ZoneInfo('UTC')).astimezone(
            ZoneInfo('Asia/Hong_Kong'))
        self.assertEqual(local.hour, 12)

    def test_continuous_three_day_cadence(self):
        start = datetime(2026, 10, 28, 4, tzinfo=ZoneInfo('UTC'))
        due = [start + timedelta(days=i) for i in range(500)
               if self.evaluate('schedule', start + timedelta(days=i))]
        self.assertEqual(due[0].date().isoformat(), '2026-10-29')
        self.assertTrue(all(b - a == timedelta(days=3) for a, b in zip(due, due[1:])))
        self.assertEqual(len(due), 167)

    def test_manual_dispatch_bypasses_date_gate(self):
        for day in (28, 29, 30):
            self.assertTrue(self.evaluate('workflow_dispatch',
                datetime(2026, 10, day, 4, tzinfo=ZoneInfo('UTC'))))


if __name__ == '__main__':
    unittest.main()
