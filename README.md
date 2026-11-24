# 冷链到货温度积分台

冷链质量员处理MKT 积分与温区偏离的本地工作台。样例、规则和复核记录都在项目内，不依赖外部服务。

## 启动

```bash
docker compose up --build
```

打开 `http://127.0.0.1:${PORT:-18520}`。默认端口见 `docker-compose.yml`。

## 验证

```bash
docker compose exec -T app pytest -q
docker compose config --quiet
```

## 操作

1. 在左侧选阶段，查看采信、整理、计算、判定和对账结果。
2. 选择 `dirty` 样例观察坏行和隔离原因。
3. 换 `clean` 样例执行批次，填写复核意见后签发。
4. 下载证据 JSON，核对来源摘要、指标和签发版本。
5. 在「校准与放行结果」面板登记探针允许误差、逐探针提交校准报告：报告未齐时按容差最坏包络决定能否临时放行，报告到齐后用实测偏差重算，超限即停止凭旧结论放行，已签发凭据仍可下载；同一份报告重试不会新增版本。

业务规则见 `docs/BUSINESS-RULES.md`，字段定义见 `docs/DATA-DICTIONARY.md`。
