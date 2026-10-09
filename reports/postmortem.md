# Postmortem — DR Drill Lab 23

Theo đúng template §4 "Sau Failover: Blameless Postmortem". Blameless: câu hỏi là
"hệ thống/process nào cho phép chuyện này", không phải "ai làm sai".

## 1. Timeline (mọi dòng phải có evidence path:line)

| ISO time | Sự kiện | Evidence |
|---|---|---|
| 2026-10-09T08:00:28 | outage bắt đầu (Region A bị netblock) | `chaos/chaos-events.jsonl:3` |
| 2026-10-09T08:00:30 | user đầu tiên bị ảnh hưởng (lỗi HTTP 503 / timeout) | `reports/drill-2-withdr.jsonl:24` |
| 2026-10-09T08:00:43 | health check alert (đạt threshold 3 lần fail liên tiếp) | `reports/health-events.jsonl:2` |
| 2026-10-09T08:00:49 | operator confirm cutover (bước 1 & 2 runbook hoàn tất) | `reports/runbook-run.jsonl:2` |
| 2026-10-09T08:00:58 | resolved (request đầu tiên OK từ region phụ B) | `reports/drill-2-withdr.jsonl:35` |

## 2. RTO/RPO đo được vs mục tiêu — gap ở bước nào?

- RTO mục tiêu: 300s · đo được: `30.2s` · gap: `-269.8s` (đạt chuẩn SLA và vượt mục tiêu)
- RPO mục tiêu: 300s · đo được: `8.0s` (`4` doc bị mất) · gap: `-292.0s` (nằm sâu trong ngưỡng an toàn)
- **Bước tốn nhiều giây nhất:** `Health check detection floor` (15.0s, chiếm 49.7% RTO) — xuất phát từ yêu cầu an toàn chống flapping cần 3 lần probe liên tiếp x 5.0s.

## 3. Root cause (5 whys)

1. *Tại sao user gặp lỗi 503/timeout?* Region A không phản hồi các kết nối TCP do bị cô lập mạng (netblock).
2. *Tại sao Region B không thay thế ngay lập tức?* Region B ở cấu hình warm standby: vector database chưa đồng bộ snapshot mới và pool chưa ở trạng thái `full`.
3. *Tại sao mất 15s mới phát hiện ra outage?* Health checker cần tích lũy đủ 3 lần fail liên tiếp (mỗi chu kỳ 5s) để loại trừ network jitter tạm thời.
4. *Tại sao mất 4 documents?* Replication định kỳ chạy mỗi 30s; sự cố xảy ra sau lần snapshot gần nhất 8s nên 4 docs vừa ingest trong 8s đó chưa được đưa lên replica store.
5. *Nếu đây là outage thật, bước nào trong runbook có nguy cơ thất bại cao nhất?* Bước `restore_snapshot` nếu dung lượng vector DB lên đến hàng trăm GB qua kết nối xuyên vùng, hoặc bước `scale_pool` nếu cụm GPU Region B không cấp phát đủ capacity tức thời.

## 4. Action items (có owner + deadline)

| # | Action item | Owner | Deadline | Giảm RTO/RPO bao nhiêu giây |
|---|---|---|---|---|
| 1 | Cấu hình Hot Standby GPU pool (pre-warmed model weights) tại Region B | SRE / ML Infra | 2026-11-01 | Giảm 6.7s GPU warm-up |
| 2 | Nâng cấp cơ chế vector sync sang continuous streaming CDC / WAL replication | Data Platform | 2026-11-15 | Giảm RPO từ 8.0s xuống < 1.0s |
| 3 | Tích hợp Anycast DNS / Global Server Load Balancer với active health probe | Network Team | 2026-11-20 | Giảm ~2.0s DNS TTL cache |

## 5. Ba câu hỏi bắt buộc trả lời

1. `interval × threshold` của hệ thống là **15.0 giây** (5.0s × 3). Nó chiếm **49.7%** tổng RTO đo được (15.0s / 30.2s).
2. Nếu hạ interval xuống 1s, RTO sẽ giảm được **12 giây** (từ 15s xuống 3s). Cái giá phải trả là nguy cơ **flapping** rất cao: khi mạng công cộng hoặc upstream có jitter ngắn 2-3s, hệ thống sẽ vội vã chuyển vùng sai, gây gián đoạn kép không cần thiết cho khách hàng.
3. Nếu outage kéo dài 6 giờ và region chính mất vĩnh viễn, 4 documents bị mất đồng nghĩa với 4 giao dịch/yêu cầu người dùng trong 8 giây cuối cùng bị mất ngữ cảnh tìm kiếm. Hệ thống cần bổ sung Write-Ahead Log hoặc Dead-Letter Queue ở tầng API Gateway để có thể replay lại dữ liệu khi restore.
