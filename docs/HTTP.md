# 接口

- `GET /`：工作台。
- `GET /api/catalog`：阶段、字段和样例。
- `POST /api/stages/{stage}`：按阶段返回处理结果。
- `POST /api/runs`：执行完整批次并保存草稿。
- `GET /api/runs/{id}`：读取批次，含当前校准评估 `calibration`。
- `POST /api/runs/{id}/review`：签发或暂缓，提交 `decision`、`comment`、`expected_revision`。
- `GET /api/runs/{id}/evidence`：下载已签发证据（`SUPERSEDED` 批次仍可下载）。
- `GET /api/runs/{id}/calibration`：读取当前校准评估与放行结果。
- `POST /api/runs/{id}/calibration`：提交单探针校准报告，字段 `sensor_id`、`measured_offset`；同内容重试不新增版本。
- `GET /api/tolerances`：列出已登记的探针允许误差。
- `POST /api/tolerances`：登记或更新允许误差，字段 `sensor_id`、`tolerance`（非负数值）。
- `GET /api/examples/{profile}`：下载样例。
- `GET /healthz`：健康检查。
