from flask import jsonify


MESSAGES = {
    "EMPTY_FILE": "文件为空",
    "BLANK_FILE": "文件只有空白",
    "HEADER_ONLY": "文件只有表头",
    "HEADER_MISMATCH": "表头与本项目字段不一致",
    "UNCLOSED_QUOTE": "引号未闭合，文件已拒收",
    "TOO_MANY_ROWS": "数据行超过上限",
    "FILE_TOO_LARGE": "文件超过大小上限",
    "KEY_MISSING": "主键为空",
    "CONFLICT_DUPLICATE": "同一键存在冲突内容",
    "SAMPLE_UNKNOWN": "样例不存在",
    "STAGE_UNKNOWN": "阶段不存在",
    "RUN_NOT_FOUND": "批次不存在",
    "STALE_REVIEW": "批次已被更新，请刷新后复核",
    "GATE_BLOCKED": "存在阻断项，不能签发",
    "NOT_APPROVED": "批次尚未签发",
    "BAD_REQUEST": "请求内容不完整",
    "BAD_TOLERANCE": "允许误差必须为非负数值",
    "BAD_OFFSET": "探针偏差必须为数值",
    "TOLERANCE_NOT_REGISTERED": "存在未登记允许误差的探针，不能临时放行",
    "CALIBRATION_OVER_LIMIT": "实测偏差重算后温区超限，停止放行",
    "CALIBRATION_HALTED": "批次已停止凭旧结论放行，不能再签发",
    "CALIBRATION_ENVELOPE_OVER_LIMIT": "允许误差包络内存在超限情形，不能临时放行",
    "CALIBRATION_UNKNOWN_SENSOR": "该探针不属于本批次",
}


class DomainIssue(Exception):
    def __init__(self, code: str, status: int = 400, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail
        super().__init__(code)


def error_response(exc: DomainIssue):
    return jsonify(error=exc.detail or MESSAGES.get(exc.code, "请求无法处理"), code=exc.code), exc.status
