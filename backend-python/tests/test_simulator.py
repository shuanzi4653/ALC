import unittest
from datetime import datetime, timezone

import simulator


class SimulatorTest(unittest.TestCase):
    def test_fixed_seed_and_clock_are_repeatable(self):
        fixed = datetime(2026, 9, 9, 2, 0, tzinfo=timezone.utc)
        first = simulator.generate("storm", 3, 38.91, 121.61, seed=7, now=fixed)
        second = simulator.generate("storm", 3, 38.91, 121.61, seed=7, now=fixed)
        self.assertEqual(first, second)
        self.assertEqual(len(first["hourly"]), 3)
        self.assertEqual(first["snapshot"]["time"], "2026-09-09T02:00+08:00")

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(ValueError):
            simulator.generate("invalid", seed=1)


if __name__ == "__main__":
    unittest.main()
