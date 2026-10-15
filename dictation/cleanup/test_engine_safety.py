import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

import requests

from .config import CleanupConfig
from .engine import WisprFlowCleanupEngine
from .gemini_client import GeminiAsiaMumbaiClient
from .prompts import WISPR_FLOW_SENTENCE_INSTRUCTION


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class CleanupSafetyTests(unittest.IsolatedAsyncioTestCase):
    def make_engine(self, response_text):
        engine = WisprFlowCleanupEngine(config=CleanupConfig())
        engine.client.generate_async = AsyncMock(
            return_value=(response_text, 12.0, 4.0)
        )
        return engine

    async def feed_one_sentence(self, engine, sentence):
        events = []
        engine.on_sentence_polished = events.append
        await engine.feed_stream(sentence, is_pause=True)
        await asyncio.gather(*engine._background_tasks)
        return events[-1]

    async def test_http_error_and_timeout_fall_back_without_context_leak(self):
        for error_type, post_behavior in (
            ("HTTPStatusError", Mock(return_value=_Response(429))),
            ("Timeout", Mock(side_effect=requests.Timeout("test timeout"))),
        ):
            with self.subTest(error_type=error_type):
                config = CleanupConfig()
                client = GeminiAsiaMumbaiClient(config)
                client.endpoint_url = "https://test.invalid"
                client.credentials = None
                engine = WisprFlowCleanupEngine(config=config)
                engine.client = client
                captured_requests = []
                original_generate_async = client.generate_async
                post_count = 0
                first_raw = "I will keep testing now."
                second_raw = "The follow up sentence is next."

                async def capture_request(system_instruction, user_prompt):
                    captured_requests.append(user_prompt)
                    return await original_generate_async(system_instruction, user_prompt)

                def post(*_args, **_kwargs):
                    nonlocal post_count
                    post_count += 1
                    if post_count == 1:
                        return post_behavior(*_args, **_kwargs)
                    self.assertEqual(_args[0], client.endpoint_url)
                    self.assertEqual(
                        _kwargs["json"]["contents"][0]["parts"][0]["text"],
                        captured_requests[-1],
                    )
                    return _Response(
                        200,
                        {
                            "candidates": [
                                {
                                    "content": {
                                        "parts": [{"text": second_raw}]
                                    }
                                }
                            ]
                        },
                    )

                client.generate_async = capture_request
                client.session.post = post
                first_events = []
                engine.on_sentence_polished = first_events.append

                with self.assertLogs(
                    "dictation.cleanup.gemini_client",
                    level="ERROR",
                ) as logs:
                    await engine.feed_stream(first_raw, is_pause=True)
                    await asyncio.gather(*engine._background_tasks)

                self.assertEqual(first_events[-1]["polished_sentence"], first_raw)
                self.assertEqual(engine.polished_sentences, [])
                self.assertNotIn("Context:", first_events[-1]["polished_sentence"])
                self.assertNotIn("Raw Sentence:", first_events[-1]["polished_sentence"])
                self.assertTrue(
                    any(f"error_type={error_type}" in line for line in logs.output)
                )

                second_events = []
                engine.on_sentence_polished = second_events.append
                await engine.feed_stream(second_raw, is_pause=True)
                await asyncio.gather(*engine._background_tasks)

                self.assertEqual(second_events[-1]["polished_sentence"], second_raw)
                self.assertEqual(
                    captured_requests,
                    [
                        f"<speech_to_clean>{first_raw}</speech_to_clean>",
                        f"<speech_to_clean>{second_raw}</speech_to_clean>",
                    ],
                )
                self.assertNotIn(first_raw, captured_requests[1])
                self.assertEqual(engine.polished_sentences, [second_raw])

    async def test_imperative_stays_imperative(self):
        raw = "turn on the living room lights and set temperature to 72"
        expected = "Turn on the living room lights and set the temperature to 72."
        engine = self.make_engine(expected)

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], expected)
        self.assertFalse(event["polished_sentence"].startswith("I turned"))
        self.assertIn("Never change verb tense, mood", WISPR_FLOW_SENTENCE_INSTRUCTION)

    async def test_short_sentence_keeps_its_wording(self):
        raw = "Next sentence is short."
        engine = self.make_engine(raw)

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], raw)

    async def test_rejected_output_uses_raw_text_without_saving_as_polished(self):
        raw = "Please close the window."
        engine = self.make_engine(f"<speech_to_clean>{raw}</speech_to_clean>")

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], raw)
        self.assertEqual(engine.polished_sentences, [])
        self.assertEqual(engine.get_live_state()["completed_sentences"], [raw])
        result = await engine.finish_and_finalize(run_final_pass=False)
        self.assertEqual(result["sentences"], [raw])

    async def test_normal_speech_containing_context_is_not_rejected(self):
        raw = "The context: clues were helpful."
        engine = self.make_engine(raw)

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], raw)

    async def test_clean_sentence_prefix_is_stripped(self):
        raw = "Please close the window."
        engine = self.make_engine(f"Clean sentence: {raw}")

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], raw)

    async def test_excessively_long_output_falls_back_to_raw(self):
        raw = "Please close the window."
        engine = self.make_engine(
            "Please close the window now and then explain all the details again."
        )

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], raw)
        self.assertEqual(engine.polished_sentences, [])

    async def test_speech_wrapper_tags_are_removed_before_sending(self):
        raw = "<speech_to_clean>hello</speech_to_clean> there."
        engine = self.make_engine("Hello there.")

        event = await self.feed_one_sentence(engine, raw)

        self.assertEqual(event["polished_sentence"], "Hello there.")
        request = engine.client.generate_async.await_args.kwargs["user_prompt"]
        self.assertEqual(request, "<speech_to_clean>hello there.</speech_to_clean>")

    def test_client_returns_empty_for_http_error_and_empty_candidate(self):
        client = GeminiAsiaMumbaiClient(CleanupConfig())
        client.endpoint_url = "https://test.invalid"
        client.credentials = None
        client.session.post = Mock(return_value=_Response(429))

        with self.assertLogs(
            "dictation.cleanup.gemini_client",
            level="ERROR",
        ) as logs:
            response = client.generate("system", "user prompt")

        self.assertEqual(response[0], "")
        self.assertIn("status_code=429", logs.output[0])
        self.assertIn("error_type=HTTPStatusError", logs.output[0])

        client.session.post = Mock(return_value=_Response(
            200,
            {"candidates": []},
        ))
        with self.assertLogs("dictation.cleanup.gemini_client", level="ERROR"):
            response = client.generate("system", "user prompt")
        self.assertEqual(response[0], "")

    def test_client_rejects_max_tokens_and_safety_finishes(self):
        client = GeminiAsiaMumbaiClient(CleanupConfig())
        client.endpoint_url = "https://test.invalid"
        client.credentials = None
        for finish_reason in ("MAX_TOKENS", "SAFETY"):
            with self.subTest(finish_reason=finish_reason):
                client.session.post = Mock(return_value=_Response(
                    200,
                    {
                        "candidates": [
                            {
                                "finishReason": finish_reason,
                                "content": {"parts": [{"text": "partial"}]},
                            }
                        ]
                    },
                ))
                with self.assertLogs(
                    "dictation.cleanup.gemini_client",
                    level="ERROR",
                ):
                    response = client.generate("system", "user prompt")
                self.assertEqual(response[0], "")


if __name__ == "__main__":
    unittest.main()
