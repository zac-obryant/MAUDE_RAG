# `maude_rag/llm.py`

## Purpose

This file is the one place in the project that sends a prompt to Claude and reads back the reply. Every step that needs an LLM calls it instead of talking to Anthropic's service directly.

Every single-prompt call (answering, writing SQL, routing) goes through one function, `ask_claude`. Keeping it in one place means every such call:

- uses the same model, `ANSWER_MODEL` from `config.py`;
- handles a refusal the same way, by raising `Declined` (see step 1), and a cut-off reply the same way, by raising an error;
- asks for JSON in the same way when a step needs a structured reply rather than prose;
- records which model actually answered, in `LAST_CALL` (see step 1).

It is a shared helper, not a roadmap step of its own. It is used by:

| Step | File | What it asks the LLM for |
|---|---|---|
| 1 and 2 | `ask.py` | A written answer from the retrieved excerpts |
| 3 | `sql.py` | A SQL query (as JSON), then a written explanation of its result |
| 4 | `router.py` | Which route a question should take (as JSON) |
| 5 | `agent.py` | Uses `client()` and the `FALLBACK` setting from this file, but builds its own requests because the agent needs tools |

The file has no command of its own. It runs whenever one of these does:

```bash
python -m maude_rag.ask "What problems are reported with infusion sets?"
python -m maude_rag.sql "How many death reports are there?"
python -m maude_rag.router "How many death reports were there per manufacturer?"
```

All of them need an Anthropic API key in the `ANTHROPIC_API_KEY` environment variable, and each call is charged by Anthropic.

## Dependencies

| Dependency | Where it comes from | Why it is needed |
|---|---|---|
| `json` | Built into Python | Turns a JSON reply into a Python dictionary |
| `functools.cache` | Built into Python | Remembers the connection so it is opened only once |
| `anthropic` | Installed package | Sends the prompt to Claude and receives the reply |
| `config.py` | This project | Supplies `ANSWER_MODEL`, the model every call uses |

## Step by step with code snippets

### 1. The fallback setting, the call record, and the "declined" signal

```python
# If the model declines a request, the API retries it on a fallback model.
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


# What the last call actually ran on. With fallbacks on, the served model can
# differ from ANSWER_MODEL, which is exactly the kind of change a validation must see.
# ponytail: module-level state, fine for a one-question CLI; return it instead if calls go concurrent.
LAST_CALL: dict = {}


class Declined(Exception):
    """The model declined to answer."""
```

**In plain steps**

```
FALLBACK = two extra settings to send with every request:
    switch on the optional "server-side fallback" feature
    use the default fallback model

LAST_CALL = an empty record, filled in after each call (step 3c) with
    which model was asked for, which model actually answered, and the effort level

define a new kind of problem called Declined, meaning "the model declined to answer"
```

**Key elements**

| Code | What it means |
|---|---|
| `{"betas": [...], "fallbacks": "default"}` | A dictionary holding two request settings, stored so they can be added to any request |
| `"server-side-fallback-2026-07-01"` | The name of an optional feature (a *beta*) that has to be switched on by name. The date is part of its name |
| `"fallbacks": "default"` | If the model declines, retry on Anthropic's default fallback model |
| `LAST_CALL: dict = {}` | An empty dictionary, kept at the top level of the file so other files can read it. `: dict` is a note for human readers |
| `# ponytail: ...` | A note left by another working session: keeping this record in one shared place is fine while only one question runs at a time |
| `class Declined(Exception):` | Define a new kind of error, called an *exception*, named `Declined`. Raising it stops the current function and passes the problem up to whoever called it |
| `"""The model declined to answer."""` | A short description for human readers |

**Explanation**

A model can decline a request, for example if it judges the content unsafe. Questions about deaths and injuries from medical devices are legitimate, but a refusal is still possible. The fallback feature means the service itself retries on another model before giving up, so the program does not need its own retry code.

If the request is still declined, the calling step needs to know. `Declined` is a named signal for that. Each caller decides what to do with it: `ask.py` hands back the notice in place of an answer, `sql.py` and `router.py` print it and stop, and the evaluation scripts count the question as wrong. A named error is clearer than handing back an empty answer, which could be mistaken for a real one.

`LAST_CALL` exists because of the fallback. If the main model declines and the fallback model answers, the answer came from a different model than the one named in `config.py`. A check of the system's behaviour (a *validation*) needs to know that, since a result from one model says little about another. `LAST_CALL` keeps the requested model, the model that actually served the reply, and the effort level from the most recent call. `ask.py` includes it in its `--json` output (see [ask.md](ask.md), step 8). It holds only the most recent call: each call overwrites it.

### 2. Open the connection once (`client`)

```python
@cache
def client():
    import anthropic

    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
```

**In plain steps**

```
to get the connection to Anthropic:
    the first time: bring in the Anthropic toolkit,
                    open a connection using the API key saved on this computer,
                    remember it, and hand it back
    every later time: hand back the connection already opened
```

**Key elements**

| Code | What it means |
|---|---|
| `@cache` | A label on the function below it: "remember the answer after the first run and reuse it" |
| `import anthropic` | Bring in Anthropic's toolkit. It sits inside the function, so it is only loaded when an LLM call is actually made |
| `anthropic.Anthropic()` | Open a connection to the service. It finds the API key by itself |
| `ANTHROPIC_API_KEY` | The environment variable (a named setting held by the computer, outside the code) where the key is kept |

**Explanation**

The key never appears in the code, so the code can be shared publicly without leaking it. `@cache` means one run that makes many calls, such as an evaluation, reuses one connection.

Putting `import anthropic` inside the function lets the parts of the project that need no LLM, such as `ask.py --retrieve-only` or `sql.py --show-schema`, run on a computer that has no key set up.

### 3. Send one prompt and read the reply (`ask_claude`)

#### 3a. Choose the output settings

```python
def ask_claude(system: str, prompt: str, schema: dict | None = None, effort: str = "medium"):
    """Send one prompt. Returns text, or a dict when a JSON `schema` is given."""
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
```

**In plain steps**

```
to ask Claude (standing instructions, prompt, optional reply shape, effort "medium" unless told otherwise):
    output settings = the effort level
    if a reply shape (schema) was given:
        add to the output settings: "reply in JSON that fits this shape"
```

**Key elements**

| Code | What it means |
|---|---|
| `system: str` | The first input: the standing instructions, as text. `: str` is a note for human readers saying the input is text |
| `prompt: str` | The second input: the message itself |
| `schema: dict \| None = None` | An optional input: a description of the reply's shape, or nothing. If it is not given, it is `None` |
| `effort: str = "medium"` | An optional input with a default. It sets how much thinking the model does before answering |
| `{"effort": effort}` | Start the output settings with the effort level |
| `output_config["format"] = {...}` | Add a `format` setting to the dictionary |
| `"type": "json_schema"` | Ask for *structured output*: a reply in JSON that fits the given schema |

**Explanation**

Two settings shape the reply.

**Effort** controls how much the model reasons before it replies. More effort can give better answers to harder questions, but takes longer and costs more. Most callers use the default, `"medium"`. The router in `router.py` uses `"low"`, because choosing between three routes is a quick decision.

**Format** is only used when the caller passes a *schema*. JSON is a plain-text way of writing labelled values, much like a Python dictionary. A JSON *schema* is a description of which labels the reply must have and what kind of value each holds. For example, `sql.py` asks for a reply with exactly two text fields, `sql` and `explanation`. With structured output, the API guarantees the reply matches the schema, so the program can read it directly without checking that each field is there. Without it, a model asked for JSON might add a sentence before it or leave a field out.

#### 3b. Send the request

```python
    response = client().beta.messages.create(
        model=ANSWER_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
        **FALLBACK,
    )
```

**In plain steps**

```
response = send one message to the model, including:
    which model to use (the one named in the settings)
    the longest reply allowed
    the standing instructions
    one message from the "user": the prompt
    the output settings from 3a
    the fallback settings from step 1
wait for the reply
```

**Key elements**

| Code | What it means |
|---|---|
| `client()` | The connection from step 2 |
| `.beta.messages.create(...)` | Send a message and wait for the reply. `beta` is the part of the toolkit that offers newer features, which the fallback setting needs |
| `model=ANSWER_MODEL` | The model named in `config.py`. Every step uses the same one |
| `max_tokens=16000` | An upper limit on the reply's length. A *token* is a piece of a word |
| `system=system` | The standing instructions passed in by the caller |
| `messages=[{"role": "user", "content": prompt}]` | The conversation: one message, from the person asking, containing the prompt |
| `output_config=output_config` | The effort and format settings from 3a |
| `**FALLBACK` | Unpack the `FALLBACK` dictionary into named settings, so this line means `betas=[...], fallbacks="default"` |

**Explanation**

This is the same request `ask.py` used to make by itself (see [ask.md](ask.md), step 6), moved here so every step shares it. Changing the model in `config.py` now changes it for every step at once.

#### 3c. Record the call, check how it ended, and hand back the reply

```python
    LAST_CALL.update(model_requested=ANSWER_MODEL, model_served=response.model, effort=effort)
    if response.stop_reason == "refusal":
        raise Declined("The model declined to answer this question.")
    if response.stop_reason == "max_tokens":  # the reply was cut off; JSON would be incomplete
        raise RuntimeError("The model's reply was cut off at the length limit.")
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text) if schema else text
```

**In plain steps**

```
record in LAST_CALL: the model asked for, the model that answered, and the effort

if the model declined (even after the fallback):
    stop and raise Declined, with a short message
if the reply was cut off at the length limit:
    stop and raise an error saying so

text = every part of the reply that is text, joined together

if a schema was given: turn the JSON text into a dictionary and hand it back
otherwise: hand back the text as it is
```

**Key elements**

| Code | What it means |
|---|---|
| `LAST_CALL.update(...)` | Fill in (or overwrite) these three fields of the record from step 1 |
| `response.model` | The name of the model that actually wrote the reply |
| `response.stop_reason` | Why the model stopped writing. `"refusal"` means it declined; `"max_tokens"` means it hit the length limit |
| `raise Declined(...)` | Stop here and pass the `Declined` problem from step 1 up to the caller |
| `raise RuntimeError(...)` | Stop with a general error and a message saying what went wrong |
| `response.content` | The reply, delivered as a list of blocks |
| `block.type == "text"` | "Is this block ordinary text?" Other blocks can hold, for example, the model's reasoning |
| `"".join(...)` | Glue the text blocks together with nothing between them |
| `json.loads(text)` | Read JSON text and turn it into a Python dictionary |
| `x if schema else text` | `x` when a schema was given, the plain text otherwise |

**Explanation**

The call is recorded before the checks, so `LAST_CALL` is filled in even when the reply is then rejected.

A reply that hits `max_tokens` is cut off mid-sentence. For a JSON reply this would leave broken JSON, which would fail later with a confusing error, so it is stopped here with a message that says why. Unlike `Declined`, no caller catches this error specially; it ends the command.

A caller gets back one of two things: plain text when it asked for prose, or a dictionary when it gave a schema. For example, `write_sql` in `sql.py` gets back `{"sql": "...", "explanation": "..."}` and can read `["sql"]` straight away.

## What to keep in mind

- **Every call costs money and needs a key.** Nothing in this file has been run against the real API yet for steps 3 to 5; no API key was available when they were written.
- **Refusals and cut-off replies are detected; other failures are not.** If the service is unreachable or the key is wrong, the error from the `anthropic` toolkit passes straight up to the caller.
- **One model for everything.** Every step uses `ANSWER_MODEL`. A cheaper or faster model for simple jobs such as routing would need a new input; for now the router saves effort by using `effort="low"` instead.
- **Structured output fixes the shape, not the content.** The schema guarantees a field called `sql` holding text. It does not guarantee that the text is a correct query. That is what [evaluate_llm.md](evaluate_llm.md) measures.
- **The fallback model may differ.** If the main model declines and the fallback answers, the answer came from a different model. `LAST_CALL` records which one, but only for the most recent call.
- **The agent is separate.** `agent.py` runs a loop of calls with tools, so it uses `client()` and `FALLBACK` directly rather than `ask_claude`. The refusal and cut-off checks, and `LAST_CALL`, do not cover the agent's calls.
