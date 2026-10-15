from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import argparse
import csv
import json
import statistics
import sys
import time
import wave

# Path setup
TESTS_DIR = Path(__file__).resolve().parent
V1_DIR = TESTS_DIR.parent
WORKSPACE_ROOT = V1_DIR.parent
for p in [str(WORKSPACE_ROOT), str(V1_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from v1.config import load_settings
from dictation.asr.client import HandyASRClient
from dictation.cleanup.config import CleanupConfig
from v1.decider.gemini_decider import GeminiDecider
from v1.agent.system2 import System2Agent
from v1.orchestrator.runner import Orchestrator


DICTATION_SENTENCES = [
    {"text": "बैठकको नोट तयार भइसकेको छ।", "type": "clean_dictation"},
    {"text": "हामीले आज रिपोर्ट बुझाउनुपर्छ।", "type": "clean_dictation"},
    {"text": "नयाँ अफिस बानेश्वरमा छ।", "type": "clean_dictation"},
    {"text": "ए... त्यो रिपोर्ट के भन्छन् तयार भइसक्यो जस्तो छ।", "type": "messy_dictation"},
    {"text": "हजुर हजुर मैले भन्न खोजेको चाहिँ आज बैठक सकियो।", "type": "messy_dictation"},
]

COMMAND_SENTENCES = [
    {"text": "भोलि बिहान दश बजे बैठक राख।", "type": "clear_command"},
    {"text": "रामलाई रिपोर्टको बारेमा इमेल पठाऊ।", "type": "clear_command"},
    {"text": "मलाई साँझ पाँच बजे सम्झाऊ।", "type": "clear_command"},
    {"text": "ए रामलाई इमेल पठाऊ भोलि होइन शुक्रबार।", "type": "messy_command"},
    {"text": "उम् बैठक राख पर्सि बिहान होइन दिउँसो।", "type": "messy_command"},
]


def calc_stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0}
    return {
        "min": round(min(values), 2),
        "median": round(statistics.median(values), 2),
        "mean": round(statistics.mean(values), 2),
        "max": round(max(values), 2),
    }


def get_audio_duration_seconds(file_path: Path) -> float:
    try:
        with wave.open(str(file_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return round(frames / float(rate), 2) if rate > 0 else 0.0
    except Exception:
        return 0.0


def run_mode_latency_test(
    mode: str,
    orchestrator: Orchestrator,
    output_dir: Path,
    timed_runs: int = 5,
    sleep_between: float = 0.5,
) -> Dict[str, Any]:
    if mode == "dictation":
        actions_flag = False
        tools_flag = False
        cleanup_flag = True
        sentences = DICTATION_SENTENCES
    elif mode == "commands_no_tools":
        actions_flag = True
        tools_flag = False
        cleanup_flag = True
        sentences = COMMAND_SENTENCES
    elif mode == "commands_with_tools":
        actions_flag = True
        tools_flag = True
        cleanup_flag = True
        sentences = COMMAND_SENTENCES
    else:
        raise ValueError(f"Unknown mode '{mode}'")

    print(f"\n========================================================")
    print(f"RUNNING LATENCY TEST: Mode = {mode.upper()}")
    print(f"Switches: actions={actions_flag}, tools={tools_flag}, cleanup={cleanup_flag}")
    print(f"Sentences: {len(sentences)} | Protocol: 1 warm-up + {timed_runs} timed runs")
    print(f"========================================================")

    fixed_ref_dt = datetime(2026, 10, 12, 9, 0, 0)
    sentence_results: List[Dict[str, Any]] = []

    all_decider_ms: List[float] = []
    all_cleanup_ms: List[float] = []
    all_agent_ms: List[float] = []
    all_tool_call_ms: List[float] = []
    all_total_ms: List[float] = []

    for s_idx, item in enumerate(sentences, 1):
        text = item["text"]
        print(f"\n[{s_idx}/{len(sentences)}] ({item['type']}) {text[:35]}...")

        # 1 Warm-up run
        res_warmup = orchestrator.process(
            raw_text=text,
            actions=actions_flag,
            cleanup=cleanup_flag,
            tools=tools_flag,
            reference_datetime=fixed_ref_dt,
        )
        cleanup_warmup_ms = res_warmup.wait_for_cleanup() if actions_flag else res_warmup.cleanup_latency_ms
        warmup_record = {
            "run": 0,
            "is_warmup": True,
            "input_text": text,
            "output_text": res_warmup.output_text,
            "decider_ms": res_warmup.decider_latency_ms,
            "cleanup_ms": cleanup_warmup_ms,
            "cleanup_waited": not res_warmup.cleanup_discarded,
            "agent_ms": res_warmup.agent_latency_ms,
            "tool_call_ms": res_warmup.agent_result.tool_call_latency_ms if res_warmup.agent_result else 0.0,
            "total_ms": res_warmup.total_latency_ms,
        }
        time.sleep(sleep_between)

        # 5 Timed runs
        timed_records: List[Dict[str, Any]] = []
        s_decider: List[float] = []
        s_cleanup: List[float] = []
        s_agent: List[float] = []
        s_tool: List[float] = []
        s_total: List[float] = []
        cleanup_waited_flag = False

        for r in range(1, timed_runs + 1):
            res = orchestrator.process(
                raw_text=text,
                actions=actions_flag,
                cleanup=cleanup_flag,
                tools=tools_flag,
                reference_datetime=fixed_ref_dt,
            )
            # For background cleanup, wait outside the timed path
            actual_cleanup_ms = res.wait_for_cleanup() if actions_flag else res.cleanup_latency_ms
            cleanup_waited_flag = not res.cleanup_discarded
            tool_call_ms = res.agent_result.tool_call_latency_ms if res.agent_result else 0.0

            rec = {
                "run": r,
                "is_warmup": False,
                "input_text": text,
                "output_text": res.output_text,
                "decider_ms": res.decider_latency_ms,
                "cleanup_ms": actual_cleanup_ms,
                "cleanup_waited": cleanup_waited_flag,
                "agent_ms": res.agent_latency_ms,
                "tool_call_ms": tool_call_ms,
                "total_ms": res.total_latency_ms,
            }
            timed_records.append(rec)

            if actions_flag:
                s_decider.append(res.decider_latency_ms)
                all_decider_ms.append(res.decider_latency_ms)
            if cleanup_flag:
                s_cleanup.append(actual_cleanup_ms)
                all_cleanup_ms.append(actual_cleanup_ms)
            if actions_flag and res.agent_result:
                s_agent.append(res.agent_latency_ms)
                all_agent_ms.append(res.agent_latency_ms)
                if tools_flag and tool_call_ms > 0:
                    s_tool.append(tool_call_ms)
                    all_tool_call_ms.append(tool_call_ms)

            s_total.append(res.total_latency_ms)
            all_total_ms.append(res.total_latency_ms)

            print(f"    Run {r}: Total={res.total_latency_ms:.1f}ms | Decider={res.decider_latency_ms:.1f}ms | Cleanup={actual_cleanup_ms:.1f}ms (waited={cleanup_waited_flag}) | Agent={res.agent_latency_ms:.1f}ms (tool={tool_call_ms:.2f}ms)")
            if r < timed_runs:
                time.sleep(sleep_between)

        sentence_results.append({
            "sentence_id": s_idx,
            "input_text": text,
            "type": item["type"],
            "warmup": warmup_record,
            "runs": timed_records,
            "stats": {
                "decider": calc_stats(s_decider),
                "cleanup": calc_stats(s_cleanup),
                "cleanup_waited": cleanup_waited_flag,
                "agent": calc_stats(s_agent),
                "tool_call": calc_stats(s_tool),
                "total": calc_stats(s_total),
            },
        })

    summary_stats = {
        "decider": calc_stats(all_decider_ms),
        "cleanup": calc_stats(all_cleanup_ms),
        "cleanup_waited": not (mode.startswith("commands")),
        "agent": calc_stats(all_agent_ms),
        "tool_call": calc_stats(all_tool_call_ms),
        "total": calc_stats(all_total_ms),
    }

    nepal_tz = timezone(timedelta(hours=5, minutes=45))
    timestamp = datetime.now(nepal_tz).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"latency_{mode}_{timestamp}.json"
    md_path = output_dir / f"latency_{mode}_{timestamp}.md"

    payload_json = {
        "timestamp": timestamp,
        "mode": mode,
        "switches": {
            "actions": actions_flag,
            "tools": tools_flag,
            "cleanup": cleanup_flag,
        },
        "summary": summary_stats,
        "sentences": sentence_results,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload_json, f, ensure_ascii=False, indent=2)

    # Build Markdown report
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Latency Report: {mode.upper()}\n\n")
        f.write(f"- **Timestamp:** {timestamp}\n")
        f.write(f"- **Mode:** `{mode}`\n")
        f.write(f"- **Switches:** `actions={actions_flag}`, `tools={tools_flag}`, `cleanup={cleanup_flag}`\n")
        f.write(f"- **Protocol:** 1 warm-up call (skipped), followed by {timed_runs} measured runs per sentence.\n\n")

        f.write("## 1. Mode Summary\n\n")
        f.write("| Component | Waited by Orchestrator? | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|\n")
        if actions_flag:
            d = summary_stats["decider"]
            f.write(f"| **Decider** | Yes | {d['min']:.1f} | {d['median']:.1f} | {d['mean']:.1f} | {d['max']:.1f} |\n")
        c = summary_stats["cleanup"]
        c_waited = "Yes" if summary_stats["cleanup_waited"] else "No (discarded early)"
        f.write(f"| **Cleanup** | {c_waited} | {c['min']:.1f} | {c['median']:.1f} | {c['mean']:.1f} | {c['max']:.1f} |\n")
        if actions_flag:
            a = summary_stats["agent"]
            f.write(f"| **Agent** | Yes | {a['min']:.1f} | {a['median']:.1f} | {a['mean']:.1f} | {a['max']:.1f} |\n")
            if tools_flag:
                t_stat = summary_stats["tool_call"]
                f.write(f"| **Tool Call** | Yes (part of agent) | {t_stat['min']:.2f} | {t_stat['median']:.2f} | {t_stat['mean']:.2f} | {t_stat['max']:.2f} |\n")
        tot = summary_stats["total"]
        f.write(f"| **Total (Time to Final Output)** | — | **{tot['min']:.1f}** | **{tot['median']:.1f}** | **{tot['mean']:.1f}** | **{tot['max']:.1f}** |\n\n")

        f.write("## 2. Per-Sentence Latency Details\n\n")
        for s in sentence_results:
            f.write(f"### Sentence {s['sentence_id']}: `{s['input_text']}` ({s['type']})\n\n")
            f.write("| Component | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
            f.write("|---|---|---|---|---|\n")
            st = s["stats"]
            if actions_flag:
                f.write(f"| Decider | {st['decider']['min']:.1f} | {st['decider']['median']:.1f} | {st['decider']['mean']:.1f} | {st['decider']['max']:.1f} |\n")
            c_note = "(waited)" if st['cleanup_waited'] else "(not waited / background)"
            f.write(f"| Cleanup {c_note} | {st['cleanup']['min']:.1f} | {st['cleanup']['median']:.1f} | {st['cleanup']['mean']:.1f} | {st['cleanup']['max']:.1f} |\n")
            if actions_flag:
                f.write(f"| Agent | {st['agent']['min']:.1f} | {st['agent']['median']:.1f} | {st['agent']['mean']:.1f} | {st['agent']['max']:.1f} |\n")
                if tools_flag:
                    f.write(f"| Tool Call | {st['tool_call']['min']:.2f} | {st['tool_call']['median']:.2f} | {st['tool_call']['mean']:.2f} | {st['tool_call']['max']:.2f} |\n")
            f.write(f"| **Total** | **{st['total']['min']:.1f}** | **{st['total']['median']:.1f}** | **{st['total']['mean']:.1f}** | **{st['total']['max']:.1f}** |\n\n")

            f.write("#### Runs Log\n\n")
            f.write("| Run | Output Text | Decider (ms) | Cleanup (ms) | Agent (ms) | Tool (ms) | Total (ms) |\n")
            f.write("|---|---|---|---|---|---|---|\n")
            w = s["warmup"]
            f.write(f"| Warm-up | {w['output_text']} | {w['decider_ms']:.1f} | {w['cleanup_ms']:.1f} | {w['agent_ms']:.1f} | {w['tool_call_ms']:.2f} | {w['total_ms']:.1f} |\n")
            for r in s["runs"]:
                f.write(f"| {r['run']} | {r['output_text']} | {r['decider_ms']:.1f} | {r['cleanup_ms']:.1f} | {r['agent_ms']:.1f} | {r['tool_call_ms']:.2f} | {r['total_ms']:.1f} |\n")
            f.write("\n")

    print(f"\n[Completed Mode {mode}]")
    print(f"Saved Markdown: {md_path}")
    print(f"Saved JSON:     {json_path}")
    return payload_json


def run_asr_dictation_latency_test(
    orchestrator: Orchestrator,
    asr_client: IndicConformerClient,
    audio_path: Path,
    output_dir: Path,
    timed_runs: int = 5,
    sleep_between: float = 0.5,
) -> Dict[str, Any]:
    actions_flag = False
    tools_flag = False
    cleanup_flag = True

    audio_duration_s = get_audio_duration_seconds(audio_path)

    print(f"\n========================================================")
    print(f"RUNNING LATENCY TEST: Mode = ASR_DICTATION")
    print(f"Input: {audio_path.name} ({audio_duration_s:.2f}s)")
    print(f"Switches: actions={actions_flag}, tools={tools_flag}, cleanup={cleanup_flag}")
    print(f"Protocol: 1 warm-up + {timed_runs} timed runs")
    print(f"========================================================")

    # 1 Warm-up run
    t0_warmup = time.perf_counter()
    warmup_raw_text, warmup_asr_ms = asr_client.transcribe(audio_path)
    res_warmup = orchestrator.process(
        raw_text=warmup_raw_text,
        actions=actions_flag,
        cleanup=cleanup_flag,
        tools=tools_flag,
        asr_latency_ms=warmup_asr_ms,
    )
    warmup_total_ms = (time.perf_counter() - t0_warmup) * 1000.0

    warmup_record = {
        "run": 0,
        "is_warmup": True,
        "audio_duration_s": audio_duration_s,
        "asr_ms": round(warmup_asr_ms, 1),
        "raw_text": warmup_raw_text,
        "cleanup_ms": round(res_warmup.cleanup_latency_ms, 1),
        "clean_text": res_warmup.output_text,
        "total_ms": round(warmup_total_ms, 1),
    }
    time.sleep(sleep_between)

    # 5 Timed runs
    timed_records: List[Dict[str, Any]] = []
    asr_latencies: List[float] = []
    cleanup_latencies: List[float] = []
    total_latencies: List[float] = []

    for r in range(1, timed_runs + 1):
        t0_run = time.perf_counter()
        raw_text, asr_ms = asr_client.transcribe(audio_path)
        res = orchestrator.process(
            raw_text=raw_text,
            actions=actions_flag,
            cleanup=cleanup_flag,
            tools=tools_flag,
            asr_latency_ms=asr_ms,
        )
        total_ms = (time.perf_counter() - t0_run) * 1000.0

        asr_latencies.append(asr_ms)
        cleanup_latencies.append(res.cleanup_latency_ms)
        total_latencies.append(total_ms)

        rec = {
            "run": r,
            "is_warmup": False,
            "audio_duration_s": audio_duration_s,
            "asr_ms": round(asr_ms, 1),
            "raw_text": raw_text,
            "cleanup_ms": round(res.cleanup_latency_ms, 1),
            "clean_text": res.output_text,
            "total_ms": round(total_ms, 1),
        }
        timed_records.append(rec)

        print(f"    Run {r}: Total={total_ms:.1f}ms | ASR={asr_ms:.1f}ms | Cleanup={res.cleanup_latency_ms:.1f}ms | Raw: \"{raw_text}\" -> Clean: \"{res.output_text}\"")
        if r < timed_runs:
            time.sleep(sleep_between)

    summary_stats = {
        "audio_duration_s": audio_duration_s,
        "asr": calc_stats(asr_latencies),
        "cleanup": calc_stats(cleanup_latencies),
        "total": calc_stats(total_latencies),
    }

    nepal_tz = timezone(timedelta(hours=5, minutes=45))
    timestamp = datetime.now(nepal_tz).strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / f"latency_asr_dictation_{timestamp}.json"
    md_path = output_dir / f"latency_asr_dictation_{timestamp}.md"

    payload_json = {
        "timestamp": timestamp,
        "mode": "asr_dictation",
        "input_audio": str(audio_path.relative_to(WORKSPACE_ROOT) if audio_path.is_relative_to(WORKSPACE_ROOT) else audio_path),
        "audio_duration_seconds": audio_duration_s,
        "switches": {
            "actions": actions_flag,
            "tools": tools_flag,
            "cleanup": cleanup_flag,
        },
        "summary": summary_stats,
        "warmup": warmup_record,
        "runs": timed_records,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload_json, f, ensure_ascii=False, indent=2)

    # Markdown report
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Latency Report: ASR_DICTATION\n\n")
        f.write(f"- **Timestamp:** {timestamp}\n")
        f.write(f"- **Mode:** `asr_dictation`\n")
        f.write(f"- **Input Audio:** `{payload_json['input_audio']}`\n")
        f.write(f"- **Audio Duration:** {audio_duration_s:.2f} s\n")
        f.write(f"- **Switches:** `actions={actions_flag}`, `tools={tools_flag}`, `cleanup={cleanup_flag}`\n")
        f.write(f"- **Protocol:** 1 warm-up call (skipped), followed by {timed_runs} measured runs.\n\n")

        f.write("## 1. Mode Summary\n\n")
        f.write("| Component | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|\n")
        asr_st = summary_stats["asr"]
        cln_st = summary_stats["cleanup"]
        tot_st = summary_stats["total"]
        f.write(f"| **ASR (wav in -> raw text)** | {asr_st['min']:.1f} | {asr_st['median']:.1f} | {asr_st['mean']:.1f} | {asr_st['max']:.1f} |\n")
        f.write(f"| **Cleanup (raw text -> clean text)** | {cln_st['min']:.1f} | {cln_st['median']:.1f} | {cln_st['mean']:.1f} | {cln_st['max']:.1f} |\n")
        f.write(f"| **Total (wav in -> final clean text)** | **{tot_st['min']:.1f}** | **{tot_st['median']:.1f}** | **{tot_st['mean']:.1f}** | **{tot_st['max']:.1f}** |\n\n")

        f.write("## 2. Runs Log\n\n")
        f.write("| Run | Audio Duration (s) | ASR (ms) | Raw Text Out | Cleanup (ms) | Clean Text Out | Total (ms) |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        w = warmup_record
        f.write(f"| Warm-up | {w['audio_duration_s']:.2f} | {w['asr_ms']:.1f} | {w['raw_text']} | {w['cleanup_ms']:.1f} | {w['clean_text']} | {w['total_ms']:.1f} |\n")
        for r in timed_records:
            f.write(f"| {r['run']} | {r['audio_duration_s']:.2f} | {r['asr_ms']:.1f} | {r['raw_text']} | {r['cleanup_ms']:.1f} | {r['clean_text']} | {r['total_ms']:.1f} |\n")
        f.write("\n")

    print(f"\n[Completed Mode asr_dictation]")
    print(f"Saved Markdown: {md_path}")
    print(f"Saved JSON:     {json_path}")
    return payload_json


def main():
    parser = argparse.ArgumentParser(description="Latency benchmark test for dictation, commands_no_tools, commands_with_tools, asr_dictation")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dictation", "commands_no_tools", "commands_with_tools", "asr_dictation", "all"],
        default="all",
        help="Benchmark mode to run (default: all)",
    )
    args = parser.parse_args()

    settings = load_settings()
    vertex_cfg = settings.get("vertex", {})
    asr_cfg = settings.get("asr", {})
    key_file = (V1_DIR / vertex_cfg.get("key_file", "../vertex-key.json")).resolve()
    if not key_file.exists():
        key_file = (WORKSPACE_ROOT / "vertex-key.json").resolve()

    decider = GeminiDecider(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("decider_model", "gemini-2.5-flash"),
    )
    cleanup_cfg = CleanupConfig(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=str(key_file),
        model_name=vertex_cfg.get("cleanup_model", "gemini-2.5-flash"),
    )
    agent = System2Agent(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("agent_model", "gemini-2.5-flash"),
        log_path=V1_DIR / "results" / "tool_calls.log",
    )
    asr_client = HandyASRClient()
    orchestrator = Orchestrator(
        decider=decider,
        cleanup_config=cleanup_cfg,
        settings=settings,
        agent=agent,
    )

    out_dir = V1_DIR / "results"
    audio_path = TESTS_DIR / "audio" / "namaste.wav"
    if not audio_path.exists():
        audio_path = WORKSPACE_ROOT / "namaste.wav"

    modes = ["dictation", "commands_no_tools", "commands_with_tools", "asr_dictation"] if args.mode == "all" else [args.mode]

    for m in modes:
        if m == "asr_dictation":
            run_asr_dictation_latency_test(orchestrator, asr_client, audio_path, out_dir)
        else:
            run_mode_latency_test(m, orchestrator, out_dir)


if __name__ == "__main__":
    main()
