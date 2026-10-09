# Runbook 1 trang — Region chính down

Runbook phải chạy được lúc 3h sáng bởi người KHÔNG viết nó. Mỗi bước: lệnh copy-paste
được + cách biết bước đó xong.

| # | Bước | Lệnh | Biết là xong khi | Ai làm |
|---|---|---|---|---|
| 1 | Xác nhận outage | `python chaos/kill_region.py status` | `a.alive=false` hoặc HTTP 503/timeout 3 lần liên tiếp; region b alive | On-call SRE |
| 2 | Mở incident + bấm giờ RTO | `python dr/runbook.py --primary a --target b --backend fs --auto` | Incident ID được tạo và mốc thời gian ghi vào `reports/runbook-run.jsonl:2` | Incident Commander |
| 3 | Restore state ở region phụ | `python state/snapshot.py get --region b --backend fs` | Snapshot manifest tải về thành công; log ghi nhận `rpo_seconds` và `docs_lost` tại `reports/failover-events.jsonl:2` | Data Platform / SRE |
| 4 | Scale pool warm→full | `echo full > state/region-b/pool_state` | Endpoint `curl -s http://127.0.0.1:8002/readyz` trả HTTP 200 (`ready:true`) sau 6s warmup | Inference Engineer |
| 5 | DNS/LB cutover | `echo b > edge/active_region` | `curl -s http://127.0.0.1:8088/edge/state` trả về `"active_region":"b"` | Traffic / SRE |
| 6 | Verify golden signals | `python -c "import httpx; print([httpx.get('http://127.0.0.1:8002/v1/infer').status_code for _ in range(10)])"` | 10 request trả HTTP 200; p95 < 50ms, error rate = 0% | On-call SRE |
| 7 | Đo RTO + postmortem | `python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | Output JSON có `"rto_verdict":"PASS"`, RTO ≤ 300s | Incident Commander |

## Điều kiện Rollback (Failover ngược về Region A)

1. **Điều kiện kỹ thuật:**
   - Region A đã phục hồi ổn định, endpoint `/readyz` trả HTTP 200 liên tục trong tối thiểu 15 phút.
   - Hoàn tất đồng bộ dữ liệu ngược chiều (Reverse Replication): mọi vector docs mới được ghi nhận tại Region B trong thời gian outage phải được replicate an toàn về Region A trước khi trỏ traffic.
   - Sức chứa (capacity) và GPU pool tại Region A được kiểm tra đảm bảo 100% tài nguyên sẵn sàng.

2. **Thẩm quyền quyết định:**
   - Phải được phê duyệt bởi **Incident Commander (IC)** và **Head of Infrastructure / Lead SRE**.
   - Tuyệt đối **KHÔNG** kích hoạt auto-rollback hoàn toàn tự động để tránh hiện tượng flapping 2 chiều liên tục giữa các region khi mạng chập chờn (§4 Anti-Patterns).
