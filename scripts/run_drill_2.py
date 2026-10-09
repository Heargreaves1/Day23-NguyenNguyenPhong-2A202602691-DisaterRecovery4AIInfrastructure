import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

env = os.environ.copy()
env["PYTHONUTF8"] = "1"

# Clean previous reports for drill 2
(ROOT / "reports" / "drill-2-withdr.jsonl").unlink(missing_ok=True)
(ROOT / "reports" / "health-events.jsonl").unlink(missing_ok=True)
(ROOT / "reports" / "failover-events.jsonl").unlink(missing_ok=True)
(ROOT / "reports" / "runbook-run.jsonl").unlink(missing_ok=True)

# Seed Region B empty and set active_region to a
subprocess.run([sys.executable, "state/seed_vectors.py", "--region", "b", "--docs", "0", "--weights-mb", "0"], check=True, env=env)
(ROOT / "edge" / "active_region").write_text("a\n")
subprocess.run([sys.executable, "scripts/up_bare.py"], check=True, env=env)

# Start continuous ingest and replication
print("Starting continuous ingest and replication...")
p_ingest = subprocess.Popen(
    [sys.executable, "state/ingest.py", "--region", "a", "--rate", "0.5", "--duration", "150"],
    env=env,
)
p_rep = subprocess.Popen(
    [sys.executable, "state/replicate.py", "--every", "30", "--duration", "150", "--backend", "fs"],
    env=env,
)

# Wait 5s for first snapshot to complete
time.sleep(5)

# Start traffic and health checker
print("Starting traffic and health checker...")
out_traffic = ROOT / "reports" / "drill-2-withdr.jsonl"
out_health = ROOT / "reports" / "health-events.jsonl"

p_traffic = subprocess.Popen(
    [sys.executable, "loadgen/traffic.py", "--duration", "100", "--rps", "2", "--out", str(out_traffic)],
    env=env,
)
p_health = subprocess.Popen(
    [
        sys.executable,
        "dr/health_checker.py",
        "--interval",
        "5",
        "--threshold",
        "3",
        "--duration",
        "100",
        "--out",
        str(out_health),
    ],
    env=env,
)

# Wait 12s
print("Waiting 12s before chaos attack...")
time.sleep(12)

# Kill region a
print("Executing chaos kill on region a...")
subprocess.run(
    [sys.executable, "chaos/kill_region.py", "--region", "a", "--mode", "netblock", "--mock"],
    check=True,
    env=env,
)

# Run runbook
print("Executing automated runbook...")
subprocess.run(
    [sys.executable, "dr/runbook.py", "--primary", "a", "--target", "b", "--backend", "fs", "--auto"],
    check=True,
    env=env,
)

# Wait for traffic to complete
print("Waiting for traffic to finish...")
p_traffic.wait()

# Stop background processes
p_ingest.terminate()
p_rep.terminate()
p_health.terminate()

# Measure RTO
print("Measuring RTO...")
res = subprocess.run(
    [sys.executable, "tools/measure_rto.py", "--loadgen", str(out_traffic), "--target-rto", "300"],
    capture_output=True,
    text=True,
    env=env,
)
print("MEASURE RESULT:")
print(res.stdout)
(ROOT / "reports" / "measure-drill-2.json").write_text(res.stdout, encoding="utf-8")
