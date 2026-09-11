import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import series
from common import ROOT, atomic_json, read_json


class SeriesTest(unittest.TestCase):
    def test_failure_stops_before_second_experiment(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            config = directory / 'config.json'
            plan = directory / 'plan.json'
            atomic_json(config, {'run': 'first'})
            atomic_json(plan, {'id': str(directory / 'series'), 'jobs': [
                {'config': str(config), 'opponents': []},
                {'config': str(config), 'opponents': []}]})
            with patch.object(series.subprocess, 'Popen') as spawn:
                spawn.return_value.wait.return_value = 3
                spawn.return_value.pid = 123
                with self.assertRaisesRegex(RuntimeError, 'exited 3'):
                    series.execute(plan)
            self.assertEqual(spawn.call_count, 1)
            result = read_json(directory / 'series/status.json')
            self.assertEqual(result['state'], 'failed')
            self.assertEqual(result['completed'], [])


if __name__ == '__main__':
    unittest.main()
