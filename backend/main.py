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

load_dotenv()
mongodb = os.getenv("MONGODB")

from agent import invoker
from QuestionPapers.pdf_processor import process_single_pdf
from Dreamer.dreamer.app import run_resume_pipeline

client = MongoClient(mongodb)
db = client["chat_app"]
conversations_col = db["conversations"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
            messages = conv.get("messages", [])
            
            # Check if conversation has any non-empty messages
            has_messages = False
            if messages:
                for msg in messages:
                    text = msg.get("text", "")
                    if text and text.strip() != "":
                        has_messages = True
                        break
            
            # Mark for deletion if it has no meaningful messages
            if not has_messages:
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
    oid = ObjectId(conv_id)
    doc = conversations_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Conversation not found")
    return {"messages": doc.get("messages", [])}


@app.post("/conversations/{conv_id}/messages")
def add_message(conv_id: str, msg: Message):
    oid = ObjectId(conv_id)

    # Load conversation history from database
    doc = conversations_col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Conversation not found")
    
    conversation_history = doc.get("messages", [])

    now_iso = datetime.now().isoformat()

    user_msg = {
        "sender": msg.sender,
        "text": msg.text,
        "time": now_iso,
    }

    try:
        # Pass conversation history to invoker for memory
        raw_reply = invoker(msg.text, conversation_history=conversation_history)
    except Exception as e:
        raw_reply = f"Couldn't call the backend agent: {e}"

    now_iso = datetime.now().isoformat()

    bot_messages = []

    # If the agent returned a structured response (dict with 'answer' and 'links')
    if isinstance(raw_reply, dict):
        answer_text = strip_html_if_any(str(raw_reply.get("answer", "")))
        bot_messages.append({"sender": "bot", "text": answer_text, "time": now_iso})

        # Append ONE link-only bot message per URL
        for link in raw_reply.get("links", []):
            bot_messages.append({"sender": "bot", "text": str(link), "time": datetime.now().isoformat()})

        # Push user message and then bot messages
        conversations_col.update_one(
            {"_id": oid},
            {"$push": {"messages": {"$each": [user_msg] + bot_messages}}}
        )

    else:
        bot_clean = strip_html_if_any(str(raw_reply))
        bot_msg = {"sender": "bot", "text": bot_clean, "time": now_iso}
        bot_messages.append(bot_msg)

        conversations_col.update_one(
            {"_id": oid},
            {"$push": {"messages": {"$each": [user_msg, bot_msg]}}}
        )

    # Return only the newly added messages (user + bot), not all messages
    all_messages = [user_msg] + bot_messages
    return {"messages": all_messages}



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

        if result["status"] != "Success":
            bot_text = f"PDF processing failed: {result.get('status', 'Unknown error')}"
        else:
            bot_text = f"PDF processed successfully"
    elif pdf_type == "ResumePDF":
        uploads_dir = os.path.join("Dreamer", "dreamer", "uploads")
        os.makedirs(uploads_dir, exist_ok=True)
        path = os.path.join(uploads_dir, file.filename)
        with open(path, "wb") as out:
            out.write(content)

        try:
            vari = run_resume_pipeline(path).get("ranked_jobs", [])[:5]
            formatted_jobs = []
            for i, job in enumerate(vari):  # Show top 5 only
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

    conversations_col.update_one(
        {"_id": oid},
        {
            "$push": {
                "pdfs": pdf_entry,
                "messages": bot_msg
            }
        }
    )

    return {"filename": file.filename, "type": pdf_type, "bot_text": bot_text}
