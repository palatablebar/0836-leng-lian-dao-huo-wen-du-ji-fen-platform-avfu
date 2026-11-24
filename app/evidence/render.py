from app.errors import DomainIssue
from app.evidence.manifest import stable_digest


def render(run):
    if run is None:
        raise DomainIssue("RUN_NOT_FOUND", 404)
    # 已签发凭据永久可下载：实测超限停止放行后，旧凭据仍可查验
    if run["status"] not in {"APPROVED", "SUPERSEDED"}:
        raise DomainIssue("NOT_APPROVED", 409)
    artifact = {
        "schema": "workbench-evidence/v1",
        "run_id": run["run_id"],
        "project": run["project"],
        "rule": run["rule"],
        "profile": run["profile"],
        "source": run["source"],
        "counts": run["counts"],
        "ledger": run["ledger"],
        "summary": run["summary"],
        "review": {"status": run["status"], "revision": run["revision"], "comment": run["comment"]},
    }
    if run.get("calibration"):
        artifact["calibration"] = {
            "release_result": run["calibration"]["release_result"],
            "release_label": run["calibration"]["release_label"],
            "mode": run["calibration"]["mode"],
            "complete": run["calibration"]["complete"],
            "reported_sensors": run["calibration"]["reported_sensors"],
            "measured_offsets": run["calibration"]["measured_offsets"],
            "tolerances": run["calibration"]["tolerances"],
            "summary": run["calibration"]["summary"],
        }
    artifact["artifact_sha256"] = stable_digest(artifact)
    return artifact
