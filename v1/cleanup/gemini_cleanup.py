import asyncio
import concurrent.futures
import logging
from pathlib import Path
import time
from typing import Tuple

from dictation.cleanup.config import CleanupConfig
from dictation.cleanup.engine import WisprFlowCleanupEngine
from dictation.cleanup.gemini_client import GeminiAsiaMumbaiClient


logger = logging.getLogger(__name__)


def _run_async(coro):
    """Safely executes an async coroutine across sync threads or running event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)


class GeminiCleanup:
    """V1 adapter wrapping the complete Wispr Flow dictation cleanup engine."""

    def __init__(
        self,
        project_id: str,
        region: str,
        key_file: str | Path,
        model_name: str = "gemini-2.5-flash",
        timeout_seconds: int = 15,
    ):
        self.config = CleanupConfig(
            project_id=project_id,
            region=region,
            key_file=str(key_file),
            model_name=model_name,
            timeout_seconds=timeout_seconds,
        )
        self.client = GeminiAsiaMumbaiClient(self.config)

    def create_engine(self) -> WisprFlowCleanupEngine:
        """Creates a fresh WisprFlowCleanupEngine using the cached, authenticated Gemini client."""
        engine = WisprFlowCleanupEngine(self.config)
        engine.client = self.client
        return engine

    def clean(self, raw_text: str) -> Tuple[str, float, bool, float, float]:
        """
        Cleans dictated speech using the Wispr Flow sentence segmentation and cleanup engine.
        Returns:
            (cleaned_text, latency_ms, changed, auth_ms, network_ms)
        """
        raw_trimmed = raw_text.strip()
        if not raw_trimmed:
            return "", 0.0, False, 0.0, 0.0

        async def _polish():
            engine = self.create_engine()
            await engine.feed_typed_text(raw_trimmed)
            return await engine.finish_and_finalize(run_final_pass=False)

        start_time = time.perf_counter()
        try:
            doc = _run_async(_polish())
            cleaned_text = (doc.get("polished_text") or "").strip()
        except Exception as exc:
            logger.error("Wispr Flow cleanup failed with error: %s; falling back to raw text", exc)
            cleaned_text = ""

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        if not cleaned_text:
            cleaned_text = raw_trimmed

        changed = cleaned_text != raw_trimmed
        rounded_latency = round(latency_ms, 2)
        return cleaned_text, rounded_latency, changed, 0.0, rounded_latency
