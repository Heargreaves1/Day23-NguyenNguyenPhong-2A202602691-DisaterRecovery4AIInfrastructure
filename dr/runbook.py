"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402
from dr import health_checker as hc  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Ghi 1 dòng {ts, iso, step, name, ...} vào LOG."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "step": n,
        "name": name,
        **kw,
    }
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
        f.flush()
    print(f"STEP {n} [{name}]", json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    """auto=True -> True; ngược lại hỏi y/N. Đừng bỏ hàm này đi."""
    if auto:
        return True
    ans = input(f"{msg} [y/N]: ").strip().lower()
    return ans in ("y", "yes")


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    t_start = time.time()

    # Bước 1: xac_nhan_outage — probe cả 2 region, xác nhận alert từ health check
    health_path = pathlib.Path("reports/health-events.jsonl")
    chaos_path = pathlib.Path("chaos/chaos-events.jsonl")
    t_outage = None
    t_outage_iso = None
    if chaos_path.exists():
        kills = [
            json.loads(line)
            for line in chaos_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("action") == "kill"
        ]
        if kills:
            t_outage = kills[-1]["ts"]
            t_outage_iso = kills[-1].get("iso")

    # Đợi health checker ghi nhận UNHEALTHY (hoặc probe 3 lần)
    t_wait_alert = time.time()
    detected_by_hc = False
    while time.time() - t_wait_alert < 25:
        if health_path.exists():
            hev = [
                json.loads(l)
                for l in health_path.read_text(encoding="utf-8").splitlines()
                if l.strip()
                and json.loads(l).get("event") == "state_change"
                and json.loads(l).get("to") == "UNHEALTHY"
                and json.loads(l).get("region") == primary
                and (t_outage is None or json.loads(l).get("ts") >= t_outage)
            ]
            if hev:
                detected_by_hc = True
                break
        time.sleep(0.5)

    p_fails = 0
    for _ in range(3):
        ok, _ = hc.probe(primary, timeout=1.0)
        if not ok:
            p_fails += 1
        time.sleep(0.1)

    t_alive = False
    try:
        t_alive = httpx.get(f"{URL[target]}/healthz", timeout=1.5).status_code == 200
    except Exception:
        pass

    ev1 = step(
        1,
        "xac_nhan_outage",
        primary=primary,
        primary_fails=p_fails,
        primary_outage=(p_fails >= 2 or detected_by_hc),
        health_alert_detected=detected_by_hc,
        target=target,
        target_alive=t_alive,
    )

    if not confirm(auto, f"Cảnh báo: region-{primary} không phản hồi. Tiến hành failover sang region-{target}?"):
        return {"ok": False, "aborted": True, "step": 1}

    # Bước 2: thong_bao_incident
    chaos_path = pathlib.Path("chaos/chaos-events.jsonl")
    t_outage = None
    t_outage_iso = None
    if chaos_path.exists():
        kills = [
            json.loads(line)
            for line in chaos_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line).get("action") == "kill"
        ]
        if kills:
            t_outage = kills[-1]["ts"]
            t_outage_iso = kills[-1].get("iso")

    t_notify = time.time()
    notification_delay = round(t_notify - t_outage, 2) if t_outage else None

    step(
        2,
        "thong_bao_incident",
        incident_id=f"INC-{int(t_notify)}",
        t_outage=t_outage,
        t_outage_iso=t_outage_iso,
        t_notify=t_notify,
        notification_delay_s=notification_delay,
    )

    # Bước 3: scale_gpu_pool — gọi hàm failover.failover MỘT LẦN DUY NHẤT
    fo_result = fo.failover(target=target, backend=backend, wait=60.0)
    step(
        3,
        "scale_gpu_pool",
        target=target,
        failover_ok=fo_result.get("ok"),
        waited_s=fo_result.get("waited_s"),
    )

    # Bước 4: verify_state_replica — đọc kết quả từ dict bước 3
    t_state = fo_result.get("target_state", {})
    step(
        4,
        "verify_state_replica",
        rpo_seconds=fo_result.get("rpo_seconds"),
        docs_lost=fo_result.get("docs_lost"),
        embed_model_version=fo_result.get("embed_model_version"),
        vector_count=t_state.get("count"),
        weights_present=t_state.get("weights"),
    )

    # Bước 5: dns_cutover — đọc lại kết quả cutover
    step(
        5,
        "dns_cutover",
        cutover_ok=fo_result.get("ok"),
        active_region=target if fo_result.get("ok") else primary,
    )

    # Bước 6: verify_golden_signals — 10 request thật vào region phụ
    latencies = []
    errors = 0
    with httpx.Client(timeout=3.0) as client:
        for i in range(10):
            t0 = time.time()
            try:
                res = client.get(f"{URL[target]}/v1/infer", params={"q": f"probe golden signal #{i}"})
                lat_ms = round((time.time() - t0) * 1000, 1)
                latencies.append(lat_ms)
                if res.status_code != 200:
                    errors += 1
            except Exception:
                errors += 1
            time.sleep(0.05)

    latencies.sort()
    p95 = latencies[int(0.95 * len(latencies)) - 1] if latencies else None
    error_rate = round(errors / 10.0, 2)
    step(
        6,
        "verify_golden_signals",
        requests_sent=10,
        errors=errors,
        error_rate=error_rate,
        p95_latency_ms=p95,
    )

    # Bước 7: post_incident — elapsed_s + lệnh đo RTO
    elapsed_s = round(time.time() - t_start, 2)
    step(
        7,
        "post_incident",
        elapsed_s=elapsed_s,
        measure_cmd="python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300",
    )

    return {
        "ok": fo_result.get("ok"),
        "primary": primary,
        "target": target,
        "elapsed_s": elapsed_s,
        "failover": fo_result,
        "golden_signals": {"error_rate": error_rate, "p95_latency_ms": p95},
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
