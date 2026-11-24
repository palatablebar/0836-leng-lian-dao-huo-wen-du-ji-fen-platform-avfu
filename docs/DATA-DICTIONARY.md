# 字段定义

| 字段 | 类型 | 说明 |
|---|---|---|
| `batch_id` | text | 业务字段 |
| `sensor_id` | text | 业务字段 |
| `segment_start` | datetime | 主键 |
| `segment_end` | datetime | 业务字段 |
| `temp_c` | decimal | 业务字段 |
| `unit` | text | 业务字段 |
| `probe_offset` | decimal_optional | 业务字段 |

空字符串、`-`、`NA`、`null` 和 `未提供` 按空值处理。金额字段在整理层转为整数分或整数最小单位；日期按 ISO 日期解析；带时间的字段按本地时间解析。标识字段保持为文本，前导零不会被去除。

## 校准登记

| 字段 | 类型 | 说明 |
|---|---|---|
| `sensor_id` | text | 探针标识，须属于批次内探针 |
| `tolerance` | decimal | 允许误差（非负），校准未齐时按最坏包络评估 |
| `measured_offset` | decimal | 实测探针偏差，定义为读数减校准参考值 |

`probe_tolerances` 按探针全局登记；`calibration_reports` 按批次与探针保存实测偏差及内容摘要，摘要一致的重复提交不新增版本。
