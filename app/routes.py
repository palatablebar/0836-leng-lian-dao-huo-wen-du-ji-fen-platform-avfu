from flask import Blueprint, abort, jsonify, request, send_file

from app.calibration.intake import (build_assessment, current_assessment,
                                    list_tolerances, register_tolerance,
                                    submit_report)
from app.catalog import SPEC
from app.config import SAMPLES
from app.errors import DomainIssue
from app.evidence.render import render
from app.review.service import approve, create_run, serialize
from app.service import pipeline


api = Blueprint("api", __name__)
STAGE_INDEX = {"intake": 1, "prepare": 2, "calculate": 3, "decision": 4, "reconcile": 5}


def store():
    from flask import current_app
    return current_app.extensions["runs"]


@api.get("/api/catalog")
def catalog():
    return jsonify(code=SPEC["code"], name=SPEC["name"], actor=SPEC["actor"], rule=SPEC["rule"],
                   rule_short=SPEC["rule_short"],
                   stages=[{"id": item, "name": name} for item, name in zip(
                       ["intake", "prepare", "calculate", "decision", "reconcile", "review", "evidence"],
                       SPEC["stages"])],
                   chart=SPEC["chart"], result_columns=SPEC["result_columns"],
                   columns=SPEC["columns"], samples=["dirty", "clean"])


@api.post("/api/stages/<stage_id>")
def stage(stage_id):
    if stage_id not in STAGE_INDEX:
        raise DomainIssue("STAGE_UNKNOWN", 404)
    data = request.get_json(silent=True) or {}
    profile = data.get("profile", "dirty")
    upto = SPEC["stages"][STAGE_INDEX[stage_id] - 1]
    return jsonify(pipeline(profile, upto=upto))


@api.post("/api/runs")
def create():
    data = request.get_json(silent=True) or {}
    profile = data.get("profile", "dirty")
    payload = pipeline(profile)
    return jsonify(create_run(store(), payload))


@api.get("/api/runs/<run_id>")
def get_run(run_id):
    run, assessment = current_assessment(store(), run_id)
    run["calibration"] = assessment
    return jsonify(run)


@api.post("/api/runs/<run_id>/review")
def review(run_id):
    data = request.get_json(silent=True) or {}
    if "decision" not in data or "expected_revision" not in data:
        raise DomainIssue("BAD_REQUEST")
    run = approve(store(), run_id, data["decision"], data.get("comment", ""), int(data["expected_revision"]))
    run["calibration"] = build_assessment(store(), store().get(run_id))
    return jsonify(run)


@api.get("/api/runs/<run_id>/evidence")
def evidence(run_id):
    run = serialize(store().get(run_id))
    return jsonify(render(run))


@api.get("/api/tolerances")
def tolerances():
    return jsonify(items=list_tolerances(store()))


@api.post("/api/tolerances")
def upsert_tolerance():
    data = request.get_json(silent=True) or {}
    if "sensor_id" not in data or "tolerance" not in data:
        raise DomainIssue("BAD_REQUEST")
    return jsonify(register_tolerance(store(), str(data["sensor_id"]), data["tolerance"]))


@api.post("/api/runs/<run_id>/calibration")
def calibration(run_id):
    data = request.get_json(silent=True) or {}
    if "sensor_id" not in data or "measured_offset" not in data:
        raise DomainIssue("BAD_REQUEST")
    return jsonify(submit_report(store(), run_id, str(data["sensor_id"]), data["measured_offset"]))


@api.get("/api/runs/<run_id>/calibration")
def calibration_status(run_id):
    run, assessment = current_assessment(store(), run_id)
    return jsonify(run_id=run_id, status=run["status"], revision=run["revision"], calibration=assessment)


@api.get("/api/examples/<profile>")
def example(profile):
    if profile not in {"clean", "dirty"}:
        abort(404)
    return send_file(SAMPLES / f"{profile}.csv", as_attachment=True)
