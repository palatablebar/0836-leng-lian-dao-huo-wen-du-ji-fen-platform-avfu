"""校准容差登记、报告提交与批次重算的应用服务。"""
import hashlib
import json

from app.calibration.service import assess
from app.domain.helpers import D
from app.errors import DomainIssue
from app.intake.service import load


def _serialize(row):
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload.update(run_id=row["id"], status=row["status"], revision=row["revision"],
                   comment=row["comment"], created_at=row["created_at"])
    return payload


def _run_or_404(store, run_id):
    row = store.get(run_id)
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    return row


def _payload(row):
    return json.loads(row["payload"])


def register_tolerance(store, sensor_id, tolerance_text):
    sensor_id = (sensor_id or "").strip()
    if not sensor_id:
        raise DomainIssue("BAD_REQUEST")
    try:
        tolerance = D(tolerance_text, "BAD_TOLERANCE")
    except ValueError:
        raise DomainIssue("BAD_TOLERANCE")
    if tolerance < 0:
        raise DomainIssue("BAD_TOLERANCE")
    store.upsert_tolerance(sensor_id, tolerance)
    return {"sensor_id": sensor_id, "tolerance": str(tolerance)}


def list_tolerances(store):
    return [{"sensor_id": sensor_id, "tolerance": tolerance}
            for sensor_id, tolerance in sorted(store.tolerances().items())]


def _raw_rows(profile):
    return load(profile)["rows"]


def _sensors(payload, raw_rows):
    # 优先使用执行批次时固化的探针清单，缺失时回退到来源数据
    sensors = payload.get("sensors")
    if sensors:
        return list(sensors)
    return sorted({row.get("sensor_id", "") for row in raw_rows if row.get("sensor_id")})


def build_assessment(store, row):
    payload = _payload(row)
    raw_rows = _raw_rows(payload["profile"])
    sensors = _sensors(payload, raw_rows)
    tolerances = store.tolerances(sensors)
    reports = {item["sensor_id"]: D(item["measured_offset"], "BAD_OFFSET") for item in store.reports(row["id"])}
    return assess(raw_rows, sensors, tolerances, reports, row["status"])


def submit_report(store, run_id, sensor_id, measured_text):
    row = _run_or_404(store, run_id)
    sensor_id = (sensor_id or "").strip()
    if not sensor_id:
        raise DomainIssue("BAD_REQUEST")
    payload = _payload(row)
    raw_rows = _raw_rows(payload["profile"])
    sensors = _sensors(payload, raw_rows)
    if sensor_id not in sensors:
        raise DomainIssue("CALIBRATION_UNKNOWN_SENSOR", 404)
    try:
        measured = D(measured_text, "BAD_OFFSET")
    except ValueError:
        raise DomainIssue("BAD_OFFSET")

    digest = hashlib.sha256(
        json.dumps({"run_id": run_id, "sensor_id": sensor_id, "measured_offset": str(measured)},
                   ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    # 同一份报告重试：内容摘要一致，不新增版本
    if store.report_digest(run_id, sensor_id) == digest:
        changed = False
    else:
        changed = store.upsert_report(run_id, sensor_id, measured, digest)

    row = store.get(run_id)
    assessment = build_assessment(store, row)
    payload["calibration"] = assessment
    store.save_payload(run_id, payload)

    superseded = False
    if changed and assessment["complete"] and assessment["over_limit"] and row["status"] == "APPROVED":
        updated, problem = store.supersede(run_id)
        if problem is None:
            superseded = True
            row = updated
            assessment = build_assessment(store, row)
            payload = _payload(row)
            payload["calibration"] = assessment
            store.save_payload(run_id, payload)

    out = _serialize(store.get(run_id))
    out["calibration"] = assessment
    out["report_unchanged"] = not changed
    out["superseded"] = superseded
    return out


def current_assessment(store, run_id):
    row = _run_or_404(store, run_id)
    # 容差登记是全局可变的，每次读取都基于当前登记与报告重算
    assessment = build_assessment(store, row)
    return _serialize(row), assessment
