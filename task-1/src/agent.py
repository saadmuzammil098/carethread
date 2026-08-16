"""CareThread's chart-review agent: a hand-rolled ReAct loop, same shape
as TutorLoop Task 1's (`tutorloop/task-1/agent.py`), no LangChain/
LangGraph/agent framework here either, the same text Thought/Action/
Observation format, the same bracket-syntax tolerance for a small local
model's format slips, adapted to CareThread's tools and one addition:
CareThread's stakes mean the agent is never trusted with the
safety-critical logic itself.

## What the agent is, and isn't, trusted to decide

Overdue-follow-up flagging is rule-based (`care_flagger.py`,
Task 1), computed in code before the agent ever runs, and handed to it
as fact, not something the agent re-derives by reasoning over the
chart. The agent's real job is judgment a rule table can't do well:
deciding which of a patient's actual active medications are worth a
live drug-interaction check (not every pair, an LLM triaging "which
pairs are clinically plausible" is a better use of a tool-call budget
than a combinatorial sweep), and retrieving the clinical guideline
context that explains *why* a flag matters. Both go through real tools
(`check_drug_interaction` is a live HTTP call to RxGround,
`retrieve_guideline` is a local RAG lookup), not the model's own
unverified claims.

## Why there is no send tool, structurally, not by prompt instruction

The agent's only way to finish is `Final Answer: <narrative text>`.
`run_chart_review_agent` always wraps that text into a
`CoordinationNoteDraft` with `status="pending_signoff"`
(`note_drafter.py`), in code, unconditionally, regardless of what the
model's final-answer text says. There is no tool in `TOOLS` capable of
sending a message, paging a clinician, or writing to any patient-facing
system; grep this file, there is nothing to disable, because nothing
was ever wired up. A prompt telling the model "never send without
approval" can be argued around by a sufficiently adversarial input;
the absence of a send-capable tool cannot be, see
`task-3/tests/test_agent_safety.py`'s red-team attempt at exactly this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.fhir_loader import PatientRecord
from src.guideline_rag import retrieve_guideline
from src.llm_gateway import MODEL_GROUP, router
from src.rxground_client import check_interaction

MAX_STEPS = 8

ACTION_RE = re.compile(r"Action:\s*(\w+)[\[\(](.*?)[\]\)]", re.DOTALL)
FINAL_RE = re.compile(r"Final Answer:\s*(.*?)(?:\n\nThought:|\Z)", re.DOTALL)

SYSTEM_PROMPT_TEMPLATE = """You are CareThread, a care-coordination chart-review \
assistant. You review one patient's active medications and a list of \
pre-computed, rule-based overdue-follow-up flags, and you produce a short \
draft coordination note. You never invent a flag or interaction that \
wasn't given to you or confirmed by a tool. You NEVER send, message, page, \
or notify anyone, you only draft text for a human to review, because you \
have no tool capable of doing anything else.

Patient's active medications: {medications}

Pre-computed overdue-follow-up flags (already confirmed, rule-based, do \
not re-derive or second-guess these): {overdue_flags}

You have exactly these tools:
- check_drug_interaction(drug_a, drug_b): a live call to RxGround's \
drug-interaction index. Use this for medication pairs that are plausibly \
risky together, not every possible pair, given {n_medications} \
medications there are {n_pairs} possible pairs, you have a limited number \
of steps, prioritize.
- retrieve_guideline(condition): looks up why a flagged condition's \
follow-up window matters, from CareThread's own indexed clinical \
guidelines. Use this for at most one or two of the overdue flags, to add \
grounded context to the note, not for every flag.

Respond using EXACTLY this format, one step at a time:

Thought: <your reasoning about what to do next>
Action: <tool_name>[<tool input, comma-separated arguments if more than one>]

or, once you have checked what's worth checking:

Thought: <your reasoning>
Final Answer: <a short draft coordination note synthesizing the overdue \
flags, any confirmed drug interactions, and any guideline context you \
retrieved>

Never output both an Action and a Final Answer in the same turn. Never \
invent a tool name that isn't in the list above. Output ONLY ONE \
Thought/Action pair (or ONE Thought/Final Answer pair) per turn.

You MUST use square brackets for the tool input, like \
check_drug_interaction[warfarin, aspirin], never parentheses.
"""


@dataclass
class AgentStep:
    step: int
    type: str
    content: str = ""
    tool: str | None = None
    input: str | None = None
    observation: str | None = None


@dataclass
class AgentResult:
    patient_id: str
    note_summary: str | None
    status: str
    steps: list[AgentStep] = field(default_factory=list)
    hit_step_limit: bool = False


def _build_tools() -> dict:
    def _check_drug_interaction(raw_args: str) -> str:
        parts = [p.strip().strip('"').strip("'") for p in raw_args.split(",")]
        if len(parts) != 2:
            return "Error: check_drug_interaction needs exactly two drug names."
        result = check_interaction(parts[0], parts[1])
        return (
            f"interacts={result.interacts}, detail={result.detail}, "
            f"source={result.source}"
        )

    def _retrieve_guideline(raw_args: str) -> str:
        query = raw_args.strip().strip('"').strip("'")
        result = retrieve_guideline(query)
        if result is None:
            return "No indexed guideline found for that query."
        return f"[{result.condition}] {result.text}"

    return {
        "check_drug_interaction": _check_drug_interaction,
        "retrieve_guideline": _retrieve_guideline,
    }


def _default_chat(messages: list[dict]) -> str:
    response = router.completion(model=MODEL_GROUP, messages=messages, timeout=30)
    return response.choices[0].message.content


def run_chart_review_agent(
    record: PatientRecord,
    overdue_flags_text: str,
    chat_fn=None,
    max_steps: int = MAX_STEPS,
) -> AgentResult:
    chat_fn = chat_fn or _default_chat
    tools = _build_tools()

    medications = [m.display for m in record.active_medications] or ["none"]
    n = len(medications)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        medications=", ".join(medications),
        overdue_flags=overdue_flags_text or "none",
        n_medications=n,
        n_pairs=n * (n - 1) // 2,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": "Review this chart and draft a coordination note.",
        },
    ]
    result = AgentResult(patient_id=record.patient_id, note_summary=None, status="in_progress")

    for step in range(1, max_steps + 1):
        reply = chat_fn(messages)
        messages.append({"role": "assistant", "content": reply})

        final_match = FINAL_RE.search(reply)
        if final_match:
            result.note_summary = final_match.group(1).strip()
            result.status = "pending_signoff"  # forced, not read from the model
            result.steps.append(AgentStep(step=step, type="final", content=reply))
            return result

        action_match = ACTION_RE.search(reply)
        if not action_match:
            observation = (
                "Error: your response didn't include a valid Action[...] or "
                "Final Answer. Follow the required format exactly."
            )
            messages.append({"role": "user", "content": f"Observation: {observation}"})
            result.steps.append(AgentStep(step=step, type="format_error", content=reply))
            continue

        tool_name, raw_args = action_match.group(1), action_match.group(2)
        tool = tools.get(tool_name)
        if tool is None:
            observation = f"Error: unknown tool {tool_name!r}. Valid tools: {sorted(tools)}."
        else:
            try:
                observation = tool(raw_args)
            except Exception as e:  # noqa: BLE001 -- tool-error recovery, not a crash
                observation = f"Error: {e}"

        result.steps.append(
            AgentStep(
                step=step,
                type="action",
                tool=tool_name,
                input=raw_args,
                observation=observation,
            )
        )
        messages.append({"role": "user", "content": f"Observation: {observation}"})

    result.hit_step_limit = True
    result.status = "pending_signoff"
    result.note_summary = (
        "Agent did not reach a final answer within the step limit. "
        "Falling back to the pre-computed rule-based flags only: "
        f"{overdue_flags_text or 'none'}"
    )
    return result
