from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple
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

from v1.config import load_settings, load_customer_config
from v1.asr.client import IndicConformerClient
from v1.decider.gemini_decider import GeminiDecider
from v1.cleanup.gemini_cleanup import GeminiCleanup
from v1.agent.system2 import System2Agent
from v1.orchestrator.runner import Orchestrator


def get_audio_duration_seconds(file_path: Path) -> float:
    try:
        with wave.open(str(file_path), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate) if rate > 0 else 0.0
    except Exception:
        return 0.0


def measure_call_series(
    call_fn: Callable[[], Tuple[str, Any]],
    runs: int = 5,
    sleep_between: float = 0.4,
) -> Dict[str, Any]:
    """
    Executes call_fn `runs` times, skipping the first run as warm-up.
    Returns timing statistics and recorded output text of each run.
    """
    latencies: List[float] = []
    outputs: List[str] = []
    raw_results: List[Any] = []

    for i in range(runs):
        t0 = time.perf_counter()
        out_str, raw_obj = call_fn()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        latencies.append(round(elapsed_ms, 2))
        outputs.append(out_str)
        raw_results.append(raw_obj)

        if i < runs - 1:
            time.sleep(sleep_between)

    warmup_latency = latencies[0]
    warmup_output = outputs[0]
    measured_latencies = latencies[1:]  # Skip warm-up

    min_ms = min(measured_latencies)
    median_ms = statistics.median(measured_latencies)
    mean_ms = statistics.mean(measured_latencies)
    max_ms = max(measured_latencies)

    final_output = outputs[-1]

    return {
        "runs_total": runs,
        "warmup_ms": warmup_latency,
        "warmup_output": warmup_output,
        "measured_ms": measured_latencies,
        "min_ms": round(min_ms, 2),
        "median_ms": round(median_ms, 2),
        "mean_ms": round(mean_ms, 2),
        "max_ms": round(max_ms, 2),
        "output": final_output,
        "output_len": len(final_output),
        "all_outputs": outputs,
    }


def run_latency_benchmark() -> Tuple[Path, Path]:
    settings = load_settings()
    vertex_cfg = settings.get("vertex", {})
    asr_cfg = settings.get("asr", {})

    key_file = (V1_DIR / vertex_cfg.get("key_file", "../vertex-key.json")).resolve()
    if not key_file.exists():
        key_file = (WORKSPACE_ROOT / "vertex-key.json").resolve()

    # Initialize components
    asr_client = IndicConformerClient(
        endpoint=asr_cfg["endpoint"],
        timeout_seconds=asr_cfg.get("timeout_seconds", 30),
    )
    decider = GeminiDecider(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("decider_model", "gemini-2.5-flash"),
    )
    cleanup = GeminiCleanup(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("cleanup_model", "gemini-2.5-flash"),
    )
    agent = System2Agent(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("agent_model", "gemini-2.5-flash"),
        log_path=V1_DIR / "results" / "tool_calls.log",
    )
    orchestrator = Orchestrator(
        decider=decider,
        cleanup=cleanup,
        settings=settings,
        agent=agent,
    )

    # Select 10 diverse sentences from sentences.csv
    sentences_file = TESTS_DIR / "sentences.csv"
    with open(sentences_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    def pick_by_type(target_type: str, count: int) -> List[Dict[str, str]]:
        matches = [r for r in rows if r["type"] == target_type]
        return matches[:count]

    selected_sentences: List[Dict[str, str]] = []
    selected_sentences.extend(pick_by_type("clean_dictation", 2))
    selected_sentences.extend(pick_by_type("messy_dictation", 2))
    selected_sentences.extend(pick_by_type("clear_command", 2))
    selected_sentences.extend(pick_by_type("messy_command", 2))
    selected_sentences.extend(pick_by_type("ambiguous", 2))

    print(f"\n==================================================")
    print(f"Running Open Voice Component Latency Benchmark")
    print(f"Sentences count: {len(selected_sentences)}")
    print(f"Runs per item: 5 (run 1 is warm-up, runs 2-5 measured)")
    print(f"==================================================")

    # 1. Measure ASR on every audio file in tests/audio
    print("\n--- 1. Measuring ASR ---")
    audio_dir = TESTS_DIR / "audio"
    audio_files = sorted(list(audio_dir.glob("*.wav")))
    if not audio_files:
        root_wav = WORKSPACE_ROOT / "namaste.wav"
        if root_wav.exists():
            audio_files = [root_wav]

    asr_results: List[Dict[str, Any]] = []
    for wav_path in audio_files:
        duration_s = get_audio_duration_seconds(wav_path)
        print(f"[ASR] Measuring {wav_path.name} (Duration: {duration_s:.2f}s)...")
        stats = measure_call_series(lambda: (asr_client.transcribe(wav_path)[0], None))
        asr_results.append({
            "file": wav_path.name,
            "duration_s": round(duration_s, 2),
            "input": str(wav_path.name),
            "input_len": len(wav_path.name),
            **stats,
        })
        print(f"      -> Min: {stats['min_ms']}ms, Median: {stats['median_ms']}ms, Mean: {stats['mean_ms']}ms, Max: {stats['max_ms']}ms")

    # 2. Measure Decider
    print("\n--- 2. Measuring Gemini Decider ---")
    decider_results: List[Dict[str, Any]] = []
    for idx, item in enumerate(selected_sentences, 1):
        text = item["text"]
        print(f"[Decider {idx:02d}/10] ({item['type']}) {text[:30]}...")
        def make_decider_runner(t: str):
            def run():
                res = decider.decide(t)
                return f"{res.option} (conf: {res.confidence:.4f})", res
            return run
        stats = measure_call_series(make_decider_runner(text))
        decider_results.append({
            "text": text,
            "type": item["type"],
            "input_len": len(text),
            **stats,
        })
        print(f"            -> Median: {stats['median_ms']}ms (Min: {stats['min_ms']}ms, Max: {stats['max_ms']}ms)")

    # 3. Measure Cleanup
    print("\n--- 3. Measuring Gemini Cleanup ---")
    cleanup_results: List[Dict[str, Any]] = []
    for idx, item in enumerate(selected_sentences, 1):
        text = item["text"]
        print(f"[Cleanup {idx:02d}/10] ({item['type']}) {text[:30]}...")
        def make_cleanup_runner(t: str):
            def run():
                cleaned, _, _, _, _ = cleanup.clean(t)
                return cleaned, None
            return run
        stats = measure_call_series(make_cleanup_runner(text))
        cleanup_results.append({
            "text": text,
            "type": item["type"],
            "input_len": len(text),
            **stats,
        })
        print(f"            -> Median: {stats['median_ms']}ms (Min: {stats['min_ms']}ms, Max: {stats['max_ms']}ms)")

    # 4. Measure System 2 Agent
    print("\n--- 4. Measuring System 2 Agent ---")
    fixed_ref_dt = datetime(2026, 10, 12, 9, 0, 0)
    agent_results: List[Dict[str, Any]] = []
    for idx, item in enumerate(selected_sentences, 1):
        text = item["text"]
        print(f"[Agent {idx:02d}/10] ({item['type']}) {text[:30]}...")
        def make_agent_runner(t: str):
            def run():
                res = agent.process(text=t, tools_enabled=True, reference_datetime=fixed_ref_dt)
                return res.reply, res
            return run
        stats = measure_call_series(make_agent_runner(text))
        agent_results.append({
            "text": text,
            "type": item["type"],
            "input_len": len(text),
            **stats,
        })
        print(f"          -> Median: {stats['median_ms']}ms (Min: {stats['min_ms']}ms, Max: {stats['max_ms']}ms)")

    # 5. Measure Full Orchestrator Path: Dictation vs Command
    print("\n--- 5. Measuring Full Orchestrator Path ---")
    dictation_items = [s for s in selected_sentences if "dictation" in s["type"] or s["type"] == "ambiguous"]
    command_items = [s for s in selected_sentences if "command" in s["type"]]

    orch_dict_results: List[Dict[str, Any]] = []
    for idx, item in enumerate(dictation_items, 1):
        text = item["text"]
        print(f"[Orchestrator Dictation {idx}/{len(dictation_items)}] {text[:30]}...")
        def make_orch_dict_runner(t: str):
            def run():
                res = orchestrator.process(raw_text=t, actions=True, cleanup=True, tools=True)
                return res.output_text, res
            return run
        stats = measure_call_series(make_orch_dict_runner(text))
        orch_dict_results.append({
            "text": text,
            "type": item["type"],
            "input_len": len(text),
            **stats,
        })
        print(f"            -> Median: {stats['median_ms']}ms (Min: {stats['min_ms']}ms, Max: {stats['max_ms']}ms)")

    orch_cmd_results: List[Dict[str, Any]] = []
    for idx, item in enumerate(command_items, 1):
        text = item["text"]
        print(f"[Orchestrator Command {idx}/{len(command_items)}] {text[:30]}...")
        def make_orch_cmd_runner(t: str):
            def run():
                res = orchestrator.process(raw_text=t, actions=True, cleanup=True, tools=True, reference_datetime=fixed_ref_dt)
                return res.output_text, res
            return run
        stats = measure_call_series(make_orch_cmd_runner(text))
        orch_cmd_results.append({
            "text": text,
            "type": item["type"],
            "input_len": len(text),
            **stats,
        })
        print(f"          -> Median: {stats['median_ms']}ms (Min: {stats['min_ms']}ms, Max: {stats['max_ms']}ms)")

    # Compile summaries
    def aggregate_component(data_list: List[Dict[str, Any]]) -> Dict[str, float]:
        all_measured = [ms for item in data_list for ms in item["measured_ms"]]
        if not all_measured:
            return {"min_ms": 0.0, "median_ms": 0.0, "mean_ms": 0.0, "max_ms": 0.0}
        return {
            "min_ms": round(min(all_measured), 2),
            "median_ms": round(statistics.median(all_measured), 2),
            "mean_ms": round(statistics.mean(all_measured), 2),
            "max_ms": round(max(all_measured), 2),
        }

    summary_metrics = {
        "ASR": aggregate_component(asr_results),
        "Decider": aggregate_component(decider_results),
        "Cleanup": aggregate_component(cleanup_results),
        "System2_Agent": aggregate_component(agent_results),
        "Orchestrator_Dictation": aggregate_component(orch_dict_results),
        "Orchestrator_Command": aggregate_component(orch_cmd_results),
    }

    # Prepare output files
    nepal_tz = timezone(timedelta(hours=5, minutes=45))
    timestamp = datetime.now(nepal_tz).strftime("%Y%m%d_%H%M%S")
    out_dir = V1_DIR / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"latency_{timestamp}.json"
    md_path = out_dir / f"latency_{timestamp}.md"

    payload_json = {
        "timestamp": timestamp,
        "summary": summary_metrics,
        "asr": asr_results,
        "decider": decider_results,
        "cleanup": cleanup_results,
        "agent": agent_results,
        "orchestrator_dictation": orch_dict_results,
        "orchestrator_command": orch_cmd_results,
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload_json, f, ensure_ascii=False, indent=2)

    # Write Markdown
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# Latency Benchmark Report\n\n")
        f.write(f"- **Timestamp:** {timestamp}\n")
        f.write(f"- **Protocol:** 5 runs per item (Run 1 warm-up skipped; Runs 2–5 recorded for min/median/mean/max).\n\n")

        f.write("## 1. Summary Comparison\n\n")
        f.write("| Component / Path | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|\n")
        for comp_name, metrics in summary_metrics.items():
            f.write(f"| **{comp_name}** | {metrics['min_ms']:.1f} | {metrics['median_ms']:.1f} | {metrics['mean_ms']:.1f} | {metrics['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 2. ASR (Indic Conformer)\n\n")
        f.write("| File | Audio Duration | In Len | Out Len | Output Text | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in asr_results:
            f.write(f"| `{r['file']}` | {r['duration_s']}s | {r['input_len']} | {r['output_len']} | {r['output']} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 3. Decider (Gemini)\n\n")
        f.write("| # | Input Text | Type | In Len | Out Len | Output | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(decider_results, 1):
            f.write(f"| {idx} | `{r['text']}` | {r['type']} | {r['input_len']} | {r['output_len']} | {r['output']} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 4. Cleanup (Gemini)\n\n")
        f.write("| # | Input Text | Type | In Len | Out Len | Cleaned Text | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(cleanup_results, 1):
            clean_txt = r['output'].replace('\n', ' ')
            f.write(f"| {idx} | `{r['text']}` | {r['type']} | {r['input_len']} | {r['output_len']} | {clean_txt} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 5. System 2 Agent (Gemini Function Calling)\n\n")
        f.write("| # | Input Text | Type | In Len | Out Len | Agent Reply | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(agent_results, 1):
            agent_reply = r['output'].replace('\n', ' ')
            f.write(f"| {idx} | `{r['text']}` | {r['type']} | {r['input_len']} | {r['output_len']} | {agent_reply} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 6. Full Orchestrator Path: Dictation\n\n")
        f.write("| # | Input Text | Type | In Len | Out Len | Output Text | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(orch_dict_results, 1):
            out_txt = r['output'].replace('\n', ' ')
            f.write(f"| {idx} | `{r['text']}` | {r['type']} | {r['input_len']} | {r['output_len']} | {out_txt} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

        f.write("## 7. Full Orchestrator Path: Command\n\n")
        f.write("| # | Input Text | Type | In Len | Out Len | Final Output | Min (ms) | Median (ms) | Mean (ms) | Max (ms) |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|\n")
        for idx, r in enumerate(orch_cmd_results, 1):
            out_txt = r['output'].replace('\n', ' ')
            f.write(f"| {idx} | `{r['text']}` | {r['type']} | {r['input_len']} | {r['output_len']} | {out_txt} | {r['min_ms']:.1f} | {r['median_ms']:.1f} | {r['mean_ms']:.1f} | {r['max_ms']:.1f} |\n")
        f.write("\n")

    print(f"\n[Benchmark Complete]")
    print(f"Saved Markdown report: {md_path}")
    print(f"Saved JSON data:      {json_path}")
    return md_path, json_path


if __name__ == "__main__":
    run_latency_benchmark()
