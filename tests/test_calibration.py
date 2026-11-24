"""校准记录晚到场景的端到端规则测试。"""
from app.calibration.service import (BLOCKED, CONFIRMED, NO_CALIBRATION,
                                     PROVISIONAL, PROVISIONAL_OK,
                                     TOLERANCE_MISSING, assess, release_gate)
from app.domain.helpers import D
from app.intake.service import load


def create_run(client, profile="clean"):
    response = client.post("/api/runs", json={"profile": profile})
    assert response.status_code == 200
    return response.get_json()


def register(client, sensor_id, tolerance):
    return client.post("/api/tolerances", json={"sensor_id": sensor_id, "tolerance": tolerance})


def report(client, run_id, sensor_id, offset):
    return client.post(f"/api/runs/{run_id}/calibration",
                       json={"sensor_id": sensor_id, "measured_offset": offset})


def status(client, run_id):
    return client.get(f"/api/runs/{run_id}/calibration").get_json()["calibration"]


def approve(client, run_id, revision, decision="APPROVED", comment="核验"):
    return client.post(f"/api/runs/{run_id}/review",
                       json={"decision": decision, "comment": comment, "expected_revision": revision})


# ---------- 容差登记 ----------

def test_tolerance_can_be_registered_and_listed(client):
    response = register(client, "S01", "0.1")
    assert response.status_code == 200
    assert response.get_json() == {"sensor_id": "S01", "tolerance": "0.1"}
    items = client.get("/api/tolerances").get_json()["items"]
    assert {"sensor_id": "S01", "tolerance": "0.1"} in items


def test_tolerance_rejects_negative_and_non_numeric(client):
    assert register(client, "S01", "-0.1").get_json()["code"] == "BAD_TOLERANCE"
    assert register(client, "S01", "abc").get_json()["code"] == "BAD_TOLERANCE"
    assert client.post("/api/tolerances", json={"sensor_id": "S01"}).status_code == 400


def test_tolerance_zero_is_allowed(client):
    assert register(client, "S01", "0").status_code == 200


# ---------- 校准未齐：容差闸门 ----------

def test_no_report_keeps_original_release_path(client):
    run = create_run(client)
    cal = status(client, run["run_id"])
    assert cal["release_result"] == NO_CALIBRATION
    assert cal["mode"] == "ENVELOPE"
    assert cal["complete"] is False
    # 没有校准活动时沿用原规则，可直接签发
    response = approve(client, run["run_id"], 0)
    assert response.status_code == 200


def test_missing_tolerance_blocks_provisional_release(client):
    run = create_run(client)
    report(client, run["run_id"], "S01", "0")
    cal = status(client, run["run_id"])
    assert cal["release_result"] == TOLERANCE_MISSING
    assert set(cal["missing_tolerances"]) == {"S02", "S03"}
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = approve(client, run["run_id"], revision)
    assert response.status_code == 409
    assert response.get_json()["code"] == "TOLERANCE_NOT_REGISTERED"


def test_envelope_over_limit_blocks_provisional_release(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0.2")
    report(client, run["run_id"], "S01", "0")
    cal = status(client, run["run_id"])
    # B003 标称 MKT 恰为 8.0，最坏包络上浮 0.2 后超限
    assert cal["over_limit"] is True
    assert cal["release_result"] == BLOCKED
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = approve(client, run["run_id"], revision)
    assert response.status_code == 409
    assert response.get_json()["code"] == "CALIBRATION_ENVELOPE_OVER_LIMIT"


def test_envelope_within_range_allows_provisional_release(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0")
    report(client, run["run_id"], "S01", "0")
    cal = status(client, run["run_id"])
    assert cal["release_result"] == PROVISIONAL_OK
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = approve(client, run["run_id"], revision)
    assert response.status_code == 200
    after = status(client, run["run_id"])
    assert after["release_result"] == PROVISIONAL


# ---------- 报告到齐：实测重算 ----------

def test_complete_reports_confirm_release(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0.1")
    for sid, offset in (("S01", "0"), ("S02", "0.2"), ("S03", "0")):
        report(client, run["run_id"], sid, offset)
    cal = status(client, run["run_id"])
    assert cal["complete"] is True
    assert cal["mode"] == "MEASURED"
    assert cal["release_result"] == CONFIRMED
    assert cal["over_limit"] is False
    assert cal["summary"] == {"PASS": 3, "REVIEW": 0, "REJECT": 0}


def test_complete_reports_over_limit_blocks_unapproved_run(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0.5")
    for sid, offset in (("S01", "0"), ("S02", "0.2"), ("S03", "-0.3")):
        report(client, run["run_id"], sid, offset)
    cal = status(client, run["run_id"])
    assert cal["release_result"] == BLOCKED
    assert cal["over_limit"] is True
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = approve(client, run["run_id"], revision)
    assert response.status_code == 409
    assert response.get_json()["code"] == "CALIBRATION_OVER_LIMIT"


def test_late_over_limit_report_supersedes_approved_run_but_keeps_evidence(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0")
    report(client, run["run_id"], "S01", "0")
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    approve(client, run["run_id"], revision)
    # 临时放行期间凭据可下载
    assert client.get(f"/api/runs/{run['run_id']}/evidence").status_code == 200

    report(client, run["run_id"], "S02", "0.2")
    final = report(client, run["run_id"], "S03", "-0.3").get_json()
    assert final["superseded"] is True
    assert final["status"] == "SUPERSEDED"
    assert final["calibration"]["release_result"] == BLOCKED

    # 已签发凭据仍可下载查验，且记录停止放行状态
    evidence = client.get(f"/api/runs/{run['run_id']}/evidence")
    assert evidence.status_code == 200
    artifact = evidence.get_json()
    assert artifact["review"]["status"] == "SUPERSEDED"
    assert artifact["calibration"]["release_result"] == BLOCKED

    # 停止放行后不能再次签发（终态，即使后续报告修正也不重新放行）
    latest = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = approve(client, run["run_id"], latest)
    assert response.status_code == 409
    assert response.get_json()["code"] == "CALIBRATION_HALTED"
    # 修正后的合格报告仍可登记，但不解除终态
    report(client, run["run_id"], "S03", "0")
    response = approve(client, run["run_id"], latest + 1)
    assert response.status_code == 409
    assert response.get_json()["code"] == "CALIBRATION_HALTED"
    # 凭据依然可下载
    assert client.get(f"/api/runs/{run['run_id']}/evidence").status_code == 200


def test_complete_conforming_reports_keep_approved_run_confirmed(client):
    run = create_run(client)
    for sid in run["sensors"]:
        register(client, sid, "0")
    report(client, run["run_id"], "S01", "0")
    revision = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    approve(client, run["run_id"], revision)
    report(client, run["run_id"], "S02", "0.2")
    final = report(client, run["run_id"], "S03", "0").get_json()
    assert final["status"] == "APPROVED"
    assert final["calibration"]["release_result"] == CONFIRMED
    assert client.get(f"/api/runs/{run['run_id']}/evidence").status_code == 200


# ---------- 幂等：同一份报告重试不新增版本 ----------

def test_identical_report_retry_does_not_bump_revision(client):
    run = create_run(client)
    first = report(client, run["run_id"], "S01", "0.15").get_json()
    assert first["report_unchanged"] is False
    revision_after_first = first["revision"]
    second = report(client, run["run_id"], "S01", "0.15").get_json()
    assert second["report_unchanged"] is True
    assert second["revision"] == revision_after_first
    third = report(client, run["run_id"], "S01", "0.15").get_json()
    assert third["revision"] == revision_after_first


def test_changed_report_content_bumps_revision(client):
    run = create_run(client)
    report(client, run["run_id"], "S01", "0.15")
    before = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    response = report(client, run["run_id"], "S01", "0.16")
    assert response.get_json()["report_unchanged"] is False
    after = client.get(f"/api/runs/{run['run_id']}").get_json()["revision"]
    assert after == before + 1


# ---------- 输入校验 ----------

def test_report_unknown_sensor_is_rejected(client):
    run = create_run(client)
    response = report(client, run["run_id"], "S99", "0")
    assert response.status_code == 404
    assert response.get_json()["code"] == "CALIBRATION_UNKNOWN_SENSOR"


def test_report_bad_offset_is_rejected(client):
    run = create_run(client)
    response = report(client, run["run_id"], "S01", "n/a")
    assert response.status_code == 400
    assert response.get_json()["code"] == "BAD_OFFSET"


def test_report_on_missing_run_returns_404(client):
    response = client.post("/api/runs/ghost/calibration", json={"sensor_id": "S01", "measured_offset": "0"})
    assert response.status_code == 404


# ---------- 领域单元：包络与实测 ----------

def _clean_inputs():
    raw = load("clean")["rows"]
    sensors = sorted({row["sensor_id"] for row in raw})
    return raw, sensors


def test_envelope_assumes_worst_case_for_unreported_sensors():
    raw, sensors = _clean_inputs()
    assessment = assess(raw, sensors, {sid: D("0.2") for sid in sensors},
                        {"S01": D("0")}, "DRAFT")
    assert assessment["mode"] == "ENVELOPE"
    # 未报告探针的假定偏差 = 声明偏差 - 容差
    assert assessment["envelope"]["assumed_offset"]["S03"] == "-0.2"
    # S02 声明偏差 0.2，最坏假定为 0.0
    assert assessment["envelope"]["assumed_offset"]["S02"] == "0.0"
    assert assessment["over_limit"] is True


def test_measured_mode_uses_reported_offsets_for_every_sensor():
    raw, sensors = _clean_inputs()
    reports = {"S01": D("0"), "S02": D("0.2"), "S03": D("-0.3")}
    assessment = assess(raw, sensors, {sid: D("0.5") for sid in sensors}, reports, "DRAFT")
    assert assessment["mode"] == "MEASURED"
    assert assessment["complete"] is True
    assert assessment["measured_offsets"]["S03"] == "-0.3"
    assert assessment["over_limit"] is True


def test_release_gate_rules():
    raw, sensors = _clean_inputs()
    idle = assess(raw, sensors, {}, {}, "DRAFT")
    assert release_gate(idle) == (True, None)

    missing = assess(raw, sensors, {"S01": D("0.1")}, {"S01": D("0")}, "DRAFT")
    allowed, reason = release_gate(missing)
    assert allowed is False and reason == "TOLERANCE_NOT_REGISTERED"

    envelope_ok = assess(raw, sensors, {sid: D("0") for sid in sensors}, {"S01": D("0")}, "DRAFT")
    assert release_gate(envelope_ok) == (True, "PROVISIONAL")

    measured_bad = assess(raw, sensors, {sid: D("1") for sid in sensors},
                          {"S01": D("0"), "S02": D("0.2"), "S03": D("-0.5")}, "DRAFT")
    allowed, reason = release_gate(measured_bad)
    assert allowed is False and reason == "CALIBRATION_OVER_LIMIT"


def test_superseded_status_is_always_blocked_release():
    raw, sensors = _clean_inputs()
    reports = {sid: D("0") for sid in sensors}
    assessment = assess(raw, sensors, {sid: D("0.1") for sid in sensors}, reports, "SUPERSEDED")
    assert assessment["release_result"] == BLOCKED
