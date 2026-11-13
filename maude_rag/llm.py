"""One place to call Claude, used by every step that needs an LLM.

Single-prompt calls (answering, writing SQL, routing) go through `ask_claude`, so
they share the same model, refusal handling, and way of asking for JSON back.
The agent (step 5) runs a loop of calls, so it uses `client()` and `FALLBACK`
from here directly.
"""

import json
from functools import cache

from .config import ANSWER_MODEL

# If the model declines a request, the API retries it on a fallback model.
FALLBACK = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}


# What the last call actually ran on. With fallbacks on, the served model can
# differ from ANSWER_MODEL, which is exactly the kind of change a validation must see.
# ponytail: module-level state, fine for a one-question CLI; return it instead if calls go concurrent.
LAST_CALL: dict = {}


class Declined(Exception):
    """The model declined to answer."""


@cache
def client():
    import anthropic

    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def ask_claude(system: str, prompt: str, schema: dict | None = None, effort: str = "medium"):
    """Send one prompt. Returns text, or a dict when a JSON `schema` is given."""
    output_config = {"effort": effort}
    if schema:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    response = client().beta.messages.create(
        model=ANSWER_MODEL,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config=output_config,
        **FALLBACK,
    )
    LAST_CALL.update(model_requested=ANSWER_MODEL, model_served=response.model, effort=effort)
    if response.stop_reason == "refusal":
        raise Declined("The model declined to answer this question.")
    if response.stop_reason == "max_tokens":  # the reply was cut off; JSON would be incomplete
        raise RuntimeError("The model's reply was cut off at the length limit.")
    text = "".join(block.text for block in response.content if block.type == "text")
    return json.loads(text) if schema else text
