from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from pymongo import MongoClient
from datetime import datetime
import re
import os
from dotenv import load_dotenv
import asyncio

from pathlib import Path
import traceback  # Import traceback

env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)
mongodb = os.getenv("MONGODB")
print(f"DEBUG: Loaded env from {env_path}")
print(f"DEBUG: REDIS_HOST={os.getenv('REDIS_HOST')}")
print(f"DEBUG: REDIS_PORT={os.getenv('REDIS_PORT')}")

from agent import invoker
from QuestionPapers.pdf_processor import process_single_pdf
from Dreamer.dreamer.app import run_resume_pipeline
from database.redis_client import RedisClient

client = MongoClient(mongodb)
db = client["chat_app"]
conversations_col = db["conversations"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost",
        "http://127.0.0.1"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check():
    """Health check endpoint for Docker healthcheck."""
    return {"status": "healthy"}


class Message(BaseModel):
    sender: str
    text: str
    time: Optional[str] = None


class ConversationOut(BaseModel):
    id: str
    title: str
    isStarred: bool = False


def conv_to_out(doc) -> ConversationOut:
    return ConversationOut(
        id=str(doc["_id"]),
        title=doc.get("title", "Untitled"),
        isStarred=doc.get("isStarred", False),
    )


def strip_html_if_any(text: str) -> str:
    if "<" in text and ">" in text:
        return re.sub(r"<[^>]+>", "", text)
    return text


def purge_empty_conversations():
    """Remove conversations that have no messages or only empty messages."""
    try:
        # Find all conversations
        conversations = list(conversations_col.find({}))
        
        # Collect IDs of conversations to delete (to avoid modifying while iterating)
        ids_to_delete = []
        
        for conv in conversations:
            conv_id = str(conv["_id"])
            messages = conv.get("messages", [])
            
            # 1. Check if conversation has messages in Mongo
            has_messages = False
            if messages:
                for msg in messages:
                    text = msg.get("text", "")
                    if text and text.strip() != "":
                        has_messages = True
                        break
            
            if has_messages:
                continue

            # 2. Check if conversation has messages in Redis (active session)
            # If so, do NOT delete it yet.
            redis_msgs = RedisClient.get_chat_history(conv_id)
            if redis_msgs:
                continue
            
            # 3. Mark for deletion if it has no meaningful messages in either DB
            ids_to_delete.append(conv["_id"])
        
        # Delete all empty conversations
        if ids_to_delete:
            conversations_col.delete_many({"_id": {"$in": ids_to_delete}})
    except Exception as e:
        print(f"Error purging empty conversations: {e}")


@app.post("/conversations/purge-empty")
def purge_empty_conversations_endpoint():
    """Synchronous endpoint to purge empty conversations."""
    purge_empty_conversations()
    return {"status": "success"}


@app.get("/conversations", response_model=List[ConversationOut])
def get_conversations():
    docs = conversations_col.find({})
    return [conv_to_out(d) for d in docs]


@app.delete("/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    oid = ObjectId(conv_id)
    result = conversations_col.delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise HTTPException(404, "Conversation not found")
    return {"status": "success"}


@app.post("/conversations", response_model=ConversationOut)
def create_conversation():
    data = {
        "title": "Chat " + str(ObjectId())[-4:],
        "isStarred": False,
        "messages": [],
        "pdfs": []
    }
    result = conversations_col.insert_one(data)
    data["_id"] = result.inserted_id
    return conv_to_out(data)


@app.patch("/conversations/{conv_id}", response_model=ConversationOut)
def update_conversation(conv_id: str, body: dict):
    oid = ObjectId(conv_id)
    update_data = {}
    
    if "title" in body:
        update_data["title"] = body["title"]
    if "isStarred" in body:
        update_data["isStarred"] = body["isStarred"]
    
    if update_data:
        conversations_col.update_one(
            {"_id": oid},
            {"$set": update_data}
        )
    
    doc = conversations_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Conversation not found")
    return conv_to_out(doc)


@app.patch("/conversations/{conv_id}/star", response_model=ConversationOut)
def toggle_star(conv_id: str):
    oid = ObjectId(conv_id)
    doc = conversations_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Conversation not found")
    
    new_starred = not doc.get("isStarred", False)
    conversations_col.update_one(
        {"_id": oid},
        {"$set": {"isStarred": new_starred}}
    )
    doc["isStarred"] = new_starred
    return conv_to_out(doc)


@app.get("/conversations/{conv_id}/messages")
def get_messages(conv_id: str):
    # Try Redis first
    messages = RedisClient.get_chat_history(conv_id)
    
    # Check if we need to hydrate from Mongo
    if not messages:
        # Fallback to Mongo if empty (e.g. old chat or expired)
        oid = ObjectId(conv_id)
        doc = conversations_col.find_one({"_id": oid})
        if not doc:
            raise HTTPException(404, "Conversation not found")
        messages = doc.get("messages", [])
        
        # Hydrate Chat History to Redis
        for msg in messages:
            RedisClient.add_message(conv_id, msg)
            
        # Hydrate Resume Context to Redis (if exists)
        candidate_info = doc.get("candidate_info")
        if candidate_info:
             RedisClient.save_resume_context(conv_id, candidate_info)
             print(f"Hydrated resume context for {conv_id}")
            
    return {"messages": messages}


@app.post("/conversations/{conv_id}/messages")
def add_message(conv_id: str, msg: Message):
    try:
        # Retrieve history from Redis
        conversation_history = RedisClient.get_chat_history(conv_id)
        
        # Check for resume context in Redis
        resume_context = RedisClient.get_resume_context(conv_id)
        
        # Check for job context in Redis
        job_context = RedisClient.get_job_context(conv_id)
    
        now_iso = datetime.now().isoformat()
    
        user_msg = {
            "sender": msg.sender,
            "text": msg.text,
            "time": now_iso,
        }
        
        # Store User Message in Redis
        RedisClient.add_message(conv_id, user_msg)
        
        # Pass history + resume context + job_context to invoker
        try:
            raw_reply = invoker(
                msg.text, 
                conversation_history=conversation_history,
                resume_context=resume_context,
                job_context=job_context
            )
        except Exception as e:
            raw_reply = f"Couldn't call the backend agent: {e}"
            traceback.print_exc()
    
        now_iso = datetime.now().isoformat()
        bot_messages = []
    
        # If the agent returned a structured response (dict with 'answer' and 'links')
        if isinstance(raw_reply, dict):
            answer_text = strip_html_if_any(str(raw_reply.get("answer", "")))
            
            # Main bot answer
            main_bot_msg = {"sender": "bot", "text": answer_text, "time": now_iso}
            bot_messages.append(main_bot_msg)
            RedisClient.add_message(conv_id, main_bot_msg)
    
            # Append ONE link-only bot message per URL
            for link in raw_reply.get("links", []):
                link_msg = {"sender": "bot", "text": str(link), "time": datetime.now().isoformat()}
                bot_messages.append(link_msg)
                RedisClient.add_message(conv_id, link_msg)
    
        else:
            bot_clean = strip_html_if_any(str(raw_reply))
            bot_msg = {"sender": "bot", "text": bot_clean, "time": now_iso}
            bot_messages.append(bot_msg)
            RedisClient.add_message(conv_id, bot_msg)
    
        # Return new messages
        all_new_messages = [user_msg] + bot_messages
        return {"messages": all_new_messages}

    except Exception as e:
        print("CRITICAL ERROR in add_message:")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def flush_conversation_to_mongo(conv_id: str):
    """
    Persist Redis chat history AND resume context to MongoDB.
    This effectively 'saves' the session.
    """
    try:
        messages = RedisClient.get_chat_history(conv_id)
        resume_context = RedisClient.get_resume_context(conv_id) # Get from Redis
        
        if not messages and not resume_context:
            return  # Nothing to save

        oid = ObjectId(conv_id)
        
        # Prepare update data
        update_data = {
            "last_updated": datetime.now().isoformat()
        }
        if messages:
             update_data["messages"] = messages
        if resume_context:
             update_data["candidate_info"] = resume_context

        # Overwrite/Update MongoDB
        conversations_col.update_one(
            {"_id": oid},
            {"$set": update_data}
        )
        print(f"Flushed session (msgs={len(messages)}, resume={bool(resume_context)}) to MongoDB for {conv_id}")
    except Exception as e:
        print(f"Error flushing to Mongo: {e}")
        traceback.print_exc()


@app.post("/conversations/{conv_id}/end")
def end_session(conv_id: str, background_tasks: BackgroundTasks):
    """
    End the chat session:
    1. Flush history from Redis to MongoDB.
    2. (Optional) Clear Redis key if you want to free memory immediately, 
       but keeping it for 24h (TTL) is usually safer for 'viewing' history.
    """
    # Run storage in background so UI returns instantly
    background_tasks.add_task(flush_conversation_to_mongo, conv_id)
    return {"status": "session_ended", "message": "Flushing to database in background"}



@app.post("/conversations/{conv_id}/upload_pdf/{pdf_type}")
def upload_pdf(conv_id: str, pdf_type: str, file: UploadFile = File(...)):
    if pdf_type not in ["ResumePDF", "QuestionPapersPDF"]:
        raise HTTPException(400, "Invalid PDF type")

    if file.content_type != "application/pdf":
        raise HTTPException(400, "Not a PDF")

    content = file.file.read()
    oid = ObjectId(conv_id)
    now_iso = datetime.now().isoformat()
    size = len(content)

    pdf_entry = {
        "type": pdf_type,
        "filename": file.filename,
        "size": size,
        "data": content,
        "time": now_iso,
    }

    bot_text = f"Uploaded {pdf_type}: {file.filename} (size: {size} bytes)"

    if pdf_type == "QuestionPapersPDF":
        result = process_single_pdf(content, file.filename)
        print("PDF Processor Result:", result)

        if result["status"] == "Success":
            bot_text = f"PDF processed successfully"
        elif result["status"] == "Duplicate":
            bot_text = result.get("message", "This file is already in the database.")
        else:
            bot_text = f"PDF processing failed: {result.get('message', result.get('status', 'Unknown error'))}"
    elif pdf_type == "ResumePDF":
        uploads_dir = os.path.join("Dreamer", "dreamer", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        path = os.path.join(uploads_dir, file.filename)
        with open(path, "wb") as out:
            out.write(content)

        try:
            result = run_resume_pipeline(path)
            candidate_info = result["candidate_info"]
            ranked_jobs = result["ranked_jobs"][:5]
            
            # Save candidate info to Redis for Context Awareness
            RedisClient.save_resume_context(conv_id, candidate_info)
            
            # Save job recommendations to Redis for Context Awareness
            RedisClient.save_job_context(conv_id, ranked_jobs)
            
            formatted_jobs = []
            for i, job in enumerate(ranked_jobs):  # Show top 5 only
                formatted_jobs.append(
                    f"{i+1}. {job.get('title')} @ {job.get('company')}\n"
                    f"Location: {job.get('location', 'Not specified')}\n"
                    f"Experience: {job.get('min_exp', 'N/A')}\n"
                    f"Salary: {job.get('salary', 'Not disclosed') if 'salary' in job else 'Not disclosed'}\n"
                )
            print(formatted_jobs)

            bot_text = "Here are your best matched jobs based on your resume:\n\n" + "\n\n".join(formatted_jobs)

        except Exception as e:
            bot_text = f"Encountered error while processing resume: {e}"

    bot_msg = {
        "sender": "bot",
        "text": bot_text,
        "time": now_iso,
    }
    
    # Store Bot Response in Redis
    RedisClient.add_message(conv_id, bot_msg)

    # Optional: Still saving PDF record to Mongo for persistence (metadata only)
    conversations_col.update_one(
        {"_id": oid},
        {
            "$push": {
                "pdfs": pdf_entry
                # We do NOT push messages to Mongo here anymore
            }
        }
    )

    return {"filename": file.filename, "type": pdf_type, "bot_text": bot_text}
