# V2 Plan: System 2 (Commands That Act)

**Timeline:** Sunday Oct 11 to Monday Oct 12
**Runs as:** command line, built on top of V1
**Language:** Nepali in Devanagari
**Goal:** when the decider says "command", a Gemini agent picks the right tool, calls it with the right arguments, and writes a short Nepali reply.

---

## 1. What V2 proves

1. The command path works end to end: text in, tool call out, reply written.
2. The agent picks the right tool and fills the arguments correctly, including relative dates and times such as "भोलि" (tomorrow) and "पर्सि" (day after tomorrow).
3. Raw text or cleaned text works better as input to the agent (the question left open in V1).
4. The tools switch in the customer config changes the flow.

---

## 2. Scope

**In V2**

- System 2 agent: Gemini with function calling
- Three dummy tools that return fake success and write a log line
- Short Nepali reply sentence from the agent
- A new `tools` switch in the customer config
- A labeled command test set with the expected tool and arguments
- A raw vs cleaned input comparison

**Not in V2**

- A2UI cards and TTS (V3)
- Web page or mic capture (V3)
- A real decider model. The hosted Jev has no key, is English-first and has no Nepali support. The decider stays on Gemini, behind the same interface.
- Real MCP servers

---

## 3. Flow

```
 text or wav -> (ASR) -> raw text
                            |
        orchestrator reads customer config
                            |
          +-----------------+-----------------+
    DECIDER (Gemini)                   CLEANUP (Gemini)
          +-----------------+-----------------+
                            |
                  orchestrator branches
             +--------------+--------------+
        dictation                      command
      print clean text                    |
                              SYSTEM 2 AGENT (Gemini)
                              input: raw text (or cleaned, from the test)
                              today's date and time added by code
                                          |
                          +---------------+---------------+
                      tools ON                       tools OFF
                  call dummy tool                 no tool call
                  write Nepali reply              write Nepali reply that
                                                  says what it would do
```

Rules:

- Everything from V1 still applies (actions off, cleanup off, unclear goes to dictation).
- The agent gets today's date, the weekday and the time zone from the code, never from the model. It turns relative words into exact dates only with that information.
- If the agent cannot find a tool for the request, it says so in Nepali and does not make one up.
- If a needed argument is missing (no recipient, no time), the agent asks one short question instead of guessing.

---

## 4. Dummy tools

| Tool | Arguments | Returns |
|---|---|---|
| `send_email` | to, subject, body | fake success and a message id |
| `create_calendar_event` | title, date, start time, optional attendees | fake success and an event id |
| `set_reminder` | text, date, time | fake success and a reminder id |

Each tool writes one line to a log file in `results/` with its name and arguments. The tools never contact any real service.

---

## 5. Customer config

Add one switch to the customer files:

| Config | Meaning |
|---|---|
| `tools: true` | The agent can call the dummy tools. |
| `tools: false` | The agent only replies and does not call tools. |

Add a third customer file, `customer_c`, with actions on and tools off, to show this branch.

---

## 6. Command test set

About 20 Nepali command sentences, in a new file `tests/commands.csv`. Columns: text, expected tool, expected arguments, notes.

| Type | Count | Example |
|---|---|---|
| Clear, all details given | 6 | "भोलि बिहान दश बजे बैठक राख।" |
| Relative dates and times | 4 | "पर्सि साँझ चार बजे सम्झाऊ।" |
| Messy with a self-correction | 4 | "उम् बैठक राख पर्सि बिहान होइन दिउँसो।" |
| Missing details | 3 | "रामलाई इमेल पठाऊ।" (no subject or body) |
| No matching tool | 3 | "मलाई चिया बनाइदेऊ।" |

Reuse the command sentences from V1 where they fit. Write the expected tool and arguments by hand, using a fixed "today" date for the tests so the expected dates stay stable.

---

## 7. What to measure

| Metric | Why |
|---|---|
| Correct tool chosen | Is the routing right? |
| Correct arguments | Dates, times, names, titles |
| Missing-detail cases: asked vs guessed | The agent should ask, not invent |
| No-tool cases: refused vs invented | The agent should say it cannot |
| Raw vs cleaned input | Which one goes to the agent in later versions |
| Reply in natural Nepali | Check by eye |
| Time per step | Decider, agent, total |
| Tools on vs off | The switch changes the flow |

---

## 8. Project changes

```
V1/
  agent/
    system2.py           Gemini function-calling agent
    tools.py             the three dummy tools and their definitions
  config/
    customer_b.yaml      tools: true
    customer_c.yaml      actions: true, tools: false
  tests/
    commands.csv         ~20 commands with expected tool and arguments
    test_commands.py     runs the command test, raw vs cleaned
  results/
    tool_calls.log       one line per dummy tool call
```

The orchestrator calls the agent on the command branch and shows the result.

---

## 9. Tasks

**Sunday**

1. Check that the chosen Gemini model supports function calling on Vertex.
2. Write the three dummy tools and their definitions.
3. Write the agent and connect it to the command branch.
4. Add the `tools` switch and `customer_c`.
5. Try five commands by hand and look at the tool calls.

**Monday**

1. Write `commands.csv` with the expected tools and arguments.
2. Run the command test with raw input, then with cleaned input.
3. Fix the agent prompt based on the failures.
4. Write a one-page results summary with both comparisons.

---

## 10. Done when

- A command sentence runs from text to a tool call to a Nepali reply.
- Customer B calls tools, Customer C only replies, and Customer A never reaches the agent.
- The test report shows correct-tool rate, correct-argument rate and the raw vs cleaned comparison.
- The log file shows each dummy tool call with its arguments.

---

## 11. Risks

| Risk | What to do |
|---|---|
| Wrong dates from relative words | Dates come from code, and the test uses a fixed "today". |
| Agent invents missing details | Rule in the prompt: ask one short question instead. Test it with the missing-detail cases. |
| Agent calls a tool for a non-command | The decider already filters, and the no-tool test cases check the rest. |
| Slow response (decider, then agent) | Measure each step. Turn off thinking if the model allows it. |
| Gemini Nepali replies sound unnatural | Review by eye and adjust the reply style in the prompt. |

---

## 12. What V3 adds

- A web page with mic capture and live text
- A2UI cards for tool results
- Vertex TTS for spoken replies
- Customer switches on the page
- A timing panel
