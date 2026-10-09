import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

env = os.environ.copy()
env["PYTHONUTF8"] = "1"

# Clean previous reports for drill 1
(ROOT / "reports" / "drill-1-nodr.jsonl").unlink(missing_ok=True)

# Seed
subprocess.run([sys.executable, "state/seed_vectors.py", "--region", "a", "--docs", "200"], check=True, env=env)
subprocess.run([sys.executable, "state/seed_vectors.py", "--region", "b", "--docs", "0", "--weights-mb", "0"], check=True, env=env)
(ROOT / "edge" / "active_region").write_text("a")

# Up
subprocess.run([sys.executable, "scripts/up_bare.py"], check=True, env=env)

# Traffic in background
out_path = ROOT / "reports" / "drill-1-nodr.jsonl"
p_traffic = subprocess.Popen([sys.executable, "loadgen/traffic.py", "--duration", "40", "--rps", "2", "--out", str(out_path)], env=env)

# Wait 8s
time.sleep(8)

# Kill region a
subprocess.run([sys.executable, "chaos/kill_region.py", "--region", "a", "--mode", "netblock", "--mock"], check=True, env=env)

# Wait traffic
p_traffic.wait()

# Measure
res = subprocess.run([sys.executable, "tools/measure_rto.py", "--loadgen", str(out_path), "--target-rto", "300"], capture_output=True, text=True, env=env)
print("MEASURE RESULT:")
print(res.stdout)
(ROOT / "reports" / "measure-drill-1.json").write_text(res.stdout, encoding="utf-8")

# Restore Region A
subprocess.run([sys.executable, "chaos/kill_region.py", "restore", "--region", "a", "--backend", "bare"], check=True, env=env)
