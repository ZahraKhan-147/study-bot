# main.py

import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage
from pymongo import MongoClient
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from bson import ObjectId
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

# Load environment variables
load_dotenv()

# --- Database Setup ---
mongo_uri = os.getenv("MONGO_URI")
if not mongo_uri:
    raise ValueError("MONGO_URI not set in environment variables")

client = MongoClient(mongo_uri)
db = client["study_bot_db"]
conversations = db["conversations"]

# --- AI Model Setup ---
groq_api_key = os.getenv("GROQ_API_KEY")
if not groq_api_key:
    raise ValueError("GROQ_API_KEY not set in environment variables")

llm = ChatGroq(
    model="llama-3.3-70b-versatile", 
    temperature=0.7,
    groq_api_key=groq_api_key
)
# --- FastAPI App ---
app = FastAPI(
    title="Study Bot API",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Pydantic Models ---
class ChatRequest(BaseModel):
    message: str
    conversation_id: str = None

class ChatResponse(BaseModel):
    response: str
    conversation_id: str

# --- Helper Functions ---
def get_or_create_conversation(conversation_id=None):
    """Gets an existing conversation or creates a new one."""
    if conversation_id:
        try:
            conv = conversations.find_one({"_id": ObjectId(conversation_id)})
            if conv:
                return conv
        except:
            pass
    
    new_conv = {
        "messages": [],
        "created_at": datetime.now()
    }
    result = conversations.insert_one(new_conv)
    new_conv["_id"] = result.inserted_id
    return new_conv

def add_message(conversation_id, role, content):
    """Adds a message to a conversation."""
    conversations.update_one(
        {"_id": conversation_id},
        {
            "$push": {
                "messages": {
                    "role": role,
                    "content": content,
                    "timestamp": datetime.now()
                }
            }
        }
    )

def get_recent_messages(conversation_id, limit=5):
    """Gets the last few messages for context."""
    conv = conversations.find_one({"_id": conversation_id})
    if conv and "messages" in conv:
        return conv["messages"][-limit:]
    return []

# --- API Endpoints ---
@app.get("/")
async def root():
    return {"message": "Welcome to the Study Bot API! Use /chat to talk to the bot."}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint."""
    try:
        # Get or create conversation
        conversation = get_or_create_conversation(request.conversation_id)
        conv_id = conversation["_id"]
        
        # Get recent messages for context
        recent = get_recent_messages(conv_id)
        
        # Build messages for AI
        messages_for_ai = []
        
        # Add system message (using proper format)
        messages_for_ai.append({
            "role": "system", 
            "content": "You are a helpful study assistant. You help students with their academic questions. Always explain concepts step by step and use simple analogies. If a student seems confused, offer to explain differently.Be clear, patient, and educational in your responses."
        })
        
        # Add conversation history - using the correct message format
        for msg in recent:
            if msg["role"] == "human":
                messages_for_ai.append(HumanMessage(content=msg["content"]))
            else:
                messages_for_ai.append(AIMessage(content=msg["content"]))
        
        # Add new message
        messages_for_ai.append(HumanMessage(content=request.message))
        
        # Get AI response
        response = llm.invoke(messages_for_ai)
        
        # Save to database
        add_message(conv_id, "human", request.message)
        add_message(conv_id, "ai", response.content)
        
        return ChatResponse(
            response=response.content,
            conversation_id=str(conv_id)
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/conversation/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Retrieve a conversation history."""
    try:
        conv = conversations.find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conv["_id"] = str(conv["_id"])
        return conv
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Run the app ---
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)