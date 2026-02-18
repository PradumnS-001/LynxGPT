from typing import List, Literal, TypedDict, Any, Optional, Dict
from datetime import datetime

from langgraph.graph import StateGraph, END
from RAG.rag_engine import ask_subject_qa
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
    route: Literal["question_paper", "course_plan", "memory", "resume_qa", "subject_qa", "out_of_scope"]
    last_result: Optional[Any]
    resume_context: Optional[Dict]  # Added for Dreamer integration

# ---------------------------------------------------
#  ROUTER MODEL OUTPUT SCHEMA
# ---------------------------------------------------
class Route(BaseModel):
    choice: Literal["question_paper", "course_plan", "memory", "resume_qa", "subject_qa", "out_of_scope"]

router_llm = llm.with_structured_output(Route)

# ---------------------------------------------------
#  ROUTER NODE
# ---------------------------------------------------
def classifier_node(state: State) -> State:
    """
    Decide which node to route to based ONLY on the current_input.
    Does not access state['messages'] — EXCEPT for follow-up detection.
    """
    user_query = state["current_input"]
    
    # Quick check: if the last bot message asked for missing fields, route back to question_paper
    messages = state.get("messages", [])
    if messages:
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                if "please specify" in msg.content.lower():
                    print(f"Router choice: question_paper (follow-up to 'Please specify')")
                    return {**state, "route": "question_paper"}
                break  # Only check the most recent bot message

    system = SystemMessage(
        content=(
            "You are a strict router that chooses ONE of five labels based ONLY on the latest user question:\n"
            "- 'question_paper': if the user is asking for question papers, CT papers, exam papers, past papers,\n"
            "  or similar.\n"
            "- 'course_plan': if the user is asking for course plans, syllabus, circulars, CCM, course structure,\n"
            "  exam pattern, or related topics.\n"
            "- 'memory': if the user is asking about previous parts of the SAME conversation (e.g., 'What did I ask?'), greetings ('hi', 'hello'), identity/meta questions ('who are you', 'what can you do', 'what is this', 'help'), or casual conversational remarks ('thanks', 'thank you', 'okay', 'got it', 'cool', 'bye', 'nice', 'great').\n"
            "- 'resume_qa': if the user is asking clarifying questions about their uploaded resume, skills, experience, or job recommendations.\n"
            "- 'subject_qa': if the user is asking subject-specific questions, definitions, formulas, or academic content questions (e.g., 'What is thermodynamics?', 'Explain Newton's laws').\n"
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
def question_paper_fn(state: State) -> dict:
    print("Routing to question_paper_fn...")
    from QuestionPapers.query_processor import get_link
    
    query = state["current_input"]
    messages = state.get("messages", [])
    
    # Check if this is a follow-up to a "Please specify" prompt
    # Look at the last bot message — if it asked for missing details,
    # find the original user query and merge them
    if len(messages) >= 2:
        last_bot_msg = None
        prev_user_msg = None
        # Walk backwards to find last bot message and the user message before it
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and last_bot_msg is None:
                last_bot_msg = msg.content
            elif isinstance(msg, HumanMessage) and last_bot_msg is not None:
                prev_user_msg = msg.content
                break
        
        if last_bot_msg and "please specify" in last_bot_msg.lower() and prev_user_msg:
            # Merge: original query + follow-up answer
            merged = f"{prev_user_msg} {query}"
            print(f"INFO: Detected follow-up. Merging: '{prev_user_msg}' + '{query}' → '{merged}'")
            query = merged
    
    resp = get_link(query)
    return resp

def course_plan_fn(state: State):
    from Circulars.retriever import ask_question_once
    resp = ask_question_once(state["current_input"])
    return resp

def memory_fn(state: State) -> str:
    print("Routing to memory_fn...")
    system = SystemMessage(
        content=(
            "You are LynxGPT — a sharp, confident AI assistant forged by Spider R&D.\n"
            "You have a slightly diabolical edge: witty, bold, and unapologetically helpful.\n"
            "You are proud of your creators at Spider R&D but never arrogant.\n"
            "When greeted, respond with energy and personality.\n"
            "When asked who you are, introduce yourself as LynxGPT, built by Spider R&D.\n"
            "You have access to the conversation history and can recall previous messages.\n"
            "Keep responses concise but memorable. Never be boring.\n"
            "Do NOT say you are a 'large language model' or mention Google/Gemini — you are LynxGPT."
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

def subject_qa_fn(state: State) -> str:
    print("Routing to subject_qa_fn...")
    resp = ask_subject_qa(state["current_input"])
    return resp

# ---------------------------------------------------
# NODE WRAPPERS
# ---------------------------------------------------
def question_paper_node(state: State) -> State:
    answer_dict = question_paper_fn(state)
    
    # Handle the dictionary response (answer text + links)
    msgs = []
    
    # Add the main text response
    main_text = answer_dict.get("answer", "Here is what I found:")
    msgs.append(AIMessage(content=str(main_text)))
    
    # Add each link as a separate message (Frontend renders .pdf links as chips)
    for link in answer_dict.get("links", []):
        msgs.append(AIMessage(content=str(link)))

    return {**state, "messages": state["messages"] + msgs, "last_result": answer_dict}

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

def subject_qa_node(state: State) -> State:
    answer = subject_qa_fn(state)
    return {**state, "messages": state["messages"] + [AIMessage(content=str(answer))]}

def out_of_scope_node(state: State) -> State:
    msg = "Sorry! I'm not able to handle that — could you try a different question?"
    return {**state, "messages": state["messages"] + [AIMessage(content=msg)]}

# ---------------------------------------------------
# GRAPH
# ---------------------------------------------------
# ---------------------------------------------------
#  GRAPH
# ---------------------------------------------------
builder = StateGraph(State)

builder.add_node("classifier", classifier_node)
builder.add_node("question_paper", question_paper_node)
builder.add_node("course_plan", course_plan_node)
builder.add_node("memory", memory_node)
builder.add_node("resume_qa", resume_qa_node)
builder.add_node("subject_qa", subject_qa_node)
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
        "subject_qa": "subject_qa",
        "out_of_scope": "out_of_scope"
    },
)

builder.add_edge("question_paper", END)
builder.add_edge("course_plan", END)
builder.add_edge("memory", END)
builder.add_edge("resume_qa", END)
builder.add_edge("subject_qa", END)
builder.add_edge("out_of_scope", END)

graph = builder.compile()

# ---------------------------------------------------
#  HELPER / DB
# ---------------------------------------------------
try:
    from database.redis_client import RedisClient, redis_host, redis_port
except ImportError:
    # Fallback for when running agent.py directly as a script (sys.path issues)
    import sys
    sys.path.append(str(Path(__file__).parent))
    from database.redis_client import RedisClient, redis_host, redis_port

def invoker(user_input: str, conversation_history: Optional[List[dict]] = None, resume_context: Optional[Dict] = None, session_id: Optional[str] = None):
    """
    Invoke the agent with user input. 
    - If `conversation_history` is provided, it uses that (stateless mode).
    - If `conversation_history` is MISSING but `session_id` is provided, it fetches from Redis (stateful mode).
    """
    messages = []
    
    # 1. Try to load legacy list-of-dicts history if provided
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

    # 2. If no history provided, but we have a session_id, fetch from Redis
    elif session_id:
        print(f"DEBUG: Fetching history for session {session_id} from Redis...")
        try:
            stored_msgs = RedisClient.get_chat_history(session_id)
            for m in stored_msgs:
                # Redis stores them as dicts with 'sender'/'text' or LangChain JSON
                # The RedisClient.get_chat_history in main.py seems to return raw dicts if inserted via main.py
                # But let's check how RedisClient returns them.
                # Inspecting redis_client.py: it returns json.loads(m).
                # If main.py inserted them, they are dicts like {"sender": "...", "text": "..."}
                
                # Handle dict format from main.py
                if "sender" in m and "text" in m:
                    sender = m["sender"]
                    text = m["text"]
                    if sender == "bot":
                        messages.append(AIMessage(content=text))
                    else:
                        messages.append(HumanMessage(content=text))
                
        except Exception as e:
            print(f"Error fetching history: {e}")

    messages.append(HumanMessage(content=user_input))
    
    init_state: State = {
        "messages": messages,
        "current_input": user_input,
        "last_result": None,
        "route": "out_of_scope",
        "resume_context": resume_context # Injected context
    }

    result = graph.invoke(init_state)
    
    # Optional: If running in stateful mode (session_id present), we should save the NEW message back to Redis?
    # BUT: The 'main.py' handles the saving of the response. 
    # If using 'invoker' from CLI, we might want to save it here to verify persistence.
    # Let's do it ONLY if using session_id (CLI mode usually).
    if session_id:
        from datetime import datetime
        now = datetime.now().isoformat()
        
        # Save User Msg
        RedisClient.add_message(session_id, {"sender": "user", "text": user_input, "time": now})
        
        # Save Bot Msg
        bot_response = result["messages"][-1].content
        RedisClient.add_message(session_id, {"sender": "bot", "text": str(bot_response), "time": now})

    
    if result.get("last_result"):
        return result.get("last_result")
    
    return result["messages"][-1].content

# ---------------------------------------------------
# CLI DEMO
# ---------------------------------------------------
if __name__ == "__main__":
    print(f"Gemini Router Agent Ready 🚀 (Connected to Redis at {redis_host}:{redis_port})")
    
    # Generate or ask for session ID
    sid = input("Enter a Session ID to resume (or press Enter for new): ").strip()
    if not sid:
        import uuid
        sid = str(uuid.uuid4())[:8]
        print(f"Started NEW session: {sid}")
    else:
        print(f"Resuming session: {sid}")

    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in {"exit", "quit"}: break
            
            # Pass session_id so it fetches/saves history
            response = invoker(user_input, session_id=sid)
            print("Bot:", response)
        except KeyboardInterrupt:
            break