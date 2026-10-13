# Modular Voice AI System: Architecture

A voice system where each customer switches capabilities on or off. It covers transcription, cleanup, actions, tools, generated UI and voice replies. This document describes the flow of components and who is responsible for what. It has no code.

---

## 1. Components

| Component | Responsibility | AI or plain code |
|---|---|---|
| **Client** | Captures the mic, finds where speech starts and ends (VAD), shows live partial text, plays audio replies | Plain code |
| **ASR (Indic Conformer)** | Turns each finished speech segment into raw text | AI model |
| **Orchestrator** | Reads the config switches, starts the calls, applies the rules, routes the result | Plain code |
| **JEV / Decider** | Reads text and answers narrow questions. Returns a probability for each option | Small, fast decision model |
| **Cleanup (Gemini)** | Removes filler words, fixes punctuation and self-corrections | LLM |
| **System 2 agent (Gemini)** | Understands a command, chooses and calls tools, writes the reply | LLM with function calling |
| **MCP tools** | Do the real work (calendar, email, and so on) | Tool servers |
| **A2UI** | Describes a UI card to show the user | Output format |
| **TTS (Vertex)** | Turns the reply text into speech | AI model |

---

## 2. The flow

```
 USER SPEAKS
      |
 +----v-----+
 |  CLIENT  |  mic capture + VAD
 +----+-----+
      | finished speech segment
 +----v-----+
 |   ASR    |  Indic Conformer: audio -> raw text  (partial text shown live)
 +----+-----+
      | raw text
 +----v----------------------------------------------+
 | ORCHESTRATOR  (reads the config switches)          |
 |                                                    |
 |  starts these two at the same time:                |
 |  +----------------+     +-------------------+      |
 |  | JEV / DECIDER  |     | GEMINI CLEANUP    |      |
 |  | reads raw text |     | raw -> clean text |      |
 |  | returns:       |     +---------+---------+      |
 |  | - dictation or |               |                |
 |  |   command?     |               |                |
 |  | - confidence   |               |                |
 |  +-------+--------+               |                |
 |          +-----------+------------+                |
 |   branches as soon as the decider answers          |
 +-----------------------+----------------------------+
            +------------+-------------+
       DICTATION                    COMMAND
       (System 1)                   (System 2)
            |                           |
     clean text -> user       +---------v----------+
                              | GEMINI (System 2)  |
                              | understands the    |
                              | request, picks     |
                              | tools              |
                              +---+-----+-----+----+
                                  |     |     |
                               MCP   A2UI   reply text
                               tools  card      |
                                              TTS -> voice
```

A call is skipped when its switch is off: the decider when actions are off, cleanup when cleanup is off.

---

## 3. Step by step

1. **Client.** Captures the mic and cuts speech into segments with VAD. It shows the live partial text as it arrives. It does no thinking.
2. **ASR.** Turns each finished segment into raw text. Raw text can contain "uh", false starts and mistakes.
3. **Orchestrator.** Reads the config switches (actions, cleanup, tools) and decides which calls are needed. It starts them at the same time. It branches as soon as the decider answers: a confident command goes straight to System 2 and the cleanup result is discarded. Anything else waits for cleanup.
4. **JEV / Decider.** Reads the raw text and answers the questions the orchestrator asks. It returns probabilities and does nothing else. It is skipped when actions are off, and the result is then always dictation.
5. **Cleanup.** Runs at the same time as the decider and returns clean text. It is skipped when cleanup is off (the raw text is used). On the command path its result is not used.
6. **System 1 (dictation).** The orchestrator returns the clean text to the user. This is also the path for an unclear answer, low confidence, and actions off. There is one dictation exit, not one per customer.
7. **System 2 (command).** The orchestrator sends the request to the Gemini agent. With tools on, the agent returns one of three outcomes: a tool call, a short question about a missing detail, or a polite refusal when no tool fits. It then writes a short reply, with an A2UI card for a tool call. With tools off, it only explains what it would do. The reply goes to TTS and is spoken.

---

## 4. JEV vs orchestrator

**The JEV only answers questions.** For example:

- Is this dictation or a command?
- Does this text need cleanup?
- Is this speech actually addressed to the assistant? (optional gate)

It never writes text, calls tools or moves data between components.

**The orchestrator does everything else:**

- reads the config switches (actions, cleanup, tools) and builds the list of questions to ask
- starts the JEV, cleanup and other calls, and branches as soon as the JEV answers
- applies rules to the answers (for example, low confidence means treat it as dictation)
- routes the result to System 1 or System 2
- calls TTS and sends output to the client

In short, the JEV says what kind of thing the input is, and the orchestrator decides what happens next.

---

## 5. Where cleanup happens, and whether it comes before or after the JEV

- **Where:** on the backend, after ASR returns a finished segment. Partial words are not cleaned. The client shows raw partial text live and swaps in the cleaned text when the segment is final.
- **Order:** cleanup and the JEV run **in parallel**, and the JEV reads the **raw** text.
  - If the JEV says dictation (or is unsure), the orchestrator waits for the cleaned text.
  - If the JEV says a confident command, the orchestrator does not wait for cleanup. The cleanup result is dropped and the **raw** text goes to the System 2 agent. A strong model can handle a messy request such as "send an email to Ram tomorrow no actually Friday" by itself.
  - If testing shows the agent makes mistakes on messy commands, pass it both the raw and the cleaned text.

---

## 6. How System 1 and System 2 fit

| | System 1: transcription | System 2: actions |
|---|---|---|
| Purpose | Turn speech into clean text | Do something because the user asked |
| Path | ASR, cleanup, text out | ASR, JEV, Gemini agent, MCP, A2UI, TTS |
| Ends with | Clean text | Tool call, UI card, spoken reply |
| Voice reply | No | Yes, if TTS is enabled |

Both share the same front half (client, ASR, orchestrator, JEV). They split at the branch.

---

## 7. What changes when components are switched off

The orchestrator only asks the JEV questions that can change the outcome for that customer.

| Configuration | What the JEV does |
|---|---|
| **Transcription ON, Actions OFF** | Optional. There is one path, so no routing decision. The JEV is only useful for the question "does this text need cleanup?", which skips the cleanup call for text that is already clean. If cleanup always runs, the JEV is not needed. |
| **Transcription ON, Actions ON** | Needed. It answers "dictation or command?" and the orchestrator picks the path. |
| **Transcription OFF, Actions ON** | Not needed for routing, because every utterance goes to System 2. Optionally it acts as a gate: "is this addressed to the assistant?", so background talk does not start the agent. |

Other switches:

| Switch | Effect on the flow |
|---|---|
| Cleanup off | Skip the cleanup call. Raw ASR text goes out as is. |
| MCP off | System 2 can understand and reply but cannot perform actions. |
| A2UI off | No card. Text reply only. |
| TTS off | The reply is shown as text, not spoken. |

**Rule:** the JEV is only used when there is a choice that changes what happens next. That is more than one path, a step that can be skipped, or input that might not deserve processing.

---

## 8. Recommended smallest first prototype

Prove the branch first. Everything else is a placeholder.

```
 audio file or mic -> Indic Conformer -> raw Nepali text
                                     |
                    +----------------+----------------+
              Gemini Flash-Lite                 Gemini cleanup
              (stand-in decider)
              "dictation or command?"
                    +----------------+----------------+
                            orchestrator + config
                         +-----------+-----------+
                    dictation                command
                 show clean text      show "would call System 2"
```

**Include**

- Indic Conformer for ASR (Nepali, Devanagari)
- one stand-in decider: Gemini Flash-Lite with a very short answer, plus a confidence
- one cleanup call
- the orchestrator
- a customer config with the switches: cleanup, actions and tools

**Leave out for now**

- real MCP tools
- A2UI
- TTS
- diarization (speaker labels)
- a real JEV or open decider model

**Test**

- About 30 example sentences: clean dictation, messy dictation, clear commands, messy commands, and unclear ones.
- Measure how often the branch is correct and how long each step takes.

**Success looks like**

- The branch is correct on most sentences.
- Switching actions on and off in the config visibly changes the flow.

**Next, in this order**

1. Real System 2 agent with dummy MCP tools
2. A2UI card
3. TTS
4. Optional "needs cleanup?" question and the "addressed to the assistant?" gate
5. A real decider model behind the same interface, if the stand-in is too slow or costly

The decider is always called through one interface (text and question in, probabilities out). Swapping the stand-in for a real decider later changes nothing else in the system.

---

## 9. Questions to settle when comparing designs

1. Does the decider read raw or cleaned text?
2. Do cleanup and the decision run in parallel or one after the other?
3. Does the System 2 agent get raw text, cleaned text or both?
4. Is cleanup applied to commands at all?
5. Is the JEV also used for cleanup-skipping and for the gate, or only for the dictation-vs-command branch?

## 10. Known limits

- The Indic Conformer endpoint handles Devanagari only. English speech is not supported, and mixed Nepali-English speech needs testing.
- The ASR does not return speaker labels, so diarization needs a separate component if it is required.
- The hosted Jev decider is English-first. Gemini is the decider for the Nepali prototype.
- The V1 test is text-only, so accuracy numbers do not include ASR mistakes.
- Speed numbers in the reference articles are claims from their authors. Measure on your own audio and network.
