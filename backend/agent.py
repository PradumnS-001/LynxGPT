from typing import List, Literal, TypedDict, Any, Optional, Dict
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

from pathlib import Path
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
google_api_key = os.getenv("GOOGLE_API_KEY")
if google_api_key:
    os.environ["GOOGLE_API_KEY"] = google_api_key

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
    current_input: str
    route: Literal["question_paper", "course_plan", "memory", "resume_qa", "out_of_scope"]
    last_result: Optional[Any]
    resume_context: Optional[Dict]  # Added for Dreamer integration

# ---------------------------------------------------
#  ROUTER MODEL OUTPUT SCHEMA
# ---------------------------------------------------
class Route(BaseModel):
    choice: Literal["question_paper", "course_plan", "memory", "resume_qa", "out_of_scope"]

router_llm = llm.with_structured_output(Route)

# ---------------------------------------------------
#  ROUTER NODE
# ---------------------------------------------------
def classifier_node(state: State) -> State:
    """
    Decide which node to route to based ONLY on the current_input.
    Does not access state['messages'].
    """
    user_query = state["current_input"]

    system = SystemMessage(
        content=(
            "You are a strict router that chooses ONE of five labels based ONLY on the latest user question:\n"
            "- 'question_paper': if the user is asking for question papers, CT papers, exam papers, past papers,\n"
            "  or similar.\n"
            "- 'course_plan': if the user is asking for course plans, syllabus, circulars, CCM, course structure,\n"
            "  exam pattern, or related topics.\n"
            "- 'memory': if the user is asking about previous parts of the SAME conversation (e.g., 'What did I ask?') OR just saying 'hi'/'hello' (greetings).\n"
            "- 'resume_qa': if the user is asking clarifying questions about their uploaded resume, skills, experience, or job recommendations.\n"
            "- 'out_of_scope': for everything else not matching the above.\n"
            "Return ONLY one label, with no explanation."
        )
    )

    result = router_llm.invoke([system, HumanMessage(content=user_query)])
    print(f"Router choice: {result.choice}")
    return {**state, "route": result.choice}

# ---------------------------------------------------
# MAIN TASK FUNCTIONS
# ---------------------------------------------------
def question_paper_fn(state: State) -> str:
    print("Routing to question_paper_fn...")
    from QuestionPapers.query_processor import get_link
    resp = get_link(state["current_input"])
    return resp

def course_plan_fn(state: State):
    from Circulars.retriever import ask_question_once
    resp = ask_question_once(state["current_input"])
    return resp

def memory_fn(state: State) -> str:
    print("Routing to memory_fn...")
    system = SystemMessage(
        content=(
            "You are a conversation memory assistant. Use only the provided history to answer meta-questions."
        )
    )
    convo = [system] + state["messages"]
    result = llm.invoke(convo)
    return str(result.content)

def resume_qa_fn(state: State) -> str:
    """
    Answer questions based on the candidate's resume context.
    """
    print("Routing to resume_qa_fn...")
    
    context = state.get("resume_context")
    if not context:
        return "I don't see a resume uploaded for this conversation yet. Please upload one first!"

    # Format context as string
    context_str = str(context)

    system = SystemMessage(
        content=(
            "You are a helpful career assistant. The user has uploaded their resume.\n"
            f"Here is the parsed information from their resume: {context_str}\n\n"
            "Answer the user's question using ONLY this information. Be professional and encouraging."
        )
    )
    
    # We use messages here so the LLM has context of the conversation
    # But specifically instruct it to use the resume info
    convo = [system] + state["messages"]
    result = llm.invoke(convo)
    return str(result.content)

# ---------------------------------------------------
# NODE WRAPPERS
# ---------------------------------------------------
def question_paper_node(state: State) -> State:
    answer = question_paper_fn(state)
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))]}

def course_plan_node(state: State) -> State:
    answer = course_plan_fn(state)
    if isinstance(answer, dict):
        msgs = []
        ans_text = answer.get("answer") or ""
        msgs.append(AIMessage(content=str(ans_text)))
        for link in answer.get("links", []):
            msgs.append(AIMessage(content=str(link)))
        return {**state, "messages": state["messages"] + msgs, "last_result": answer}
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))], "last_result": None}

def memory_node(state: State) -> State:
    answer = memory_fn(state)
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))]}

def resume_qa_node(state: State) -> State:
    answer = resume_qa_fn(state)
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))]}

def out_of_scope_node(state: State) -> State:
    msg = "Sorry! I'm not able to handle that — could you try a different question?"
    return {**state, "messages": state["messages"] + [AIMessage(content=msg)]}

# ---------------------------------------------------
# GRAPH
# ---------------------------------------------------
builder = StateGraph(State)

builder.add_node("classifier", classifier_node)
builder.add_node("question_paper", question_paper_node)
builder.add_node("course_plan", course_plan_node)
builder.add_node("memory", memory_node)
builder.add_node("resume_qa", resume_qa_node)
builder.add_node("out_of_scope", out_of_scope_node)

builder.set_entry_point("classifier")

def route_decider(state: State) -> str:
    return state["route"]

builder.add_conditional_edges(
    "classifier",
    route_decider,
    {
        "question_paper": "question_paper",
        "course_plan": "course_plan",
        "memory": "memory",
        "resume_qa": "resume_qa",
        "out_of_scope": "out_of_scope"
    },
)

builder.add_edge("question_paper", END)
builder.add_edge("course_plan", END)
builder.add_edge("memory", END)
builder.add_edge("resume_qa", END)
builder.add_edge("out_of_scope", END)

graph = builder.compile()

def invoker(user_input: str, conversation_history: Optional[List[dict]] = None, resume_context: Optional[Dict] = None):
    """
    Invoke the agent with user input, history, and optional resume context.
    """
    messages = []
    
    if conversation_history:
        for msg in conversation_history:
            sender = msg.get("sender", "").lower()
            text = msg.get("text", "")
            if not text or not text.strip():
                continue
            if sender == "gru" or sender == "user":
                messages.append(HumanMessage(content=text))
            elif sender == "bot" or sender == "ai":
                messages.append(AIMessage(content=text))
    
    messages.append(HumanMessage(content=user_input))
    
    init_state: State = {
        "messages": messages,
        "current_input": user_input,
        "last_result": None,
        "route": "out_of_scope",
        "resume_context": resume_context # Injected context
    }

    result = graph.invoke(init_state)
    
    if result.get("last_result"):
        return result.get("last_result")
    
    return result["messages"][-1].content

# ---------------------------------------------------
# CLI DEMO
# ---------------------------------------------------
if __name__ == "__main__":
    print("Gemini Router Agent Ready 🚀")
    # Simulation logic omitted for brevity
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in {"exit", "quit"}: break
            print("Bot:", invoker(user_input))
        except KeyboardInterrupt:
            break