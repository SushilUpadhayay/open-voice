# V1 Plan: The Branch (Nepali)

**Timeline:** Thursday Oct 8 to Friday Oct 9
**Runs as:** command line, no UI
**Language:** Nepali in Devanagari (the only ASR available handles Devanagari)
**Goal:** prove that one piece of recognized speech can be routed to the right path by a decider, under a customer config.

---

## 1. What V1 proves

1. Nepali speech can be turned into raw text with the Indic Conformer endpoint.
2. A decider can tell dictation from a command with useful accuracy.
3. Cleanup and the decision can run at the same time.
4. A customer config changes the flow (actions on or off, cleanup on or off).
5. The decider can be swapped behind one interface without touching the rest.

---

## 2. Scope

**In V1**

- Indic Conformer ASR call (audio file in, raw Nepali text out)
- Decider interface and one implementation: Gemini Flash-Lite as the stand-in
- Gemini cleanup call
- Orchestrator with a customer config
- Dictation path: show clean text
- Command path: placeholder only, shows "would call System 2" with the text
- A labeled Nepali test set and a report of accuracy and timing

**Not in V1**

- System 2 agent, MCP tools, A2UI, TTS
- Web page or mic capture
- Diarization
- Real JEV (planned for V2, only if it handles Nepali; the hosted one is English-first)
- "Needs cleanup?" question and the "addressed to the assistant?" gate

---

## 3. Flow

```
 audio file -> Indic Conformer -> raw Nepali text
                                      |
              orchestrator reads customer config
                                      |
                 +--------------------+--------------------+
        DECIDER (Gemini Flash-Lite)              CLEANUP (Gemini)
        "dictation or command?"                  raw -> clean text
                 +--------------------+--------------------+
                                      |
                            orchestrator branches
                       +--------------+--------------+
                  dictation                      command
               print clean text        print "would call System 2"
                                        (with the raw text)
```

Rules the orchestrator applies:

- Actions off: skip the decider and treat everything as dictation.
- Cleanup off: skip the cleanup call and output the raw text.
- Decider says "unclear" or confidence is below the threshold: treat as dictation (the safe path).
- Decider says command: drop the cleanup result and send the raw text to the command placeholder.

---

## 4. Components

| Component | What it does in V1 |
|---|---|
| **ASR client** | Sends a wav file to the Indic Conformer endpoint and returns the text. See section 5. |
| **Decider interface** | One function: text and a question with options go in, a probability per option comes out. Every decider implements it. |
| **Gemini decider** | Gemini Flash-Lite on Vertex. Very short output, thinking off, temperature 0. Includes an "unclear" option. |
| **Cleanup** | Gemini call that removes Nepali filler words and fixes punctuation and self-corrections. Told to return the text unchanged if it is already clean. |
| **Orchestrator** | Reads the config, runs the decider and cleanup in parallel, applies the rules above. |
| **Config** | A small file per customer with the two switches (cleanup, actions), the decider confidence threshold, and endpoints and model names. |
| **Test runner** | Runs the labeled sentences, records the results and timings, and prints a summary. |

---

## 5. ASR call (confirmed working)

```
POST http://45.115.219.97:20009/indic/transcribe/
Form field: file = <wav file>
Response:   {"text": " नमस्ते मेरो नाम सुशील हो"}
```

Notes for the ASR client:

- The request is a multipart form with one field named `file`.
- The response is JSON with a `text` field.
- The text can start with a space, so trim it.
- This is not the standard OpenAI path or field set (no model field has been needed so far), so the client is written for this exact call.
- Only wav has been tested. Check other formats and the maximum clip length early, because the real client will need them.
- Put the URL in the config, not in the code.
- Nepali is the language to test. Use Devanagari sentences only.

---

## 6. Decider details

**The question:** "Is this text something the user wants typed out, or a command for an assistant?"

**Options:** dictation, command, unclear.

**Prompt rules**

- Write the instructions in English and the examples in Nepali. Gemini understands both.
- One narrow question only.
- Short answer, a single option label.
- Include the "unclear" option.
- Give 3 or 4 Nepali examples of each option in the prompt.
- Keep the prompt identical on every call.

**Confidence.** Two ways, in order of preference:

1. If the Gemini model on Vertex exposes token probabilities, read the probability of the answer label.
2. Otherwise, ask the model to also return a confidence from 0 to 1 and treat it as a rough signal only.

Check which one your model supports first.

**Order test.** Run the test set twice with the option order reversed. If answers change, the decider is unstable and the prompt needs work.

---

## 7. Test set (Nepali, first draft)

30 sentences in Devanagari. Have a Nepali speaker check them before you record. For each one, expected path is what the branch should do.

**Clean dictation (expected: dictation)**

1. बैठकको नोट तयार भइसकेको छ।
2. हामीले आज रिपोर्ट बुझाउनुपर्छ।
3. भोलि मौसम राम्रो हुने अनुमान छ।
4. मलाई यो प्रस्ताव मन परेको छ।
5. ग्राहकले भुक्तानी गरिसकेका छन्।
6. नयाँ अफिस बानेश्वरमा छ।

**Messy dictation (expected: dictation, cleanup should change it)**

7. ए... त्यो रिपोर्ट के भन्छन् तयार भइसक्यो जस्तो छ।
8. हजुर हजुर मैले भन्न खोजेको चाहिँ आज बैठक सकियो।
9. उम् हामी भोलि होइन पर्सि भेट्छौं।
10. त्यो काम त्यो काम अहिलेसम्म भएको छैन जस्तो लाग्छ।
11. अनि ए बजेट बढाउनुपर्ने हुन्छ कि क्या हो।
12. मेरो मतलब चाहिँ सबै सामान आइसकेका छन्।

**Clear commands (expected: command)**

13. रामलाई रिपोर्टको बारेमा इमेल पठाऊ।
14. भोलि बिहान दश बजे बैठक राख।
15. मलाई साँझ पाँच बजे सम्झाऊ।
16. सिताको नम्बर खोज।
17. आजको कार्यक्रम देखाऊ।
18. शुक्रबारको बैठक रद्द गर।

**Messy commands (expected: command)**

19. ए रामलाई इमेल पठाऊ भोलि होइन शुक्रबार।
20. उम् बैठक राख पर्सि बिहान होइन दिउँसो।
21. मलाई साँझ छ बजे सम्झाऊ अँ पाँच बजे।
22. अनि सिताको त्यो नम्बर खोज न।
23. हजुर एउटा इमेल लेख हाम्रो टिमलाई बैठकको बारेमा।
24. ए आजको कार्यक्रम के के छन् देखाऊ।

**Ambiguous (expected: unclear or dictation, both acceptable)**

25. रामलाई रिपोर्ट तयार भयो भन्नु।
26. भोलि बैठक छ।
27. इमेल पठाउनुपर्ने छ।
28. सिताले फोन गर्न भनेकी थिइन्।
29. बैठक रद्द भयो।
30. मलाई साँझ सम्झना हुनुपर्छ।

**Optional extras (after the 30 work)**

- 4 sentences with English words spoken inside Nepali, such as "इमेल" and "मिटिङ". Check what the ASR writes for them.
- A few sentences where the ASR output has mistakes, to see how the decider copes.

**How it is tested**

1. **Text only.** Feed the 30 sentences straight to the decider and cleanup. No recording is needed. The results page states that accuracy was measured on typed text, so it does not include ASR mistakes.
2. **ASR smoke test.** Send one existing wav file (namaste.wav) through the full flow, to show that audio, ASR, decider and cleanup are connected.

The command-line tool accepts either text or a wav file as input.

---

## 8. What to measure

| Metric | Why |
|---|---|
| Branch accuracy | Is the path correct? |
| Accuracy per type | Where does it fail (messy, ambiguous)? |
| Confidence on right vs wrong answers | Is the threshold useful? |
| Order sensitivity | Does reversing the options change the answer? |
| Time per step | ASR, decider, cleanup, and total |
| How often cleanup changes the text | Is a "needs cleanup?" skip worth adding later? |
| Raw vs clean on messy commands | Which should go to System 2 in V2? |

---

## 9. Project layout

```
voice-poc/
  config/
    customer_a.yaml      actions off, cleanup on
    customer_b.yaml      actions on, cleanup on
    settings.yaml        endpoints, model names, threshold
  asr/                   Indic Conformer client
  decider/               interface + Gemini decider (Jev goes here later)
  cleanup/               Gemini cleanup
  orchestrator/          config reading, parallel calls, branching
  tests/
    sentences.csv        text, expected path, type
    audio/               recorded clips
  results/               test run outputs
  README.md
```

---

## 10. Tasks

**Thursday**

1. Confirm the Gemini model names and region available in your Vertex project.
2. Smoke test the ASR call with namaste.wav.
3. Call Gemini Flash-Lite with a Nepali test prompt and check the response time.
4. Check whether token probabilities are available for the chosen model.
5. Write the ASR client, the decider interface and the Gemini decider.
6. Write the cleanup call.

**Friday**

1. Write the orchestrator and the two customer configs.
2. Check the Nepali test sentences and run the text-only test on all 30.
3. Improve the decider prompt based on the failures.
4. Run the order test and collect timings.
5. Write a one-page results summary.

---

## 11. Done when

- The full flow runs from text or a wav file to a branch result.
- Customer A and Customer B configs give visibly different flows.
- The test report shows accuracy, per-type accuracy and timings.
- Swapping the decider needs a change in the config and one new file, nothing else.

If the branch accuracy is below what you consider usable, spend the remaining time on the prompt and examples before starting V2.

---

## 12. Risks

| Risk | What to do |
|---|---|
| ASR spelling mistakes on Nepali are not measured | The test is text-only. Say so in the results, and test with real speech in V3. |
| Token probabilities not available | Use the stated-confidence fallback and note the limit. |
| Ambiguous sentences cause many wrong branches | This is expected. Report it, and use the "unclear" and threshold rules to send them down the safe path. |
| Gemini latency is high | Use the smallest model, a tiny output, thinking off, and a short fixed prompt. |
| Mixed Nepali and English speech | Test a few examples and report what the ASR writes. |
| Devanagari only | Every spoken test sentence must be Nepali (or Hindi, if the endpoint supports it). |

---

## 13. What V2 adds

- System 2: a Gemini agent with function calling and two or three dummy tools
- A real decider model as a second option, only if it handles Nepali, with a comparison table against Gemini
- Raw vs clean input test for commands
