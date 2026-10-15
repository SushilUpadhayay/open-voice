from pathlib import Path
import argparse
import sys

# Ensure root of project is importable
CURRENT_DIR = Path(__file__).parent.resolve()
WORKSPACE_ROOT = CURRENT_DIR.parent.resolve()
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

try:
    import v1
    sys.modules.setdefault("V1", v1)
except ImportError:
    pass

from v1.config import load_settings, load_customer_config
from v1.asr.client import NemotronASRAdapter
from v1.decider.gemini_decider import GeminiDecider
from v1.cleanup.gemini_cleanup import GeminiCleanup
from v1.agent.system2 import System2Agent
from v1.orchestrator.runner import Orchestrator
from v1.tests.test_runner import run_test_suite



def build_system(settings: dict) -> tuple[NemotronASRAdapter, Orchestrator]:
    vertex_cfg = settings.get("vertex", {})
    dictation_cfg = settings.get("dictation", {})

    key_file = Path(vertex_cfg.get("key_file", "../vertex-key.json"))
    if not key_file.is_absolute():
        resolved_key = (CURRENT_DIR / key_file).resolve()
        if not resolved_key.exists():
            resolved_key = (WORKSPACE_ROOT / "vertex-key.json").resolve()
        key_file = resolved_key


    decider = GeminiDecider(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("decider_model", "gemini-2.5-flash-lite"),
    )

    cleanup = GeminiCleanup(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("cleanup_model", "gemini-2.5-flash"),
        timeout_seconds=dictation_cfg.get("timeout_seconds", 15),
    )

    agent = System2Agent(
        project_id=vertex_cfg["project_id"],
        region=vertex_cfg["region"],
        key_file=key_file,
        model_name=vertex_cfg.get("agent_model", "gemini-2.5-flash"),
    )

    orchestrator = Orchestrator(
        decider=decider,
        cleanup=cleanup,
        settings=settings,
        agent=agent,
    )

    asr_client = NemotronASRAdapter(
        model_id=dictation_cfg.get("model_id"),
        sample_rate=dictation_cfg.get("sample_rate", 16000),
    )

    return asr_client, orchestrator


def main():
    parser = argparse.ArgumentParser(
        description="V1 Modular English Voice AI Pipeline - The Branch"
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Input English text or path to a .wav audio file",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="customer_b",
        help="Customer config name (customer_a, customer_b) or path to YAML file",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run the benchmark suite against tests/sentences.csv",
    )
    parser.add_argument(
        "--no-order-test",
        action="store_true",
        help="Skip the reversed-order stability pass in test mode",
    )

    args = parser.parse_args()

    # Load settings & customer config
    settings = load_settings()
    customer_cfg = load_customer_config(args.config)

    asr_client, orchestrator = build_system(settings)

    if args.test:
        csv_path = CURRENT_DIR / "tests" / "sentences.csv"
        results_dir = CURRENT_DIR / "results"
        run_test_suite(
            orchestrator=orchestrator,
            customer_config=customer_cfg,
            csv_path=csv_path,
            output_dir=results_dir,
            run_order_test=not args.no_order_test,
        )
        return

    if not args.input:
        parser.print_help()
        print("\nError: Please provide either --input <text|wav_path> or --test")
        sys.exit(1)

    input_str = args.input.strip()
    asr_latency_ms = 0.0

    # Check if input is a wav audio file
    candidate_audio = Path(input_str)
    if candidate_audio.exists() and candidate_audio.suffix.lower() == ".wav":
        print(f"[ASR] Transcribing audio: {candidate_audio} ...")
        raw_text, asr_latency_ms = asr_client.transcribe(candidate_audio)
        print(f"[ASR] Transcribed text ({asr_latency_ms:.1f}ms): {raw_text}")
    else:
        raw_text = input_str

    print(f"\n[Orchestrator] Processing for customer '{customer_cfg.get('name')}'...")
    print(f"  Actions enabled: {customer_cfg.get('actions', False)}")
    print(f"  Cleanup enabled: {customer_cfg.get('cleanup', True)}")
    print(f"  Tools enabled:   {customer_cfg.get('tools', True)}")

    result = orchestrator.process(
        raw_text=raw_text,
        actions=customer_cfg.get("actions", False),
        cleanup=customer_cfg.get("cleanup", True),
        tools=customer_cfg.get("tools", True),
        asr_latency_ms=asr_latency_ms,
    )

    print("\n" + "=" * 50)
    print(f"BRANCH TAKEN: {result.branch.upper()}")
    print("=" * 50)
    print(f"Raw Input:       {result.raw_text}")
    if result.decision:
        print(f"Decider Choice:  {result.decision.option} (confidence: {result.decision.confidence:.2f})")
        if result.decision.option_probabilities:
            print(f"Probabilities:   {result.decision.option_probabilities}")
    else:
        print("Decider Choice:  [Skipped due to config]")

    if result.cleaned_text:
        print(f"Cleaned Text:    {result.cleaned_text} (changed={result.cleanup_changed})")
    if result.cleanup_discarded:
        print("Cleanup Status:  Discarded (early command branch taken)")
    
    if result.agent_result:
        print(f"Agent Action:    {'Tool Executed' if result.agent_result.action_taken else 'No Tool Call'}")
        if result.agent_result.tool_name:
            print(f"Tool Called:     {result.agent_result.tool_name}")
            print(f"Tool Arguments:  {result.agent_result.tool_args}")
            print(f"Tool Result:     {result.agent_result.tool_result}")
        elif result.agent_result.clarification_asked:
            print("Agent Note:      Clarification question asked (missing details)")
        elif result.agent_result.refusal:
            print("Agent Note:      Request refused (no matching tool)")

    print(f"Final Output:    {result.output_text}")
    print("\n[Timings]")
    if result.asr_latency_ms > 0:
        print(f"  ASR:           {result.asr_latency_ms:.1f} ms")
    print(f"  Decider:       {result.decider_latency_ms:.1f} ms")
    print(f"  Cleanup:       {result.cleanup_latency_ms:.1f} ms")
    if result.agent_latency_ms > 0:
        print(f"  Agent:         {result.agent_latency_ms:.1f} ms")
    print(f"  Total:         {result.total_latency_ms:.1f} ms")
    print("=" * 50)


if __name__ == "__main__":
    main()
