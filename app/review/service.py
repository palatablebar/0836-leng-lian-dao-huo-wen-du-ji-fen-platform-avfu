import json

from app.calibration.intake import build_assessment
from app.calibration.service import release_gate
from app.errors import DomainIssue
from app.review.policy import approval_allowed


def create_run(store, payload):
    row = store.create(payload["run_key"], payload["profile"], payload)
    return serialize(row)


def approve(store, run_id, decision, comment, expected_revision):
    row = store.get(run_id)
    if row is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if row["status"] == "SUPERSEDED":
        # 实测超限已停止凭旧结论放行，终态不可再签发，凭据仍可下载查验
        raise DomainIssue("CALIBRATION_HALTED", 409)
    payload = json.loads(row["payload"])
    if decision == "APPROVED":
        if not approval_allowed(payload):
            raise DomainIssue("GATE_BLOCKED", 409)
        # 校准闸门：报告到齐且实测超限、或容差未登记齐全时禁止签发
        assessment = build_assessment(store, row)
        allowed, reason = release_gate(assessment)
        if not allowed:
            raise DomainIssue(reason, 409)
    if decision not in {"APPROVED", "HELD"}:
        raise DomainIssue("BAD_REQUEST")
    row, problem = store.review(run_id, decision, comment.strip(), expected_revision)
    if problem == "missing":
        raise DomainIssue("RUN_NOT_FOUND", 404)
    if problem == "stale":
        raise DomainIssue("STALE_REVIEW", 409)
    return serialize(row)


def serialize(row):
    if row is None:
        return None
    payload = json.loads(row["payload"])
    payload.update(run_id=row["id"], status=row["status"], revision=row["revision"],
                   comment=row["comment"], created_at=row["created_at"])
    return payload
