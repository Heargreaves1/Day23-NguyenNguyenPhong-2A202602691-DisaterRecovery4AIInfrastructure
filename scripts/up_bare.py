import os
import pathlib
import subprocess
import sys
import time
import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)

RUN = ROOT / "run"
REPORTS = ROOT / "reports"
RUN.mkdir(exist_ok=True)
REPORTS.mkdir(exist_ok=True)

EDGE_PORT = int(os.environ.get("EDGE_PORT", "8088"))
WARMUP_SECONDS = os.environ.get("WARMUP_SECONDS", "6")
EDGE_TTL_SECONDS = os.environ.get("EDGE_TTL_SECONDS", "5")


CREATIONFLAGS = (
    (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    if sys.platform == "win32"
    else 0
)


def start_region(r: str, port: int):
    env = os.environ.copy()
    env["REGION"] = r
    env["STATE_DIR"] = f"state/region-{r}"
    env["WARMUP_SECONDS"] = WARMUP_SECONDS
    env["PYTHONUTF8"] = "1"
    log_file = (RUN / f"region-{r}.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "serving.app:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
        creationflags=CREATIONFLAGS,
    )
    (RUN / f"region-{r}.pid").write_text(str(proc.pid))
    print(f"region-{r} pid={proc.pid} port={port}")
    return proc


def start_edge(port: int):
    env = os.environ.copy()
    env["EDGE_TTL_SECONDS"] = EDGE_TTL_SECONDS
    env["PYTHONUTF8"] = "1"
    log_file = (RUN / "edge.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "edge.proxy:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
        creationflags=CREATIONFLAGS,
    )
    (RUN / "edge.pid").write_text(str(proc.pid))
    print(f"edge pid={proc.pid} port={port}")
    return proc


def main():
    p_a = start_region("a", 8001)
    p_b = start_region("b", 8002)
    p_e = start_edge(EDGE_PORT)

    print("cho service len (toi da 10s)...")
    services = [("region-a", 8001, "/healthz"), ("region-b", 8002, "/healthz"), ("edge", EDGE_PORT, "/edge/state")]
    ok = True
    with httpx.Client(timeout=1.0) as client:
        for name, port, path in services:
            up = False
            for _ in range(10):
                try:
                    r = client.get(f"http://127.0.0.1:{port}{path}")
                    if r.status_code == 200:
                        up = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            if up:
                print(f"  {name} (port {port}): UP")
            else:
                print(f"  {name} (port {port}): KHONG PHAN HOI -- xem run/{name}.log")
                ok = False

    if not ok:
        print("MOT SO SERVICE CHUA LEN -- doc log truoc khi chay drill")
        sys.exit(1)

    try:
        r = httpx.get(f"http://127.0.0.1:{EDGE_PORT}/edge/state", timeout=2.0)
        print(r.text)
    except Exception:
        pass


if __name__ == "__main__":
    main()
