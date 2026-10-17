"""Ask a fresh LLM about each college, in one request: vibe, AP/IB and olympiad preference, HubSpot feedback.

Every request is a single, stand-alone message: no system prompt and no
information about UGS or this project. When a college has HubSpot
calls/notes, they are added as context (after sources/redact.py has removed
sentences that may name people), and the model is told to fact-check them
and answer primarily from its own knowledge of the college.

Provider: Gemini when GEMINI_API_KEY is set (model GEMINI_MODEL), otherwise
Anthropic (ANTHROPIC_API_KEY, model ANTHROPIC_MODEL, default claude-opus-5).
"""

import json
import os
import re
import threading
import time
from collections import deque

from colleges.models import SourceRecord
from sources.redact import filter_names

CONTEXT_CHAR_LIMIT = 6000

# Names that read better in a prompt than the IPEDS name.
DISPLAY_NAMES = {
    190150: "Columbia University (Columbia College and Columbia Engineering)",
    221519: "Sewanee: The University of the South",
    160755: "Tulane University",
    130590: "Trinity College (Hartford, Connecticut)",
}

INFORMED = "Make an informed response by considering everything you know about the university."

# One request per college answers all three questions; each answer has its own JSON field.
PROMPT = (
    "You are director of undergraduate admissions at {name}. Answer the three questions below. "
    + INFORMED + "\n\n"
    "1. What are the key traits of a student we are looking to admit? Limit response to 100 words or less. "
    "(field: vibe)\n\n"
    "2. When your office reads applications from international students, how much do you favour applicants "
    "from high schools that offer an IB or AP curriculum over equally strong applicants from ordinary schools "
    "that follow their country's national curriculum? Choose one level: strong_preference (an IB/AP background "
    "is a clear advantage), some_preference (it helps somewhat, but national-curriculum students are fully "
    "competitive), or no_preference (curriculum type does not matter, only performance in the context of the "
    "school). Explain in 50 words or less. (fields: apib_level, apib_explanation)\n\n"
    "3. Does your office mainly look for academically exceptional applicants, with national or international "
    "olympiad results and research experience, or would a strong, well-rounded applicant whose main distinction "
    "is community impact or activism be just as competitive? Choose one level: academic_excellence (olympiad- or "
    "research-level academic distinction is close to expected), balanced (academic distinction and other kinds of "
    "impact are weighed about equally), or holistic (an applicant without academic awards but with strong "
    "character and community impact, for example a social activist, is fully competitive). Explain in 50 words "
    "or less. (fields: olympiad_level, olympiad_explanation)"
)

PROPERTIES = {
    "vibe": {"type": "string", "description": "Answer to question 1, 100 words or less"},
    "apib_level": {"type": "string", "enum": ["strong_preference", "some_preference", "no_preference"]},
    "apib_explanation": {"type": "string", "description": "50 words or less"},
    "olympiad_level": {"type": "string", "enum": ["academic_excellence", "balanced", "holistic"]},
    "olympiad_explanation": {"type": "string", "description": "50 words or less"},
}

CONTEXT_INTRO = (
    "\n\nBelow are notes from conversations between a college-counselling organisation and your "
    "admissions office. Treat them as unverified: they may be wrong, out of date, about a single "
    "student, or too broad to be useful. Stress-test them: check each claim against what you know "
    "about {name}, and discard claims that conflict with well-established facts about the university. "
    "Base your answers primarily on your own knowledge of {name}; use the notes only to refine them where "
    "they are consistent with it, and do not mention the notes in those answers. In the field "
    "hubspot_feedback, write 80 words or less of feedback on the notes: which claims hold up, which look "
    "wrong, outdated or too broad, and why.\n\n<notes>\n{notes}\n</notes>"
)
FEEDBACK = {"hubspot_feedback": {"type": "string", "description": "Fact-check of the notes, 80 words or less"}}


def display_name(college):
    return DISPLAY_NAMES.get(college.unitid, college.name)


def hubspot_context(college, allow_words):
    """(text, n_items): name-filtered HubSpot calls/notes/meetings, newest first."""
    recs = SourceRecord.objects.filter(source="hubspot", college=college).exclude(kind="hubspot_company")
    items, used = [], 0
    for r in sorted(recs, key=lambda r: (r.raw_json or {}).get("timestamp") or "", reverse=True):
        kept, _, _ = filter_names(r.raw_text, allow_words)
        if len(kept) < 20:
            continue
        date = ((r.raw_json or {}).get("timestamp") or "")[:10]
        kind = r.kind.replace("hubspot_", "")
        block = f"[{date} {kind}]\n{kept}"
        if sum(len(b) for b in items) + len(block) > CONTEXT_CHAR_LIMIT:
            break
        items.append(block)
        used += 1
    return "\n\n".join(items), used


def build_prompt(college, context):
    name = display_name(college)
    prompt = PROMPT.format(name=name)
    if context:
        prompt += CONTEXT_INTRO.format(name=name, notes=context)
    return prompt


def schema_for(with_notes):
    props = dict(PROPERTIES)
    if with_notes:
        props.update(FEEDBACK)
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# ---------------------------------------------------------------- rate limit

class RateLimiter:
    """At most `max_calls` calls in any `period` seconds, shared across threads."""

    def __init__(self, max_calls, period=60.0):
        self.max_calls, self.period = max_calls, period
        self.calls = deque()
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= self.period:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                sleep_for = self.period - (now - self.calls[0]) + 0.05
            time.sleep(sleep_for)


# ---------------------------------------------------------------- providers

def provider():
    """('gemini' | 'anthropic', model) from .env."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini", os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", os.environ.get("ANTHROPIC_MODEL") or "claude-opus-5"
    return None, None


def make_client(name):
    if name == "gemini":
        from google import genai

        return genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    import anthropic

    return anthropic.Anthropic(max_retries=4)


PATIENT = (30, 60, 90)   # seconds to wait before each retry when Gemini is busy (batch commands)
QUICK = (3,)             # while a student waits on the page: one short retry, then give up


def _call_gemini(client, model, prompt, schema, waits=PATIENT):
    from google.genai import errors, types

    config = types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema)
    for attempt in range(len(waits) + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            break
        except errors.APIError as exc:
            if getattr(exc, "code", None) in (429, 500, 503) and attempt < len(waits):
                time.sleep(waits[attempt])  # quota or overload: wait for the window to free up
                continue
            raise
    text = (response.text or "").strip()
    usage = response.usage_metadata
    return text, {"input_tokens": getattr(usage, "prompt_token_count", None),
                  "output_tokens": getattr(usage, "candidates_token_count", None)}, model


def _call_anthropic(client, model, prompt, schema):
    response = client.beta.messages.create(
        model=model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],  # server-side fallback if the model declines
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined ({getattr(response.stop_details, 'category', None)})")
    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    return text, {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}, response.model


def ask(provider_name, client, model, prompt, with_notes, limiter=None):
    """One stand-alone request. Returns {'text', 'parsed', 'model', 'provider', 'usage'}."""
    schema = schema_for(with_notes)
    if limiter:
        limiter.wait()
    call = _call_gemini if provider_name == "gemini" else _call_anthropic
    text, usage, used_model = call(client, model, prompt, schema)
    return {"provider": provider_name, "model": used_model, "text": text, "parsed": json.loads(text), "usage": usage}


def word_count(text):
    return len(re.findall(r"\b\w[\w'’-]*\b", text))
