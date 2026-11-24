"""校准记录晚到场景下的批次重算与放行评估。

- 校准未齐：每个探针必须有允许误差（容差）登记；未收到报告的探针按最坏情况
  （真实温度上浮一个容差）重算，全部达标才允许临时放行。
- 报告到齐：用实测偏差重算，按现行判定规则给出确认结论；超限即停止凭旧结论放行。
"""
from decimal import Decimal

from app.domain.calculate import calculate_rows
from app.domain.decision import decide_rows
from app.domain.helpers import D
from app.domain.prepare import prepare_rows

# 批次当前放行结果（工作台展示口径）
NO_CALIBRATION = "NO_CALIBRATION"        # 尚未登记任何校准报告
TOLERANCE_MISSING = "TOLERANCE_MISSING"  # 校准未齐且存在未登记容差的探针
PROVISIONAL_OK = "PROVISIONAL_OK"        # 校准未齐，最坏包络达标，可临时放行
PROVISIONAL = "PROVISIONAL"              # 已凭临时结论签发
CONFIRMED = "CONFIRMED"                  # 报告到齐且实测达标
BLOCKED = "BLOCKED"                      # 实测或包络判定超限，停止放行

RELEASE_LABELS = {
    NO_CALIBRATION: "未收到校准报告",
    TOLERANCE_MISSING: "容差未登记齐全",
    PROVISIONAL_OK: "可临时放行",
    PROVISIONAL: "临时放行（待校准到齐）",
    CONFIRMED: "已确认放行",
    BLOCKED: "已停止放行",
}


def _recompute(raw_rows, offset_overrides):
    """用给定的探针偏差覆盖值重新走整理、计算与判定。"""
    rows = []
    for item in raw_rows:
        copied = dict(item)
        sensor_id = copied.get("sensor_id", "")
        if sensor_id in offset_overrides:
            copied["probe_offset"] = str(offset_overrides[sensor_id])
        rows.append(copied)
    prepared, prepare_issues = prepare_rows(rows)
    results = decide_rows(calculate_rows(prepared))
    return results, prepare_issues


def _summary(results):
    summary = {"PASS": 0, "REVIEW": 0, "REJECT": 0}
    for item in results:
        summary[item.get("verdict", "REVIEW")] = summary.get(item.get("verdict", "REVIEW"), 0) + 1
    return summary


def _serializable_results(results):
    out = []
    for item in results:
        out.append({
            "label": item.get("label", ""),
            "verdict": item.get("verdict", ""),
            "reason": item.get("reason", ""),
            "mkt": float(item["mkt"]) if item.get("mkt") is not None else None,
            "max_c": float(item["max_c"]) if item.get("max_c") is not None else None,
            "minutes": float(item["minutes"]) if item.get("minutes") is not None else None,
        })
    return out


def assess(raw_rows, sensors, tolerances, reports, review_status):
    """计算批次当前的校准评估与放行结果。

    tolerances: {sensor_id: Decimal}，已登记的允许误差（非负）。
    reports:    {sensor_id: Decimal}，已到齐的实测偏差（读数减校准参考值）。
    """
    reported = sorted(reports)
    missing_reports = [sensor_id for sensor_id in sensors if sensor_id not in reports]
    complete = not missing_reports
    tolerance_map = {sensor_id: D(value, "BAD_TOLERANCE") for sensor_id, value in tolerances.items()}

    if complete:
        mode = "MEASURED"
        results, issues = _recompute(raw_rows, {sensor_id: reports[sensor_id] for sensor_id in sensors})
        missing_tolerances = []
        envelope = None
    elif not reports:
        # 尚无校准活动：沿用批次原判定，不启用容差闸门
        mode = "ENVELOPE"
        results, issues = [], []
        missing_tolerances = []
        envelope = None
    else:
        mode = "ENVELOPE"
        missing_tolerances = [sensor_id for sensor_id in missing_reports if sensor_id not in tolerance_map]
        if missing_tolerances:
            results, issues = [], []
            envelope = None
        else:
            overrides = {}
            for sensor_id in sensors:
                if sensor_id in reports:
                    overrides[sensor_id] = reports[sensor_id]
                else:
                    # 最坏情况：偏差往负方向偏一个容差，真实温度 = 读数 - 偏差，上浮一个容差
                    declared = next((row.get("probe_offset") for row in raw_rows
                                    if row.get("sensor_id") == sensor_id), "0")
                    try:
                        base = D(declared, "BAD_OFFSET")
                    except ValueError:
                        base = Decimal("0")
                    overrides[sensor_id] = base - abs(tolerance_map[sensor_id])
            results, issues = _recompute(raw_rows, overrides)
            envelope = {
                "sensor_id": missing_reports,
                "assumed_offset": {sensor_id: str(overrides[sensor_id]) for sensor_id in missing_reports},
            }

    summary = _summary(results)
    over_limit = summary.get("REJECT", 0) > 0

    if complete:
        release = BLOCKED if over_limit else CONFIRMED
    elif missing_tolerances:
        release = TOLERANCE_MISSING
    elif not reports:
        release = NO_CALIBRATION
    else:
        release = BLOCKED if over_limit else PROVISIONAL_OK

    # 已签发状态覆盖展示口径：临时签发后保持“临时放行”，实测超限后为“已停止放行”
    if review_status == "APPROVED":
        if complete and over_limit:
            release = BLOCKED
        elif not complete and not missing_tolerances:
            release = PROVISIONAL
        elif complete:
            release = CONFIRMED
    elif review_status == "SUPERSEDED":
        release = BLOCKED

    return {
        "mode": mode,
        "complete": complete,
        "release_result": release,
        "release_label": RELEASE_LABELS[release],
        "reported_sensors": reported,
        "missing_reports": missing_reports,
        "missing_tolerances": missing_tolerances,
        "tolerances": {sensor_id: str(tolerance_map[sensor_id])
                       for sensor_id in sorted(set(sensors) & set(tolerance_map))},
        "measured_offsets": {sensor_id: str(reports[sensor_id]) for sensor_id in reported},
        "envelope": envelope,
        "summary": summary,
        "results": _serializable_results(results),
        "prepare_issues": list(issues),
        "over_limit": over_limit,
    }


def release_gate(assessment):
    """签发闸门：返回 (允许签发, 原因码)。

    无任何校准报告时沿用批次原判定；一旦开始接收校准报告，未齐前要求
    容差登记齐全且最坏包络达标（临时放行），到齐后要求实测达标。
    """
    if not assessment["reported_sensors"]:
        return True, None
    if assessment["complete"]:
        if assessment["over_limit"]:
            return False, "CALIBRATION_OVER_LIMIT"
        return True, None
    if assessment["missing_tolerances"]:
        return False, "TOLERANCE_NOT_REGISTERED"
    if assessment["over_limit"]:
        return False, "CALIBRATION_ENVELOPE_OVER_LIMIT"
    return True, "PROVISIONAL"
