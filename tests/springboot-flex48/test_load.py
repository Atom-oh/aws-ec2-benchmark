"""Exercise the real load script with short-lived wrk/curl executables."""
import os
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LoadTest(unittest.TestCase):
    def run_load(self, rps="1234.50", early=False, omit_latency=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bindir = root / "bin"
            bindir.mkdir()
            (bindir / "wrk").write_text("""#!/bin/sh
for arg in "$@"; do
 case "$arg" in -d*) duration=${arg#-d}; duration=${duration%s};; -t*) threads=$arg;; esac
done
if [ "${EARLY:-0}" = 1 ] && [ "$threads" = -t4 ] && [ "$duration" = 3 ]; then duration=2; fi
sleep "$duration"
if [ "${OMIT_LATENCY:-0}" = 0 ]; then
 echo '  Latency   100us  20us  1ms  90%'
 echo '  Latency Distribution'
 echo '  99% 1.50ms'
fi
echo 'Requests/sec: """ + rps + "'\n")
            (bindir / "curl").write_text("""#!/bin/sh
echo '{"measurements":[{"statistic":"VALUE","value":0.85}]}'
""")
            for path in bindir.iterdir():
                path.chmod(0o755)
            env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
                       RESULTS_DIR=str(root / "results"), TARGET="http://test:8080",
                       DURATION_SECONDS="3", WARMUP_SECONDS="1", SAMPLE_SECONDS="1",
                       INSTANCE_TYPE="m7i-flex.xlarge", RUN_ID="test", CLEANUP="0",
                       EARLY="1" if early else "0", OMIT_LATENCY="1" if omit_latency else "0")
            if early:
                env["SAMPLE_SECONDS"] = "3"
            result = subprocess.run(["sh", str(ROOT / "scripts/springboot-flex48-load.sh")],
                                    env=env, capture_output=True, text=True, timeout=15)
            files = {p.name: p.read_text() for p in (root / "results").glob("*")}
            return result, files

    def test_continuous_load_and_durable_samples(self):
        result, files = self.run_load()
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("COMPLETE", files["status.txt"])
        self.assertIn("Requests/sec: 1234.50", files["continuous.log"])
        self.assertIn(",1234.50,0.100,1.500,", files["samples.csv"])
        self.assertIn("system.cpu.usage", files["metrics.ndjson"])
        self.assertGreaterEqual(len(files["samples.csv"].splitlines()), 2)

    def test_zero_throughput_is_a_failed_run(self):
        result, files = self.run_load("0.00")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", files["status.txt"])
        self.assertNotIn("COMPLETE", files["status.txt"])

    def test_continuous_load_cannot_exit_during_final_probe(self):
        result, files = self.run_load(early=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", files["status.txt"])

    def test_missing_latency_is_not_reported_as_zero(self):
        result, files = self.run_load(omit_latency=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FAILED", files["status.txt"])


class RecoveryTest(unittest.TestCase):
    def test_recover_average_from_original_wrk_output(self):
        spec = importlib.util.spec_from_file_location("flex48", ROOT / "scripts/springboot_flex48.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            source = "timestamp,elapsed_sec,probe_rps,avg_latency_ms,p99_latency_ms,socket_errors,http_errors\n2026-11-04T01:28:28Z,60,22879.33,0.000,7.980,0,0\n"
            (p / "samples.csv").write_text(source)
            (p / "probes.log").write_text("\n--- 2026-11-04T01:28:28Z elapsed=60 duration=60 ---\n    Latency 4.36ms 1.19ms 56.09ms 83.33%\n  Latency Distribution\n 99% 7.98ms\nRequests/sec: 22879.33\n")
            module.recover_latency(p)
            self.assertIn(",22879.33,4.360,7.980,0,0", (p / "samples.csv").read_text())
            self.assertEqual((p / "samples-raw.csv").read_text(), source)
            module.recover_latency(p)
            self.assertEqual((p / "samples-raw.csv").read_text(), source)


if __name__ == "__main__":
    unittest.main()
