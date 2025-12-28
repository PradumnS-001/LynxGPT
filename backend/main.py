from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from pymongo import MongoClient
from datetime import datetime
import re
import os
from dotenv import load_dotenv

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


@app.get("/conversations", response_model=List[ConversationOut])
def get_conversations():
    docs = conversations_col.find({})
    return [conv_to_out(d) for d in docs]


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
def rename_conversation(conv_id: str, body: dict):
    oid = ObjectId(conv_id)
    conversations_col.update_one(
        {"_id": oid},
        {"$set": {"title": body["title"]}}
    )
    doc = conversations_col.find_one({"_id": oid})
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

    now_iso = datetime.now().isoformat()

    user_msg = {
        "sender": msg.sender,
        "text": msg.text,
        "time": now_iso,
    }

    try:
        raw_reply = invoker(msg.text)
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
