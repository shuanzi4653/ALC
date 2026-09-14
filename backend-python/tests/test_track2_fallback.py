import unittest

import track2_agent


def snapshot(**changes):
    value = {
        "windSpeed": 4.0, "windGust": 7.0, "precipMmh": 0.0,
        "visibilityM": 12000.0, "thunderProb": 0.05, "tempC": 25.0,
    }
    value.update(changes)
    return value


class Track2FallbackTest(unittest.TestCase):
    def test_single_hard_threshold_forces_ban(self):
        result = track2_agent._fallback(snapshot(precipMmh=5.0), 6, "test", "巡检")
        self.assertEqual(result["risk_level"], "禁飞")
        self.assertTrue(result["hard_ban"])
        self.assertEqual(result["raw_sfi"], 65)
        self.assertEqual(result["sfi"], 39)

    def test_temperature_is_part_of_fallback(self):
        result = track2_agent._fallback(snapshot(tempC=46.0), 6, "test", "巡检")
        self.assertEqual(result["risk_level"], "禁飞")
        self.assertTrue(result["hard_ban"])

    def test_missing_data_is_not_assumed_safe(self):
        value = snapshot()
        del value["windSpeed"]
        with self.assertRaises(ValueError):
            track2_agent._fallback(value, 6, "test", "巡检")

    def test_deepseek_result_carries_local_rule_version(self):
        original_chat = track2_agent._chat
        track2_agent._chat = lambda *_args, **_kwargs: '''{
            "risk_level":"谨慎", "confidence":0.8,
            "key_factors":["阵风增强", "能见度下降"],
            "advice":"降低飞行高度", "alert_text":"谨慎飞行"
        }'''
        try:
            result = track2_agent.analyze(snapshot(), [], "辽宁", "巡检", {"api_key": "test"})
        finally:
            track2_agent._chat = original_chat

        self.assertEqual(result["source"], "deepseek")
        self.assertEqual(result["rule_version"], "v1")


if __name__ == "__main__":
    unittest.main()
