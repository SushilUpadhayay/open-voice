import asyncio
from pathlib import Path
import sys
import time

# Ensure open-voice root is in python path
ROOT = Path(__file__).parents[2].resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dictation.cleanup import WisprFlowCleanupEngine, CleanupConfig

async def main():
    print("=" * 70)
    print("Wispr Flow Sentence-Level Dictation Cleanup (Gemini Asia Mumbai)")
    print("=" * 70)

    config = CleanupConfig()

    def on_sentence_done(event):
        print(f"\n[LLM Background Finish] Sentence #{event['sentence_index']} ({event['latency_ms']}ms):")
        print(f"  Raw:      \"{event['raw_sentence']}\"")
        print(f"  Polished: \"{event['polished_sentence']}\"")

    engine = WisprFlowCleanupEngine(
        config=config,
        on_sentence_polished=on_sentence_done,
    )

    simulated_chunks = [
        ("hello um so basically ", False),
        ("let us meet at two ", False),
        ("no wait actually three pm. ", False),
        ("also please uh bring ", False),
        ("twenty five dollars for the tickets ", True),
        ("do you know uh where the venue is located? ", False),
    ]

    print("\nStreaming raw Nemotron ASR chunks into cleaner...")
    start_time = time.perf_counter()

    for chunk, is_pause in simulated_chunks:
        print(f"[ASR Stream Chunk] '{chunk.strip()}' (pause={is_pause})")
        await engine.feed_stream(chunk, is_pause=is_pause)
        await asyncio.sleep(0.3)

    print("\nFinalizing stream (flushing tail and waiting for background LLM tasks)...")
    result = await engine.finish_and_finalize(run_final_pass=False)
    total_time = (time.perf_counter() - start_time) * 1000.0

    print("\n" + "=" * 70)
    print("FINAL RESULTS")
    print("=" * 70)
    print(f"RAW TRANSCRIPT (Verbatim Nemotron):")
    print(f"  {result['raw_text']}")
    print(f"\nPOLISHED TRANSCRIPT (Wispr Flow Polish):")
    print(f"  {result['polished_text']}")
    print(f"\nTotal Session Time: {total_time:.1f}ms")
    print(f"Total Sentences Polished: {result['sentences_count']}")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())
