# V3 Plan: The Web Demo

**Timeline:** Monday Oct 12 evening to Wednesday Oct 14 (demo on Thursday Oct 15)
**Runs as:** one web page served by the backend, on your laptop
**Language:** Nepali in Devanagari
**Goal:** a person speaks into the page and sees the whole system work: live text, cleaned text, a command result card, a spoken reply, and the time each step took. Three switches on the page change the flow live.

---

## 1. What V3 proves

1. The design works with real speech from a real microphone, not only typed text.
2. The same system behaves differently for different customers by changing three switches (actions, cleanup, tools), with no code change.
3. The measured time of every step is visible, so the speed claim can be checked.

---

## 2. Before V3 starts (about one hour)

1. **Finish the latency tests** (three text modes, then the ASR mode). The numbers are needed for the timing panel and the results page.
2. **Read the V2 raw vs cleaned result.** It decides whether the agent gets raw or cleaned text in the demo.
3. **Check for a Nepali TTS voice** in your Vertex project, and test one sentence. If there is none, use a fallback (see section 9).
4. **Check that ffmpeg is installed** on your laptop, or plan the browser-side wav fallback (see section 5).

---

## 3. Scope

**In V3**

- Backend web service wrapping the existing orchestrator
- One web page: mic, text box, three switches, result area, timing panel
- Audio conversion from browser recording to wav for the ASR
- Result cards for tool calls, questions and refusals
- Vertex TTS for the spoken reply
- A fixed demo script and a backup video

**Not in V3**

- Handy or any desktop client
- Word-by-word live text while speaking (the ASR takes a finished clip)
- Speaker labels
- A real decider model (Jev)
- Real tools or the real A2UI protocol (a simple card format is used)
- Login, deployment, more than one user at a time

---

## 4. Architecture

```
 BROWSER (one page)
   mic / text box / 3 switches
        |  audio or text + switches
        v
 BACKEND (web service)
   audio -> wav (ffmpeg) -> ASR
   orchestrator (existing V2 code)
        |
        v
   JSON result: raw text, cleaned text, branch, outcome,
                card, reply text, timings
        |
        v
 BROWSER shows text, card, timings
        |  reply text
        v
 BACKEND: TTS -> audio -> BROWSER plays it
```

The page never calls Gemini, ASR or TTS directly. All keys stay on the backend.

---

## 5. Backend

| Endpoint | What it does |
|---|---|
| `GET /` | Serves the page. |
| `POST /api/process` | Takes audio or text, plus the switches (actions, cleanup, tools). Runs the orchestrator and returns one JSON result. |
| `POST /api/tts` | Takes the reply text and returns audio. It is separate so the text and card appear first and the voice follows. |

**Result JSON (fields the page needs)**

- raw text, cleaned text
- branch (dictation or command), decider option and confidence
- agent outcome: tool call, question, refusal, or "would do" (tools off)
- tool name and arguments, when there is a tool call
- reply text (Nepali)
- card (see section 7)
- timings in ms: ASR, decider, cleanup, agent, tool call, total

**Audio conversion.** The browser records webm/opus. The backend converts it to 16 kHz mono wav with ffmpeg before the ASR call. Test this first, because every later step depends on it. If ffmpeg is a problem on your laptop, record raw audio in the browser and encode the wav there instead.

**Timings.** Reuse the timing fields from the V2 and latency-test work. Add TTS time and total time seen by the browser, so network delay is visible too.

---

## 6. The page

One page with these parts:

1. **Mic button.** Click to start. It stops by itself after about 1.2 seconds of silence (simple volume check), or when clicked again.
2. **Text box.** Type a Nepali sentence instead of speaking. This is the fallback if the mic fails during the demo.
3. **Three switches.** Actions, Cleanup, Tools. They are sent with every request. A line under them names the mode in plain words (for example, "Dictation only" when actions are off).
4. **Transcript area.** Shows the raw text first, then replaces it with the cleaned text when it is ready.
5. **Result area.** Shows the card for a command (see section 7), or the cleaned text with a copy button for dictation.
6. **Reply line.** The short Nepali reply, with a play button. It plays by itself when TTS is on.
7. **Timing panel.** A small table of the steps and their times for the last request, and the total.
8. **Tool log.** The last few dummy tool calls with their arguments.

Keep the design plain. One column, large text, readable Devanagari font.

---

## 7. Result cards

A simple card format is enough for the demo (the real A2UI protocol can come later). The backend sends a card object and the page draws it.

| Outcome | Card shows |
|---|---|
| Email tool call | Recipient, subject, body, and a "sent (dummy)" label |
| Calendar tool call | Title, date, start time, attendees |
| Reminder tool call | Text, date, time |
| Question | The question, in Nepali |
| Refusal | The refusal sentence, in Nepali |
| Tools off | "Would do" explanation, in Nepali, with a "tools off" label |
| Dictation | Cleaned text and a copy button |

---

## 8. Customer modes on the page

| Switches | What the audience sees |
|---|---|
| Actions off, Cleanup on | Pure dictation. Cleaned text only. No decider time in the panel. |
| Actions on, Tools off, Cleanup on | Commands are recognized and answered in words. No tool call. |
| Actions on, Tools on, Cleanup on | Commands run a dummy tool and show a card. |
| Cleanup off | Raw text is shown as is. No cleanup time in the panel. |

---

## 9. Spoken reply (TTS)

- Use Vertex TTS from the backend, only for the reply sentence of a command.
- Dictation has no spoken reply.
- Check for a Nepali voice first. If there is no usable one, choose in this order: a Hindi voice (it can read Devanagari, but the sound will be off, so say so), or no voice and the reply shown as text.
- Measure the TTS time and show it in the panel.

---

## 10. Stages and schedule

**V3a: backend (Monday evening and Tuesday morning)**

1. Wrap the orchestrator in a web service with `/api/process`.
2. Add audio conversion and test it with a recorded clip from the browser.
3. Return the full result JSON with timings.
4. Test with text input first, then audio.

**V3b: page (Tuesday)**

1. Page with mic, text box and switches.
2. Transcript area (raw, then cleaned), result area and timing panel.
3. Silence detection for the mic.

**V3c: commands, cards and voice (Wednesday morning)**

1. Result cards for every outcome.
2. TTS endpoint and the play button.
3. Tool log.

**V4: harden and rehearse (Wednesday afternoon)**

1. Run the demo script five times and fix whatever fails.
2. Record a backup video of a good run.
3. One slide with the architecture and the measured numbers.

**Thursday:** demo.

---

## 11. Demo script (about 8 inputs)

1. Actions off: a clean dictation sentence.
2. Actions off: a messy dictation sentence, to show cleanup.
3. Switch actions on, tools off: a command sentence. Shows "would do".
4. Switch tools on: a calendar command.
5. An email command with a self-correction ("भोलि होइन शुक्रबार").
6. A reminder command.
7. A command with a missing detail, to show the agent asking.
8. A request with no matching tool, to show the refusal.

Use sentences you tested, spoken by you, and keep the text box ready as a fallback for each one.

---

## 12. What to measure

| Metric | Why |
|---|---|
| Time per step on the page | The speed claim, shown live |
| Total time from end of speech to text | Dictation feel |
| Total time from end of speech to the card | Command feel |
| Time to the first spoken word | Voice feel |
| Failures in five full rehearsals | Is the demo reliable? |

---

## 13. If time runs short, cut in this order

1. TTS (show the reply as text).
2. The timing panel (use the latency test tables on a slide).
3. Cards (show the reply as plain text).
4. The mic (use the text box and one pre-recorded clip).

Do not cut: the three switches and one real tool call. Those are the proof of the design.

---

## 14. Risks

| Risk | What to do |
|---|---|
| Browser audio will not convert to wav | Test in the first hour of V3a. Use the browser-side wav fallback. |
| No Nepali TTS voice | Use the fallback order in section 9. |
| Slow network or Vertex errors during the demo | Keep the backup video and the text box. Keep the retry logic from V1. |
| Ambient noise ends the recording too soon or never | Use a manual stop button as well as silence detection. |
| Ambiguous sentences give odd results live | Stick to the tested demo script. |
| The Indic ASR misspells a spoken word | Use the text box for that sentence. Mention the limit honestly. |
| Key or secret shown on screen | Keep all keys on the backend. Never print them. |

---

## 15. Done when

- A spoken Nepali sentence goes from the mic to text on the page, with the raw text replaced by the cleaned text.
- The three switches visibly change the flow and the timing panel.
- A command with tools on shows a card, a log line and a spoken reply.
- A missing-detail command and a no-tool command show a question and a refusal.
- The demo script runs five times in a row without a failure.
- A backup video exists.

---

## 16. What comes after the demo

- A real decider (Jev or an open model fine-tuned on Nepali) behind the same interface
- Streaming ASR for live words
- Real tools and the real A2UI protocol
- Handy or another desktop client
- "Needs cleanup?" skip and the "addressed to the assistant?" gate
