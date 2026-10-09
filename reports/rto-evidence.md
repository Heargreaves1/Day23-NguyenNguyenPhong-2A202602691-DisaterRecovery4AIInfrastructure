# RTO/RPO Evidence — Lab 23

Quy tắc duy nhất: mỗi con số ở đây phải trỏ được về **một dòng log thật**
(`đường/dẫn.jsonl:số_dòng`). `pytest tests/test_rto_evidence.py` sẽ mở từng file ra kiểm tra.
Con số không có evidence = trượt, bất kể các phần khác.

## 1. Drill 1 — không có DR (baseline)

| Chỉ số | Giá trị | Cách đo | Evidence |
|---|---|---|---|
| t_outage | `2026-10-09T07:58:55` | chaos kill | `chaos/chaos-events.jsonl:1` |
| Request fail đầu tiên | `+2.4s` | dòng `ok:false` đầu tiên sau t_outage | `reports/drill-1-nodr.jsonl:17` |
| Request thành công sau đó | không có | không có dòng `ok:true` nào sau t_outage | `reports/measure-drill-1.json` |
| RTO | `NO_RECOVERY` | `tools/measure_rto.py` | `reports/measure-drill-1.json` |

## 2. Drill 2 — có DR

| Mốc | +giây từ t_outage | Cách đo | Evidence |
|---|---|---|---|
| t_outage (mốc 0) | `+0.0s` | `action:kill` | `chaos/chaos-events.jsonl:3` |
| User thấy lỗi đầu tiên | `+2.2s` | dòng `ok:false` đầu | `reports/drill-2-withdr.jsonl:24` |
| Health check phát hiện | `+15.0s` | `to:UNHEALTHY, region:a` | `reports/health-events.jsonl:2` |
| Snapshot restore xong | `+21.4s` | `step:2_restore_snapshot` | `reports/failover-events.jsonl:2` |
| Region phụ ready | `+28.2s` | `step:4_wait_ready` | `reports/failover-events.jsonl:4` |
| DNS cutover | `+28.2s` | `step:5_dns_cutover` | `reports/failover-events.jsonl:5` |
| **RTO đo được** | `+30.2s` | dòng `ok:true` đầu sau lỗi | `reports/drill-2-withdr.jsonl:35` |

| Chỉ số | Đo được | Mục tiêu (slide §1) | Verdict |
|---|---|---|---|
| RTO — Inference API | `30.2s` | 300s (5 phút) | PASS |
| RPO — Vector DB | `8.0s` / `4` doc | 300s (5 phút) | PASS |

## 3. RTO của tôi gồm những gì (bắt buộc — đây là phần chấm điểm hiểu bài)

| Thành phần | Giây | Nó đến từ đâu | Giảm được bằng cách nào |
|---|---|---|---|
| Health-check detect floor | `15.0s` | `interval_s × threshold` trong `reports/health-events.jsonl:2` (`interval=5.0s, threshold=3`) | Giảm `interval` (xuống 2s) hoặc `threshold` (xuống 2), nhưng tăng rủi ro flapping do network jitter. |
| Snapshot restore | `0.0s` | `2_restore_snapshot` → `3_scale_pool` trong `reports/failover-events.jsonl:2` | Dùng volume snapshot cấp block storage hoặc streaming CDC thay vì periodic file copy. |
| GPU pool warm-up | `6.7s` | `waited_s` ở `4_wait_ready` trong `reports/failover-events.jsonl:4` | Giữ standby pool ở mức warm cao hơn (pre-warmed replicas, pre-loaded model weights trong RAM/VRAM). |
| DNS/LB TTL cache | `2.0s` | `t_recovered − t_cutover` (`30.2s - 28.2s`) tại `reports/drill-2-withdr.jsonl:35` | Giảm TTL phía client/proxy xuống 1s hoặc dùng Anycast routing / Cloud Load Balancer với health-checking chủ động. |
