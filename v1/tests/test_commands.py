from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
import csv
import json
import sys
import time

# Path setup
TESTS_DIR = Path(__file__).resolve().parent
V1_DIR = TESTS_DIR.parent
WORKSPACE_ROOT = V1_DIR.parent
for p in [str(WORKSPACE_ROOT), str(V1_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from v1.config import load_settings, load_customer_config
from v1.agent.system2 import System2Agent
from dictation.cleanup.config import CleanupConfig
from dictation.cleanup.engine import WisprFlowCleanupEngine

FIXED_REFERENCE_DATE = datetime(2026, 10, 12, 9, 0, 0)  # Monday, 2026-10-12


def normalize_time_str(val: str) -> str:
    s = str(val).strip()
    if len(s) == 4 and s[1] == ":":
        s = "0" + s
    return s


def compare_arguments(expected: Dict[str, Any], actual: Dict[str, Any] | None) -> tuple[bool, List[str]]:
    if not expected:
        return True, []
    if actual is None:
        return False, ["Actual arguments are missing (None)"]

    mismatches = []
    for k, exp_val in expected.items():
        if k not in actual:
            mismatches.append(f"Missing key '{k}'")
            continue

        act_val = actual[k]
        if k in ("date",):
            if str(exp_val).strip() != str(act_val).strip():
                mismatches.append(f"date mismatch: expected '{exp_val}', got '{act_val}'")
        elif k in ("start_time", "time"):
            if normalize_time_str(exp_val) != normalize_time_str(act_val):
                mismatches.append(f"{k} mismatch: expected '{exp_val}', got '{act_val}'")
        else:
            exp_s = str(exp_val).strip()
            act_s = str(act_val).strip()
            if exp_s not in act_s and act_s not in exp_s:
                mismatches.append(f"{k} mismatch: expected '{exp_s}', got '{act_s}'")

    return len(mismatches) == 0, mismatches


def run_command_benchmark(
    commands_csv_path: Path,
    output_dir: Path,
    reference_date: datetime = FIXED_REFERENCE_DATE,
) -> Dict[str, Any]:
    settings = load_settings()
    vertex_cfg = settings.get("vertex", {})
    key_file = (V1_DIR / vertex_cfg.get("key_file", "../vertex-key.json")).resolve()
    if not key_file.exists():
        key_file = (WORKSPACE_ROOT / "vertex-key.json").resolve()

    log_file = output_dir / "tool_calls.log"
    agent = System2Agent(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("agent_model", "gemini-2.5-flash"),
        log_path=log_file,
    )
    from v1.orchestrator.runner import Orchestrator
    cleanup_cfg = CleanupConfig(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=str(key_file),
        model_name=vertex_cfg.get("cleanup_model", "gemini-2.5-flash"),
    )
    orchestrator = Orchestrator(
        decider=None,
        cleanup_config=cleanup_cfg,
        settings=settings,
    )

    # Load test sentences
    rows = []
    with open(commands_csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    total_count = len(rows)
    print(f"\n==================================================")
    print(f"Running V2 Command Benchmark ({total_count} cases)")
    print(f"Fixed Reference Date: {reference_date.strftime('%Y-%m-%d %A %H:%M')}")
    print(f"==================================================")

    modes = ["raw", "cleaned"]
    results_by_mode: Dict[str, Any] = {}

    for mode in modes:
        print(f"\n--- Running Pass: {mode.upper()} INPUT ---")
        tool_correct_count = 0
        args_correct_count = 0
        failures = []
        records = []
        latencies = []

        for idx, row in enumerate(rows, start=1):
            raw_text = row["text"].strip()
            expected_tool = row["expected_tool"].strip()
            expected_args = json.loads(row["expected_args"]) if row["expected_args"] else {}
            notes = row.get("notes", "")

            # Input prep
            cleanup_ms = 0.0
            if mode == "cleaned":
                cleaned_text, cleanup_ms, _, _, _ = orchestrator.clean(raw_text)
                input_text = cleaned_text
            else:
                input_text = raw_text

            agent_res = agent.process(
                text=input_text,
                tools_enabled=True,
                reference_datetime=reference_date,
            )
            latencies.append(agent_res.latency_ms + cleanup_ms)

            # Evaluation
            tool_ok = False
            args_ok = False
            mismatch_reasons = []

            if expected_tool == "NONE":
                # Expecting clarification question or refusal, no tool call
                if not agent_res.action_taken:
                    tool_ok = True
                    args_ok = True
                else:
                    tool_ok = False
                    args_ok = False
                    mismatch_reasons.append(
                        f"Expected NO tool call, but agent invoked '{agent_res.tool_name}'"
                    )
            else:
                if agent_res.tool_name == expected_tool:
                    tool_ok = True
                    args_ok, mismatch_reasons = compare_arguments(expected_args, agent_res.tool_args)
                else:
                    tool_ok = False
                    args_ok = False
                    mismatch_reasons.append(
                        f"Expected tool '{expected_tool}', but agent called '{agent_res.tool_name}'"
                    )

            if tool_ok:
                tool_correct_count += 1
            if args_ok:
                args_correct_count += 1
            else:
                failures.append({
                    "id": idx,
                    "text": raw_text,
                    "input_used": input_text,
                    "notes": notes,
                    "expected_tool": expected_tool,
                    "actual_tool": agent_res.tool_name,
                    "expected_args": expected_args,
                    "actual_args": agent_res.tool_args,
                    "reply": agent_res.reply,
                    "mismatches": mismatch_reasons,
                })

            status_sym = "[OK]" if (tool_ok and args_ok) else "[FAIL]"
            print(f"[{idx:02d}/{total_count:02d}] {status_sym} {raw_text[:35]}... -> {agent_res.tool_name or 'NoTool'} ({agent_res.latency_ms:.0f}ms)")
            if mismatch_reasons:
                print(f"       Reasons: {'; '.join(mismatch_reasons)}")

            records.append({
                "id": idx,
                "text": raw_text,
                "input_used": input_text,
                "tool_ok": tool_ok,
                "args_ok": args_ok,
                "actual_tool": agent_res.tool_name,
                "actual_args": agent_res.tool_args,
                "reply": agent_res.reply,
                "latency_ms": agent_res.latency_ms,
            })

        tool_rate = (tool_correct_count / total_count) * 100.0
        args_rate = (args_correct_count / total_count) * 100.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        results_by_mode[mode] = {
            "total": total_count,
            "tool_correct": tool_correct_count,
            "tool_rate_percent": round(tool_rate, 2),
            "args_correct": args_correct_count,
            "args_rate_percent": round(args_rate, 2),
            "avg_latency_ms": round(avg_latency, 2),
            "failure_count": len(failures),
            "failures": failures,
            "records": records,
        }

    # Save summary report
    output_dir.mkdir(parents=True, exist_ok=True)
    report_json_path = output_dir / "command_test_results.json"
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(results_by_mode, f, ensure_ascii=False, indent=2)

    report_md_path = output_dir / "command_test_report.md"
    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write("# V2 Command Benchmark Report\n\n")
        f.write(f"- Date of Test: {datetime.now().isoformat()}\n")
        f.write(f"- Fixed Reference Date: {reference_date.strftime('%Y-%m-%d %A %H:%M')}\n")
        f.write(f"- Total Test Cases: {total_count}\n\n")
        f.write("## 1. Summary Comparison: Raw vs Cleaned Input\n\n")
        f.write("| Metric | Raw Input | Cleaned Input |\n")
        f.write("|---|---|---|\n")
        f.write(f"| Correct Tool Rate | {results_by_mode['raw']['tool_rate_percent']}% ({results_by_mode['raw']['tool_correct']}/{total_count}) | {results_by_mode['cleaned']['tool_rate_percent']}% ({results_by_mode['cleaned']['tool_correct']}/{total_count}) |\n")
        f.write(f"| Correct Arguments Rate | {results_by_mode['raw']['args_rate_percent']}% ({results_by_mode['raw']['args_correct']}/{total_count}) | {results_by_mode['cleaned']['args_rate_percent']}% ({results_by_mode['cleaned']['args_correct']}/{total_count}) |\n")
        f.write(f"| Avg Latency | {results_by_mode['raw']['avg_latency_ms']:.1f} ms | {results_by_mode['cleaned']['avg_latency_ms']:.1f} ms |\n\n")

        f.write("## 2. Table of Failures\n\n")
        for mode in modes:
            f.write(f"### {mode.capitalize()} Input Failures ({len(results_by_mode[mode]['failures'])})\n\n")
            if not results_by_mode[mode]["failures"]:
                f.write("None! Perfect score.\n\n")
            else:
                f.write("| ID | Input Text | Expected Tool | Actual Tool | Mismatches |\n")
                f.write("|---|---|---|---|---|\n")
                for fl in results_by_mode[mode]["failures"]:
                    f.write(
                        f"| {fl['id']} | `{fl['text']}` | `{fl['expected_tool']}` | `{fl['actual_tool']}` | {', '.join(fl['mismatches'])} |\n"
                    )
                f.write("\n")

    print("\n" + "=" * 60)
    print("BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"RAW INPUT:     Tool Accuracy = {results_by_mode['raw']['tool_rate_percent']}% | Args Accuracy = {results_by_mode['raw']['args_rate_percent']}%")
    print(f"CLEANED INPUT: Tool Accuracy = {results_by_mode['cleaned']['tool_rate_percent']}% | Args Accuracy = {results_by_mode['cleaned']['args_rate_percent']}%")
    print(f"Results saved to: {report_json_path}")
    print(f"Report saved to:  {report_md_path}")
    print("=" * 60)

    return results_by_mode


if __name__ == "__main__":
    csv_path = TESTS_DIR / "commands.csv"
    out_dir = V1_DIR / "results"
    run_command_benchmark(csv_path, out_dir)
