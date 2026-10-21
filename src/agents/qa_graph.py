"""Repository Q&A agent (LangGraph):

    route -> agent <-> tools -> (synthesize) -> finalize

route is the spec's Query Understanding step: a deterministic keyword
classifier assigns one or more intents (structural, architectural,
historical, rationale), and each intent unlocks its tools — which also keeps
the tool definitions sent on every round small. agent asks the LLM what to
look up; tools runs the read-only tools and records evidence server-side;
synthesize produces a final answer from the evidence when the tool budget
runs out; finalize normalizes citations and the confidence line.
"""
import operator
import re
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

import llm
import qa_engine as qa

INTENT_PATTERNS = {
    "rationale": re.compile(
        r"\b(why|reason\w*|rationale|decid\w*|decisions?|chose|choose|choice|adopt\w*|switch(ed|ing)? (to|from)|"
        r"migrat\w*|instead of|replac\w*|motivat\w*|adrs?|trade-?offs?)\b", re.IGNORECASE),
    "historical": re.compile(
        r"\b(who|when|history|historical|commits?|committed|authors?|wrote|written|changed|changes|changing|"
        r"modif\w*|contribut\w*|since|recent(ly)?|over time|evolv\w*|evolution|introduc\w*|added|removed|"
        r"deleted|timeline|blame|first|oldest|newest|latest|snapshots?)\b", re.IGNORECASE),
    "architectural": re.compile(
        r"\b(violat\w*|rules?|layers?|layered|architect\w*|health|drift\w*|coupl\w*|clean|smells?|"
        r"design|separation|degrad\w*|bypass\w*|directly|data access|service layer|anti-?patterns?)\b",
        re.IGNORECASE),
}

BASE_TOOLS = {"get_repository_overview", "search_entities"}
INTENT_TOOLS = {
    "structural": {"get_module_details", "get_function_details", "get_change_impact", "read_source",
                   "search_source_text"},
    "architectural": {"get_architecture_health", "get_drift_trend", "compare_snapshots", "get_module_details",
                      "read_source"},
    "historical": {"get_file_history", "get_commit", "get_contributors", "get_drift_trend", "compare_snapshots",
                   "get_module_details"},
    "rationale": {"list_decisions", "explain_decision", "get_commit", "get_file_history"},
}
INTENT_ORDER = ("structural", "architectural", "historical", "rationale")


def route_intents(question: str) -> list:
    """Deterministic multi-label intent classification. Structural is the
    default and is kept alongside other intents only when the question names
    code (a file path or an identifier), since rationale/history questions
    usually still need to resolve a module."""
    intents = [name for name in ("architectural", "historical", "rationale") if INTENT_PATTERNS[name].search(question)]
    names_code = bool(re.search(r"[\w-]+\.(py|js|jsx|ts|tsx)\b|`[^`]+`|\w+\(\)|\b\w+_\w+\b|\b[a-z]+[A-Z]\w*\b", question))
    if not intents or names_code:
        intents.insert(0, "structural")
    return [i for i in INTENT_ORDER if i in intents]


def tools_for(intents: list) -> list:
    names = set(BASE_TOOLS)
    for intent in intents:
        names |= INTENT_TOOLS[intent]
    return [t for t in qa.TOOLS if t["function"]["name"] in names]


class QAState(TypedDict, total=False):
    question: str
    history: list
    session: object
    sources: dict
    repo_url: str
    intents: list
    tools: list
    messages: list
    pending: list
    seen_calls: set
    rounds: int
    evidence: Annotated[list, operator.add]
    answer: str


def _route(state: QAState) -> dict:
    intents = route_intents(state["question"])
    messages = [{"role": "system", "content": qa.system_prompt(state["repo_url"], bool(state["sources"]), intents)}]
    messages += qa.clean_history(state.get("history"))
    messages.append({"role": "user", "content": state["question"].strip()})
    return {"intents": intents, "tools": tools_for(intents), "messages": messages, "rounds": 0,
            "seen_calls": set(), "pending": []}


def _agent(state: QAState) -> dict:
    result = llm.chat(state["messages"], purpose="qa", max_tokens=qa.MAX_OUTPUT_TOKENS, tools=state["tools"])
    calls = [{"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments or "{}"}
             for tc in result.tool_calls][:qa.MAX_TOOL_CALLS_PER_ROUND]
    if not calls:
        return {"answer": result.content, "pending": []}
    assistant = {"role": "assistant", "content": result.content or "",
                 "tool_calls": [{"id": c["id"], "type": "function",
                                 "function": {"name": c["name"], "arguments": c["arguments"]}} for c in calls]}
    return {"messages": state["messages"] + [assistant], "pending": calls}


def _tools(state: QAState) -> dict:
    tool_messages, evidence = qa.execute_tool_calls(state["session"], state["sources"], state["pending"],
                                                    state["seen_calls"])
    messages = state["messages"] + tool_messages
    qa.fit_context(messages)
    return {"messages": messages, "evidence": evidence, "pending": [], "rounds": state["rounds"] + 1}


def _synthesize(state: QAState) -> dict:
    # The last agent turn asked for more tools than the budget allows; answer
    # from what was gathered, without offering tools at all.
    messages = state["messages"]
    if messages and messages[-1].get("tool_calls"):
        messages = messages[:-1]
    result = llm.chat(qa.synthesis_messages(messages), purpose="qa", max_tokens=qa.MAX_OUTPUT_TOKENS)
    return {"answer": result.content}


# gpt-oss sometimes returns its plan ("We need to call read_source for ...")
# instead of an answer, typically once the tools are no longer offered.
# Only planning phrasing counts: an answer may well mention a tool or a step.
_PLANNING = re.compile(r"^\s*(we need to|we should|we must|let's|let us|i need to|i will|i'll)\b"
                       r"|\b(we|i) (need to|should|must|will|'ll) (call|use|invoke|run|query|check)\b", re.IGNORECASE)
NOT_ANSWERED = ("I gathered evidence for this question but couldn't put together a reliable answer. "
                "Please ask again, or ask a narrower question.")


_PLAN_START = re.compile(r"^\s*(we need to|we should|we must|let's|let us|i need to|i will|i'll)\b", re.IGNORECASE)
# How gpt-oss ends untagged reasoning before writing the answer itself: "Provide answer.", "Now write the final answer:".
_ANSWER_MARK = re.compile(r"(?:^|(?<=[.!\n]))\s*(?:now,?\s+)?(?:let's\s+|let us\s+|we\s+|i\s+)?(?:will\s+)?"
                          r"(?:provide|write|give|produce|craft|compose|draft)\s+(?:the\s+|an?\s+)?(?:final\s+)?"
                          r"(?:answer|response)\b[.:!]?", re.IGNORECASE)


_TOOL_TALK = re.compile(r"\b(call|calls|tool|tools|invoke|" + "|".join(t["function"]["name"] for t in qa.TOOLS) + r")\b",
                        re.IGNORECASE)


def looks_like_plan(answer: str) -> bool:
    """A reply that talks about calling tools rather than answering: a short one
    with planning phrasing, or one of any length that opens with planning and
    talks about tools straight away."""
    text = (answer or "").strip()
    if not text:
        return False
    if len(text) < 800 and _PLANNING.search(text):
        return True
    return bool(_PLAN_START.match(text)) and bool(_TOOL_TALK.search(text[:400]))


def strip_leaked_reasoning(answer: str) -> str:
    """gpt-oss sometimes writes its reasoning into the answer, untagged ("We need
    to call ... Provide answer."), followed by the real answer. Keep the answer."""
    text = answer or ""
    if not _PLAN_START.match(text):
        return answer
    marks = list(_ANSWER_MARK.finditer(text))
    if marks:
        rest = text[marks[-1].end():].strip()
        if len(rest) >= 40 and not looks_like_plan(rest):
            return rest
    return answer


def _finalize(state: QAState) -> dict:
    answer = strip_leaked_reasoning(state.get("answer") or "")
    if looks_like_plan(answer):
        # Ask once more for the answer itself, from the evidence already gathered.
        messages = state["messages"]
        if messages and messages[-1].get("tool_calls"):
            messages = messages[:-1]          # calls asked for but never run
        retry = qa.synthesis_messages(messages)
        retry[-1]["content"] += ("\n\nTools are no longer available. Do not describe further steps: write the "
                                 "final answer for me now.")
        answer = strip_leaked_reasoning(llm.chat(retry, purpose="qa", max_tokens=qa.MAX_OUTPUT_TOKENS).content)
        if looks_like_plan(answer):
            answer = NOT_ANSWERED
    answer = qa.clean_citations(answer).strip()
    if not answer:
        raise ValueError("The model returned an empty answer")
    if "confidence:" not in answer.lower():
        level = "Medium" if state.get("evidence") else "Low"
        answer += f"\n\n**Confidence:** {level} — no confidence statement was given; " \
                  f"{len(state.get('evidence', []))} lookups were made."
    return {"answer": answer}


def _after_agent(state: QAState) -> str:
    if not state.get("pending"):
        return "finalize"
    return "tools" if state["rounds"] < qa.MAX_TOOL_ROUNDS else "synthesize"


def build_qa_graph():
    graph = StateGraph(QAState)
    graph.add_node("route", _route)
    graph.add_node("agent", _agent)
    graph.add_node("tools", _tools)
    graph.add_node("synthesize", _synthesize)
    graph.add_node("finalize", _finalize)
    graph.add_edge(START, "route")
    graph.add_edge("route", "agent")
    graph.add_conditional_edges("agent", _after_agent, ["tools", "synthesize", "finalize"])
    graph.add_edge("tools", "agent")
    graph.add_edge("synthesize", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile()


QA_GRAPH = build_qa_graph()


def run_qa(question: str, history: list) -> dict:
    repo_url, sources = qa.repo_snapshot()
    with qa.shared_driver().session() as session:
        if session.run("MATCH (m:Module) RETURN count(m)").single()[0] == 0:
            return {"answer": "No repository has been analyzed yet. Paste a GitHub URL above and run **Analyze** first.",
                    "evidence": [], "intents": []}
        llm.describe("qa")  # raises LLMConfigError if no provider is configured
        state = QA_GRAPH.invoke(
            {"question": question, "history": history, "session": session, "sources": sources,
             "repo_url": repo_url, "evidence": []},
            {"recursion_limit": 2 * qa.MAX_TOOL_ROUNDS + 8})
    return {"answer": state["answer"], "evidence": state.get("evidence", []), "intents": state["intents"]}
