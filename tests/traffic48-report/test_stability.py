"""Prevent mixed schedules, unmatched baselines and averaged percentiles."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import traffic48_stability as stability


def row(success, histogram, valid=True):
    return dict(seconds=60, offered=100, started=100, completed=100,
                success=success, dropped=0, http_errors=100-success,
                transport_errors=0, timeouts=0, histogram=histogram,
                memory_gc={}, valid=valid,
                qualification={"qualified": valid})


class Stability(unittest.TestCase):
    def test_day2_comparison_excludes_day1_and_unfinished_phases(self):
        phases = [
            dict(name="d1-c1-l100-s4", finished=True, duration_seconds=60),
            dict(name="d2-c1-l100-s2", finished=True, duration_seconds=60),
            dict(name="d2-c2-l100-s2", finished=False, duration_seconds=60),
            dict(name="d2-c4-l100-s2", finished=True, duration_seconds=60),
        ]
        self.assertEqual([p["name"] for p in stability.select(phases, [1, 2, 3], 60)],
                         ["d2-c1-l100-s2"])

    def test_comparison_uses_same_phases_and_pools_histograms(self):
        phases = [
            dict(name="one", instances={"flex": row(50, {"1": 99, "10": 1}),
                                        "standard": row(100, {"1": 100})}),
            dict(name="two", instances={"flex": row(100, {"10": 100}),
                                        "standard": row(100, {"1": 100}, False)}),
        ]
        result = stability.paired(phases, "flex", "standard", "strict")
        self.assertEqual(result["phase_names"], ["one"])
        self.assertEqual(result["rps_ratio"], .5)
        self.assertEqual(result["target"]["p99_ms"], .001)
        observed = stability.paired(phases, "flex", "standard", "observed")
        self.assertEqual(observed["target"]["p99_ms"], .010)
        self.assertEqual(observed["rps_ratio"], .75)

    def test_missing_comparison_is_null_and_window_boundary_not_duplicated(self):
        self.assertIsNone(stability.paired([], "flex", "standard", "strict")["target"])
        probes = [dict(elapsed_sec=t, probe_rps=v, p99_latency_ms=2*v,
                       socket_errors=0, http_errors=0)
                  for t, v in [(60, 10), (3600, 20), (3601, 30), (7200, 40)]]
        early = stability.probe_window(probes, 0, 3600)
        late = stability.probe_window(probes, 3600, 7200)
        self.assertEqual((early["samples"], late["samples"]), (2, 2))
        self.assertEqual(early["probe_rps_mean"], 15)
        self.assertEqual(late["probe_rps_mean"], 35)
        self.assertEqual(late["per_probe_p99_median_ms"], 70)

    def test_drop_onset_requires_five_adjacent_low_samples_after_baseline(self):
        rows = [dict(elapsed_sec=t, probe_rps=v) for t, v in
                [(3500, 50), (3560, 50), (3620, 50), (3680, 50), (3740, 100),
                 (3800, 80), (3860, 80), (3920, 80), (3980, 80), (4040, 80)]]
        result = stability.drop_onset(rows, 100)
        self.assertEqual(result["first_frame_end_seconds"], 3800)
        self.assertEqual(result["confirmed_at_seconds"], 4040)
        rows[-1]["elapsed_sec"] = 4400
        self.assertIsNone(stability.drop_onset(rows, 100))


if __name__ == "__main__":
    unittest.main()
