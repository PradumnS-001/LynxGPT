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
    # NEW: We store the current query string separately so non-memory nodes
    # don't need to parse the full message history.
    current_input: str
    route: Literal["question_paper", "course_plan", "memory", "out_of_scope"]
    # Optional place to store structured results from nodes (e.g. retriever dict)
    last_result: Optional[Any]

# ---------------------------------------------------
#  ROUTER MODEL OUTPUT SCHEMA
# ---------------------------------------------------
class Route(BaseModel):
    choice: Literal["question_paper", "course_plan", "memory", "out_of_scope"]

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
            "You are a strict router that chooses ONE of four labels based ONLY on the latest user question:\n"
            "- 'question_paper': if the user is asking for question papers, CT papers, exam papers, past papers,\n"
            "  or similar (e.g., 'give me a question paper of digital electronics',\n"
            "  'do you have papers available on automata?').\n"
            "- 'course_plan': if the user is asking for course plans, syllabus, circulars, CCM, course structure,\n"
            "  exam pattern, or related topics (e.g., 'give me the course plan for digital image processing',\n"
            "  'syllabus for EEPE37').\n"
            "- 'memory': if the user is asking about previous parts of the SAME conversation, such as\n"
            "  'What did I ask 2 responses ago?', 'Summarize our entire conversation', 'What did I say earlier?',\n"
            "  'What were my last 3 questions?'. These are meta-questions about the chat history.\n"
            "- 'out_of_scope': for everything else not matching the above.\n"
            "Return ONLY one label, with no explanation."
        )
    )

    # We wrap the string in a HumanMessage just for the LLM call, 
    # but we are NOT using the history list.
    result = router_llm.invoke([system, HumanMessage(content=user_query)])
    print(f"Router choice: {result.choice}")
    return {**state, "route": result.choice}

# ---------------------------------------------------
# MAIN TASK FUNCTIONS
# ---------------------------------------------------
def question_paper_fn(state: State) -> str:
    """
    Handle question paper queries. 
    Uses ONLY state['current_input']. Does not look at history.
    """
    print("Routing to question_paper_fn (QuestionPapers)...")
    from QuestionPapers.query_processor import get_link
    
    # Direct access to the string, no history parsing
    question = state["current_input"]
    
    print(f"Question paper query: {question}")
    response = get_link(question)
    print(f"Question paper response: {response}")
    return response


def course_plan_fn(state: State):
    """
    Handle course plan / syllabus queries.
    Uses ONLY state['current_input']. Does not look at history.
    """
    from Circulars.retriever import ask_question_once
    
    # Direct access to the string, no history parsing
    question = state["current_input"]
    
    print(f"Course plan / circular query: {question}")
    response = ask_question_once(question)
    return response


def memory_fn(state: State) -> str:
    """
    Answer meta-questions about the conversation history.
    This is the ONLY function that accesses state['messages'].
    """
    print("Routing to memory_fn (conversation memory)...")

    system = SystemMessage(
        content=(
            "You are a conversation memory assistant.\n"
            "You are given the full chat history between the user and the assistant as context.\n"
            "The LAST human message is a meta-question about that history (e.g., "
            "'What did I ask 2 responses ago?', 'Summarize our entire conversation').\n"
            "Use ONLY the provided messages to answer questions about the conversation.\n"
            "If the requested information is not present, say you cannot find it in the history."
        )
    )

    # We use the full messages list here because this is the memory node.
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


def memory_node(state: State) -> State:
    answer = memory_fn(state)
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
        "out_of_scope": "out_of_scope"
    },
)

builder.add_edge("question_paper", END)
builder.add_edge("course_plan", END)
builder.add_edge("memory", END)
builder.add_edge("out_of_scope", END)

graph = builder.compile()

def invoker(user_input: str, conversation_history: Optional[List[dict]] = None):
    """
    Invoke the agent with user input and optional conversation history.
    """
    # Convert conversation history to LangChain messages
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
    
    # Add the current user message to history
    messages.append(HumanMessage(content=user_input))
    
    # Initialize state. 
    # We explicitly set 'current_input' so nodes don't rely on 'messages' to find it.
    init_state: State = {
        "messages": messages,
        "current_input": user_input,
        "last_result": None,
        # route needs a default, though classifier will overwrite it immediately
        "route": "out_of_scope" 
    }

    result = graph.invoke(init_state)
    print("Final state messages:", result["messages"])

    # If the graph stored a structured last_result (e.g. {'answer', 'links'}), return it directly
    if result.get("last_result"):
        return result.get("last_result")

    # Otherwise, return the last AI message content
    bot_reply = result["messages"][-1].content
    print("Bot reply:", bot_reply)
    return bot_reply

# ---------------------------------------------------
# CLI DEMO
# ---------------------------------------------------
if __name__ == "__main__":
    print("Gemini Router Agent Ready 🚀")
    conversation_history = []
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in {"exit", "quit"}:
            break
        
        bot_reply = invoker(user_input, conversation_history=conversation_history)
        print("Bot:", bot_reply)
        
        # Update conversation history for next iteration
        conversation_history.append({"sender": "gru", "text": user_input})
        if isinstance(bot_reply, dict):
            conversation_history.append({"sender": "bot", "text": bot_reply.get("answer", "")})
            for link in bot_reply.get("links", []):
                conversation_history.append({"sender": "bot", "text": str(link)})
        else:
            conversation_history.append({"sender": "bot", "text": str(bot_reply)})