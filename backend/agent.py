from typing import List, Literal, TypedDict, Any, Optional
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
import os
from dotenv import load_dotenv
load_dotenv()
google_api_key = os.getenv("GOOGLE_API_KEY")

# ---------------------------------------------------
#  CONFIG  (Gemini Flash 2.5)
# ---------------------------------------------------
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0,
    google_api_key=google_api_key,
    convert_system_message_to_human=True
)

# ---------------------------------------------------
#  STATE
# ---------------------------------------------------
class State(TypedDict):
    messages: List[BaseMessage]
    route: Literal["answer_question", "get_docs", "out_of_scope"]
    # Optional place to store structured results from nodes (e.g. retriever dict)
    last_result: Optional[Any]

# ---------------------------------------------------
#  ROUTER MODEL OUTPUT SCHEMA
# ---------------------------------------------------
class Route(BaseModel):
    choice: Literal["answer_question", "get_docs", "out_of_scope"]

router_llm = llm.with_structured_output(Route)

# ---------------------------------------------------
#  ROUTER NODE
# ---------------------------------------------------
def classifier_node(state: State) -> State:
    last_human = next((m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None)

    if last_human is None:
        return {**state, "route": "out_of_scope"}

    system = SystemMessage(
        content=(
            "You are a text classifier router:\n"
            "- 'answer_question' if the question corelates to the user asking about something related to a course or class-committee, course plan or a circular or something related to ccm (class committee) or a related topic.\n"
            "- 'get_docs' if the user is asking for some question paper or a ct paper or some paper.\n"
            "- 'out_of_scope' if unrelated to supported topics.\n"
            "Return ONLY one label."
        )
    )

    result = router_llm.invoke([system, last_human])
    print(f"Router choice: {result.choice}")
    return {**state, "route": result.choice}

# ---------------------------------------------------
# MAIN TASK FUNCTIONS
# ---------------------------------------------------
def answer_question_fn(state: State):
    """Call the retriever; may return a string or a dict {answer, links}.
    We return the raw retriever result so the node can append appropriate messages.
    """
    from Circulars.retriever import ask_question_once
    question = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    print(f"Answering question: {question}")
    response = ask_question_once(question)
    return response


def get_docs_fn(state: State) -> str:
    """Replace with real RAG logic later"""
    print("Getting documents...")
    from QuestionPapers.query_processor import get_link
    question = next((m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), "")
    print(f"Getting docs for query: {question}")
    response = get_link(question)
    print(f"Document retrieval response: {response}")
    return response

# ---------------------------------------------------
# NODE WRAPPERS
# ---------------------------------------------------
def answer_question_node(state: State) -> State:
    answer = answer_question_fn(state)

    # If retriever returned a structured dict, append the answer and each link as separate AI messages
    if isinstance(answer, dict):
        msgs = []
        ans_text = answer.get("answer") or ""
        msgs.append(AIMessage(content=str(ans_text)))
        for link in answer.get("links", []):
            msgs.append(AIMessage(content=str(link)))
        return {**state, "messages": state["messages"] + msgs, "last_result": answer}

    # otherwise assume string
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))], "last_result": None}

def get_docs_node(state: State) -> State:
    answer = get_docs_fn(state)
    return {**state, "messages": state["messages"] + [AIMessage(content=answer)]}

def out_of_scope_node(state: State) -> State:
    msg = "Sorry! I'm not able to handle that — could you try a different question?"
    return {**state, "messages": state["messages"] + [AIMessage(content=msg)]}

# ---------------------------------------------------
# GRAPH
# ---------------------------------------------------
builder = StateGraph(State)

builder.add_node("classifier", classifier_node)
builder.add_node("answer_question", answer_question_node)
builder.add_node("get_docs", get_docs_node)
builder.add_node("out_of_scope", out_of_scope_node)

builder.set_entry_point("classifier")

def route_decider(state: State) -> str:
    return state["route"]

builder.add_conditional_edges(
    "classifier",
    route_decider,
    {
        "answer_question": "answer_question",
        "get_docs": "get_docs",
        "out_of_scope": "out_of_scope"
    },
)

builder.add_edge("answer_question", END)
builder.add_edge("get_docs", END)
builder.add_edge("out_of_scope", END)

graph = builder.compile()

def invoker(user_input: str):
    init_state: State = {
            "messages": [HumanMessage(content=user_input)],
            "last_result": None
        }

    result = graph.invoke(init_state)
    print("Final state messages:", result["messages"])

    # If the graph stored a structured last_result (e.g. {'answer', 'links'}), return it directly
    if result.get("last_result"):
        return result.get("last_result")

    # Otherwise, return the last AI message content for backward compatibility
    bot_reply = result["messages"][-1].content
    print("Bot reply:", bot_reply)
    return bot_reply

# ---------------------------------------------------
# CLI DEMO
# ---------------------------------------------------
if __name__ == "__main__":
    print("Gemini Router Agent Ready 🚀")
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in {"exit", "quit"}:
            break
        
        bot_reply = invoker(user_input)
        print("Bot:", bot_reply)
