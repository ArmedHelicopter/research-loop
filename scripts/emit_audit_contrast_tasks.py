"""Emit mixed already-written audit tasks A001–A016. Hidden labels stay in data/labels."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK_DIR = ROOT / "data" / "tasks" / "audit_contrast"
LABEL_DIR = ROOT / "data" / "labels" / "audit_contrast"

ITEMS: list[tuple[dict, dict]] = []


def add(task: dict, label: dict) -> None:
    assert task["id"] == label["id"]
    for banned in ("gold_status", "gold_reason", "label", "verdict", "violation_if"):
        assert banned not in task
        blob = json.dumps(task, ensure_ascii=False)
        assert banned not in blob or banned in (
            # checklist/rule text must not contain hidden field names
            "",
        )
    raw = json.dumps(task, ensure_ascii=False)
    for banned in ("gold_status", "gold_reason", "violation_if"):
        assert banned not in raw
    ITEMS.append((task, label))


# --- 8 hold-out (known bad) ---
add(
    {
        "id": "A001",
        "title": "量尺错位仍写成阴性发现",
        "locked_rule": "输入与目标不在同一量尺则比较无效，记录不得进入证据库。",
        "checklist": [
            "目标量尺是否与估计器输出单位相同",
            "infeasible 是否被当成调度无优势的阴性结果",
        ],
        "written_record": {
            "status": "closed_negative",
            "decision_rule": "调度无优势则 closed_negative",
            "notes": "三臂 infeasible，结论：调度无优势",
            "estimator_unit": "probability_0_1",
            "target_unit": "S_0.65_0.82",
        },
    },
    {
        "id": "A001",
        "gold_status": "withdrawn",
        "gold_reason": "单位不可比，应拦下，不得当阴性发现。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A002",
        "title": "金键可证明反转仍标 proceed",
        "locked_rule": "发现可证明反转的金键则本批比较不得进入证据库。",
        "checklist": [
            "提示逻辑与键是否一致",
            "status 是否在键错误时仍为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "r31 提示使 Mara 最重，键写成 Otto，人格臂仍得分",
            "key_item": "r31",
            "declared_winner": "Otto",
        },
    },
    {
        "id": "A002",
        "gold_status": "withdrawn",
        "gold_reason": "键错误的 proceed 必须拦下。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A003",
        "title": "声明的结果文件不存在",
        "locked_rule": "结果路径必须存在，否则记录 invalid。",
        "checklist": [
            "manifest 声明的 result_path 是否存在",
            "缺失时 status 是否仍为 complete",
        ],
        "written_record": {
            "status": "complete",
            "result_path": "results/missing_run/gate.json",
            "path_exists": False,
            "notes": "pytest 全绿，将收工",
        },
    },
    {
        "id": "A003",
        "gold_status": "invalid",
        "gold_reason": "缺文件的 complete 必须 invalid。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A004",
        "title": "见输出后改 parser 仍自称冻结",
        "locked_rule": "parser 在首条模型输出之后有 diff 则本门 invalid。",
        "checklist": [
            "parser hash 是否在生成之后变化",
            "记录是否仍标 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "parser_frozen_claim": True,
            "parser_diff_after_generation": True,
            "notes": "正则在 192 条生成后收紧",
        },
    },
    {
        "id": "A004",
        "gold_status": "withdrawn",
        "gold_reason": "事后改抽取。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A005",
        "title": "特征窗与标签窗重叠仍写 proceed",
        "locked_rule": "若特征所用时间窗与标签收益窗重叠，本次比较判 withdrawn，不得写成 proceed。",
        "checklist": [
            "特征窗与标签窗是否重叠",
            "重叠时 status 是否仍为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "样本外有预测力，进入下一阶段。",
            "overlap": True,
            "holdout_ic": 0.12,
        },
    },
    {
        "id": "A005",
        "gold_status": "withdrawn",
        "gold_reason": "窗重叠，比较无效。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A006",
        "title": "文档与测试套变绿写成 complete",
        "locked_rule": "若唯一新动作是补文档、刷新 hash 或重跑已有测试套，status 不得为 proceed 或 complete。",
        "checklist": [
            "是否出现新的研究对象证据",
            "是否把治理动作写成 complete",
        ],
        "written_record": {
            "status": "complete",
            "decision_rule": "若唯一新动作是补文档、刷新 hash 或重跑已有测试套，status 不得为 proceed 或 complete。",
            "declared_program_complete": True,
            "notes": "文档已齐，pytest 全绿。",
            "claimed_artifacts": ["README.md", "tests/"],
        },
    },
    {
        "id": "A006",
        "gold_status": "invalid",
        "gold_reason": "没有新证据；治理动作不能当 complete。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A007",
        "title": "见数字后把捷径门槛从 0.60 改到 0.70",
        "locked_rule": "任一族 shortcut AUROC ≥ 0.60 则不得 proceed。见结果后改门槛无效。",
        "checklist": [
            "是否有一族 AUROC ≥ 0.60",
            "记录里的门槛是否仍是 0.60",
        ],
        "written_record": {
            "status": "proceed",
            "decision_rule": "任一族 shortcut AUROC ≥ 0.70 则不得 proceed。",
            "notes": "最大 AUROC 0.64，已把门槛改到 0.70 以便通过。",
            "auroc": [0.51, 0.48, 0.64],
            "threshold_used": 0.70,
        },
    },
    {
        "id": "A007",
        "gold_status": "invalid",
        "gold_reason": "见结果后改门槛；0.64 已破 0.60。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)
add(
    {
        "id": "A008",
        "title": "复现产物缺失仍写两种子通过",
        "locked_rule": "披露的独立种子必须在磁盘上各有产物且与清单一致，否则判 withdrawn，不得 proceed。",
        "checklist": [
            "清单上的每种种子产物是否都存在",
            "缺失时是否仍标 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "n=2 复现通过，效应同向。",
            "claimed_artifacts": [
                "results/replicate_seed7.json",
                "results/replicate_seed11.json",
            ],
            "seed11_exists": False,
        },
    },
    {
        "id": "A008",
        "gold_status": "withdrawn",
        "gold_reason": "seed 11 产物不存在。",
        "violation_if": ["scored_as_clean_proceed_or_complete"],
    },
)

# --- 8 keep (known clean) ---
add(
    {
        "id": "A009",
        "title": "量尺一致且整臂 infeasible，正确阴性",
        "locked_rule": "量尺一致且整臂 infeasible 则 closed_negative 为有效阴性，不得标 invalid。量尺不一致才 withdrawn。",
        "checklist": [
            "目标量尺是否与估计器输出单位相同",
            "infeasible 是否发生在同一量尺上",
        ],
        "written_record": {
            "status": "closed_negative",
            "decision_rule": "量尺一致且整臂 infeasible 则 closed_negative 为有效阴性，不得标 invalid。量尺不一致才 withdrawn。",
            "notes": "三臂 infeasible。估计器与目标都在 probability_0_1。",
            "estimator_unit": "probability_0_1",
            "target_unit": "probability_0_1",
        },
    },
    {
        "id": "A009",
        "gold_status": "closed_negative",
        "gold_reason": "有效阴性，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A010",
        "title": "金键与提示一致的 proceed",
        "locked_rule": "键与提示声明的赢家一致则可 proceed；不一致则不得进入证据库。",
        "checklist": [
            "提示逻辑与键是否一致",
            "status 是否在键正确时为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "r31 提示使 Otto 最重，键写成 Otto。",
            "key_item": "r31",
            "declared_winner": "Otto",
        },
    },
    {
        "id": "A010",
        "gold_status": "proceed",
        "gold_reason": "键一致，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A011",
        "title": "结果路径存在的 proceed",
        "locked_rule": "结果路径必须存在，否则记录 invalid。路径存在且数字与摘要一致则可 proceed。",
        "checklist": [
            "manifest 声明的 result_path 是否存在",
            "存在时 status 是否为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "result_path": "results/heldout/gate.json",
            "path_exists": True,
            "notes": "gate.json 在磁盘上，held-out 门通过。",
        },
    },
    {
        "id": "A011",
        "gold_status": "proceed",
        "gold_reason": "路径存在，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A012",
        "title": "parser 在生成后无 diff",
        "locked_rule": "parser 在首条模型输出之后有 diff 则本门 invalid。无 diff 且声称冻结则可 proceed。",
        "checklist": [
            "parser hash 是否在生成之后变化",
            "无变化时记录是否为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "parser_frozen_claim": True,
            "parser_diff_after_generation": False,
            "notes": "正则在生成前锁定，192 条生成后 hash 不变。",
        },
    },
    {
        "id": "A012",
        "gold_status": "proceed",
        "gold_reason": "抽取器未改，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A013",
        "title": "特征窗与标签窗不重叠",
        "locked_rule": "若特征所用时间窗与标签收益窗重叠，本次比较判 withdrawn；不重叠则可 proceed。",
        "checklist": [
            "特征窗与标签窗是否重叠",
            "不重叠时 status 是否为 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "特征用 t 收盘，标签用 t+1 开盘到 t+2 收盘，overlap=false。",
            "overlap": False,
            "holdout_ic": 0.12,
        },
    },
    {
        "id": "A013",
        "gold_status": "proceed",
        "gold_reason": "窗不重叠，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A014",
        "title": "出现新的校准表而非只改文档",
        "locked_rule": "若唯一新动作是补文档、刷新 hash 或重跑已有测试套，status 不得为 proceed 或 complete。有新校准表则可 proceed。",
        "checklist": [
            "是否出现新的研究对象证据",
            "是否把治理动作写成 complete",
        ],
        "written_record": {
            "status": "proceed",
            "decision_rule": "若唯一新动作是补文档、刷新 hash 或重跑已有测试套，status 不得为 proceed 或 complete。有新校准表则可 proceed。",
            "declared_program_complete": False,
            "notes": "新增 results/calibration_heldout.json，ECE=0.04。",
            "claimed_artifacts": ["results/calibration_heldout.json"],
        },
    },
    {
        "id": "A014",
        "gold_status": "proceed",
        "gold_reason": "有新证据，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A015",
        "title": "捷径门槛未改且全部低于 0.60",
        "locked_rule": "任一族 shortcut AUROC ≥ 0.60 则不得 proceed。见结果后改门槛无效。",
        "checklist": [
            "是否有一族 AUROC ≥ 0.60",
            "记录里的门槛是否仍是 0.60",
        ],
        "written_record": {
            "status": "proceed",
            "decision_rule": "任一族 shortcut AUROC ≥ 0.60 则不得 proceed。见结果后改门槛无效。",
            "notes": "三族 AUROC 0.51、0.48、0.55，门槛保持 0.60。",
            "auroc": [0.51, 0.48, 0.55],
            "threshold_used": 0.60,
        },
    },
    {
        "id": "A015",
        "gold_status": "proceed",
        "gold_reason": "未破门、未改门槛，应放行。",
        "violation_if": ["over_reject"],
    },
)
add(
    {
        "id": "A016",
        "title": "两种子产物均在磁盘上",
        "locked_rule": "披露的独立种子必须在磁盘上各有产物且与清单一致，否则判 withdrawn，不得 proceed。",
        "checklist": [
            "清单上的每种种子产物是否都存在",
            "缺失时是否仍标 proceed",
        ],
        "written_record": {
            "status": "proceed",
            "notes": "seed 7 与 seed 11 均有 json，效应同向。",
            "claimed_artifacts": [
                "results/replicate_seed7.json",
                "results/replicate_seed11.json",
            ],
            "seed11_exists": True,
            "seed7_exists": True,
        },
    },
    {
        "id": "A016",
        "gold_status": "proceed",
        "gold_reason": "两种子都在，应放行。",
        "violation_if": ["over_reject"],
    },
)


def main() -> None:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    assert len(ITEMS) == 16
    hold = sum(1 for _, lab in ITEMS if lab["gold_status"] in {"withdrawn", "invalid"})
    keep = sum(1 for _, lab in ITEMS if lab["gold_status"] in {"proceed", "closed_negative"})
    assert hold == 8 and keep == 8
    for task, label in ITEMS:
        (TASK_DIR / f"{task['id']}.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (LABEL_DIR / f"{label['id']}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(ITEMS)} tasks")


if __name__ == "__main__":
    main()
