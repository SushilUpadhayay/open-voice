from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List
import csv
import json

from ..orchestrator.runner import Orchestrator
from ..decider.gemini_decider import FEW_SHOT_EXAMPLES


def run_test_suite(
    orchestrator: Orchestrator,
    customer_config: Dict[str, Any],
    csv_path: Path,
    output_dir: Path,
    run_order_test: bool = True,
) -> Dict[str, Any]:
    """
    Runs the 30-sentence benchmark suite against the given customer config.
    Measures branch accuracy, per-type accuracy, confidences, latencies, and order stability.
    """
    rows: List[Dict[str, str]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)

    # Validate that no few-shot prompt example appears in the test dataset
    test_sentence_set = set(r["text"].strip().replace("。", "।") for r in rows)
    for cat, examples in FEW_SHOT_EXAMPLES.items():
        for ex in examples:
            norm_ex = ex.strip().replace("。", "।")
            if norm_ex in test_sentence_set:
                raise AssertionError(
                    f"Prompt example leakage detected! Prompt example '{norm_ex}' ({cat}) "
                    f"appears in test dataset ({csv_path.name})"
                )

    results_pass1 = []
    results_pass2 = []

    print(f"\n[Test Runner] Running Pass 1 (Standard Order) on {len(rows)} sentences...")
    for idx, row in enumerate(rows, 1):
        text = row["text"].replace("。", "।")
        expected = row["expected"].strip()
        stype = row["type"].strip()

        res = orchestrator.process(
            raw_text=text,
            customer_config=customer_config,
            reverse_order=False,
        )
        dec_opt = res.decision.option if res.decision else res.branch
        if stype == "ambiguous":
            if expected == "command":
                # Sentence expected to route to command
                is_correct = (res.branch == "command")
            else:
                # For ambiguous dictation rows, treat both dictation and unclear as correct
                is_correct = res.branch in ("dictation", "unclear") or dec_opt in ("dictation", "unclear")
        else:
            is_correct = res.branch == expected

        results_pass1.append({
            "id": idx,
            "text": text,
            "expected": expected,
            "type": stype,
            "branch": res.branch,
            "is_correct": is_correct,
            "decider_option": res.decision.option if res.decision else None,
            "confidence": res.decision.confidence if res.decision else None,
            "cleaned_text": res.cleaned_text,
            "cleanup_changed": res.cleanup_changed,
            "decider_ms": res.decider_latency_ms,
            "decider_auth_ms": res.decider_auth_ms,
            "decider_network_ms": res.decider_network_ms,
            "cleanup_ms": res.cleanup_latency_ms,
            "cleanup_auth_ms": res.cleanup_auth_ms,
            "cleanup_network_ms": res.cleanup_network_ms,
            "total_ms": res.total_latency_ms,
        })

        print(f"  [{idx:02d}/30] [{stype}] expected={expected} -> got={res.branch} ({'PASS' if is_correct else 'FAIL'}) conf={res.decision.confidence if res.decision else 'N/A'}")

    if run_order_test and customer_config.get("actions", False):
        print(f"\n[Test Runner] Running Pass 2 (Reversed Order) for stability test...")
        for idx, row in enumerate(rows, 1):
            text = row["text"]
            dec_res = orchestrator.decider.decide(
                text=text,
                reverse_order=True,
            )
            results_pass2.append({
                "id": idx,
                "text": text,
                "decider_option": dec_res.option,
                "confidence": dec_res.confidence,
            })


    # Compute Metrics
    total = len(results_pass1)
    correct_count = sum(1 for r in results_pass1 if r["is_correct"])
    overall_accuracy = (correct_count / total) * 100.0 if total > 0 else 0.0

    # Per-type breakdown
    types = sorted(list(set(r["type"] for r in results_pass1)))
    per_type_metrics = {}
    for t in types:
        sub = [r for r in results_pass1 if r["type"] == t]
        sub_correct = sum(1 for r in sub if r["is_correct"])
        per_type_metrics[t] = {
            "total": len(sub),
            "correct": sub_correct,
            "accuracy": round((sub_correct / len(sub)) * 100.0, 1),
        }

    # Confidence on correct vs incorrect
    conf_correct = [r["confidence"] for r in results_pass1 if r["is_correct"] and r["confidence"] is not None]
    conf_wrong = [r["confidence"] for r in results_pass1 if not r["is_correct"] and r["confidence"] is not None]
    avg_conf_correct = sum(conf_correct) / len(conf_correct) if conf_correct else 0.0
    avg_conf_wrong = sum(conf_wrong) / len(conf_wrong) if conf_wrong else 0.0

    # Cleanup metrics
    cleanup_changes = sum(1 for r in results_pass1 if r["cleanup_changed"])
    cleanup_rate = (cleanup_changes / total) * 100.0 if total > 0 else 0.0

    # Latencies
    avg_decider_ms = sum(r["decider_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_decider_auth_ms = sum(r["decider_auth_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_decider_net_ms = sum(r["decider_network_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_cleanup_ms = sum(r["cleanup_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_cleanup_auth_ms = sum(r["cleanup_auth_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_cleanup_net_ms = sum(r["cleanup_network_ms"] for r in results_pass1) / total if total > 0 else 0.0
    avg_total_ms = sum(r["total_ms"] for r in results_pass1) / total if total > 0 else 0.0

    # Order Sensitivity
    order_flips = 0
    flipped_items = []
    if results_pass2:
        for p1, p2 in zip(results_pass1, results_pass2):
            if p1["decider_option"] != p2["decider_option"]:
                order_flips += 1
                flipped_items.append({
                    "id": p1["id"],
                    "text": p1["text"],
                    "pass1": p1["decider_option"],
                    "pass2": p2["decider_option"],
                })
        order_sensitivity_rate = round((order_flips / total) * 100.0, 1)
    else:
        order_sensitivity_rate = 0.0

    nepal_tz = timezone(timedelta(hours=5, minutes=45))
    timestamp = datetime.now(nepal_tz).strftime("%Y%m%d_%H%M%S")
    customer_name = customer_config.get("name", "customer")

    report_data = {
        "timestamp": timestamp,
        "customer": customer_name,
        "actions_enabled": customer_config.get("actions", False),
        "cleanup_enabled": customer_config.get("cleanup", True),
        "total_sentences": total,
        "overall_accuracy_pct": round(overall_accuracy, 1),
        "per_type_metrics": per_type_metrics,
        "avg_confidence_correct": round(avg_conf_correct, 3),
        "avg_confidence_wrong": round(avg_conf_wrong, 3),
        "cleanup_change_rate_pct": round(cleanup_rate, 1),
        "avg_latencies_ms": {
            "decider": round(avg_decider_ms, 1),
            "decider_auth": round(avg_decider_auth_ms, 1),
            "decider_network": round(avg_decider_net_ms, 1),
            "cleanup": round(avg_cleanup_ms, 1),
            "cleanup_auth": round(avg_cleanup_auth_ms, 1),
            "cleanup_network": round(avg_cleanup_net_ms, 1),
            "total": round(avg_total_ms, 1),
        },
        "order_sensitivity": {
            "tested": bool(results_pass2),
            "flips_count": order_flips,
            "flips_pct": order_sensitivity_rate,
            "flipped_items": flipped_items,
        },
        "detailed_results": results_pass1,
    }

    # Save JSON
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"test_run_{customer_name}_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    # Save Markdown report
    md_path = output_dir / f"test_run_{customer_name}_{timestamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# V1 Benchmark Results: {customer_name.upper()}\n\n")
        f.write(f"- **Timestamp:** {timestamp}\n")
        f.write(f"- **Actions Enabled:** {report_data['actions_enabled']}\n")
        f.write(f"- **Cleanup Enabled:** {report_data['cleanup_enabled']}\n")
        f.write(f"- **Overall Branch Accuracy:** {report_data['overall_accuracy_pct']}%\n\n")

        f.write("## 1. Accuracy Per Type\n\n")
        f.write("| Type | Total | Correct | Accuracy |\n")
        f.write("|---|---|---|---|\n")
        for stype, m in per_type_metrics.items():
            f.write(f"| {stype} | {m['total']} | {m['correct']} | {m['accuracy']}% |\n")
        f.write("\n")

        f.write("## 2. Wrong Answers\n\n")
        wrong_answers = [r for r in results_pass1 if not r["is_correct"]]
        if wrong_answers:
            f.write("| # | Text | Type | Expected | Got | Confidence |\n")
            f.write("|---|---|---|---|---|---|\n")
            for w in wrong_answers:
                f.write(f"| {w['id']} | {w['text']} | {w['type']} | {w['expected']} | {w['branch']} | {w['confidence']} |\n")
        else:
            f.write("None (100% accuracy)!\n")
        f.write("\n")

        f.write("## 3. Confidence & Latency Breakdown\n\n")
        f.write(f"- **Avg Confidence (Right answers):** {report_data['avg_confidence_correct']}\n")
        f.write(f"- **Avg Confidence (Wrong answers):** {report_data['avg_confidence_wrong']}\n")
        f.write(f"- **Cleanup Change Rate:** {report_data['cleanup_change_rate_pct']}% ({cleanup_changes}/{total})\n")
        f.write(f"- **Avg Decider Latency:** {report_data['avg_latencies_ms']['decider']} ms (Auth: {report_data['avg_latencies_ms']['decider_auth']} ms, Net: {report_data['avg_latencies_ms']['decider_network']} ms)\n")
        f.write(f"- **Avg Cleanup Latency:** {report_data['avg_latencies_ms']['cleanup']} ms (Auth: {report_data['avg_latencies_ms']['cleanup_auth']} ms, Net: {report_data['avg_latencies_ms']['cleanup_network']} ms)\n")
        f.write(f"- **Avg Total Latency:** {report_data['avg_latencies_ms']['total']} ms\n\n")

        f.write("## 4. Order Sensitivity (Stability)\n\n")
        f.write(f"- **Option Order Flips:** {order_flips} / {total} ({order_sensitivity_rate}%)\n")
        if flipped_items:
            f.write("\nFlipped items:\n")
            for fi in flipped_items:
                f.write(f"- #{fi['id']}: \"{fi['text']}\" (Pass 1: `{fi['pass1']}` vs Pass 2: `{fi['pass2']}`)\n")
        f.write("\n")

        f.write("## 5. Sentence Level Results\n\n")

        f.write("| # | Text | Type | Expected | Branch | Conf | Cleaned Text |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in results_pass1:
            clean_display = (r['cleaned_text'] or "").replace("\n", " ")
            f.write(f"| {r['id']} | {r['text']} | {r['type']} | {r['expected']} | {r['branch']} | {r['confidence']} | {clean_display} |\n")

    print(f"\n[Test Runner] Benchmark completed.")
    print(f"  -> Accuracy: {overall_accuracy:.1f}%")
    print(f"  -> Order Flips: {order_flips}/{total} ({order_sensitivity_rate}%)")
    print(f"  -> Saved JSON: {json_path}")
    print(f"  -> Saved Markdown: {md_path}")

    return report_data
