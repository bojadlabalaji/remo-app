# in remo-backend/main.py

import os
import sqlite3
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, HTTPException
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, messaging
from fastapi_utilities import repeat_every

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part
from agents import thinker_agent, browser_agent  # Import our agents
from tools import start_interactive_session

# --- Environment & Key Checks ---
print("--- Initializing Remo Backend ---")
load_dotenv()
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError("[FATAL] Missing GOOGLE_API_KEY environment variable. Please check your .env file.")
print("OK: GOOGLE_API_KEY loaded.")

# --- Database Setup ---
DB_NAME = "remo.db"

def init_db():
    """Initializes the SQLite database with the final, rich schema."""
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    print("DB: Creating 'tasks' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            notes TEXT,
            url TEXT,
            due_time TEXT,
            repeat_rule TEXT,
            priority TEXT,
            is_flagged BOOLEAN,
            tags_csv TEXT,
            early_reminder_offset_mins INTEGER,
            status TEXT NOT NULL,
            is_training_required BOOLEAN,
            action_plan_json TEXT,
            training_transcript TEXT,
            creation_date TEXT NOT NULL,
            last_run_log TEXT
        )
    """)
    print("DB: Creating 'push_tokens' table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_tokens (
            user_id TEXT PRIMARY KEY,
            token TEXT NOT NULL
        )
    """)
    db.commit()
    db.close()
    print("OK: Database initialized.")

# --- Firebase Admin SDK Initialization ---
try:
    # IMPORTANT: Place your Firebase service account key file in this directory
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)
    print("OK: Firebase Admin SDK initialized.")
except Exception as e:
    print(f"[WARNING] Could not initialize Firebase: {e}")
    print("[WARNING] Push notification functionality will be disabled.")


# --- Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code to run on startup
    print("--- Running application startup logic ---")
    init_db()
    try:
        cred = credentials.Certificate("secrets/serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
        print("OK: Firebase Admin SDK initialized.")
    except Exception as e:
        print(f"[WARNING] Could not initialize Firebase: {e}")
    # The application is now running. The 'yield' passes control back.
    yield
    # Code to run on shutdown (we don't have any for now)
    print("--- Running application shutdown logic ---")

# --- 1. FastAPI Application Setup ---
app = FastAPI(title="Remo Final Backend", lifespan=lifespan)

@app.on_event("startup")
def on_startup():
    """Run initial setup tasks when the server starts."""
    init_db()

# --- 2. ADK Service Initialization ---
session_service = InMemorySessionService()
browse_runner = Runner(agent=browser_agent, app_name="remo_app", session_service=session_service)
thinker_runner = Runner(agent=thinker_agent, app_name="remo_app", session_service=session_service)
print("OK: ADK Runner initialized.")

# --- 3. Final API Data Models ---

class Task(BaseModel):
    id: str
    user_id: str
    title: str
    notes: str | None = None
    url: str | None = None
    due_time: str | None = None
    repeat_rule: str | None = None
    priority: str | None = None
    is_flagged: bool = False
    tags_csv: str | None = None
    early_reminder_offset_mins: int | None = None
    status: str
    is_training_required: bool
    action_plan_json: str | None = None
    training_transcript: str | None = None
    creation_date: str
    last_run_log: str | None = None

class CreateTaskRequest(BaseModel):
    user_id: str
    title: str
    notes: str | None = None
    url: str | None = None
    due_time: str | None = None
    repeat_rule: str | None = None
    priority: str | None = None
    is_flagged: bool = False
    tags_csv: str | None = None
    early_reminder_offset_mins: int | None = None
    is_training_required: bool = False

class PushTokenRequest(BaseModel):
    user_id: str
    token: str

# Models for direct execution endpoints
class BrowseTaskRequest(BaseModel):
    user_id: str
    url: str
    
class ThinkerTaskRequest(BaseModel):
    user_id: str
    url: str
    goal: str

# --- 4. API Endpoints ---

@app.get("/")
def read_root():
    return {"message": "Remo backend is running."}

@app.post("/tasks", response_model=Task)
async def create_task(request: CreateTaskRequest):
    """Creates a new, feature-rich task and saves it to the database."""
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    new_task_id = "task_" + str(hash(request.title + str(datetime.now())))[:8]
    creation_date_iso = datetime.now(timezone.utc).isoformat()
    new_task = Task(id=new_task_id, creation_date=creation_date_iso, status="pending", **request.model_dump())

    cursor.execute(
        "INSERT INTO tasks (id, user_id, title, notes, url, due_time, repeat_rule, priority, is_flagged, tags_csv, early_reminder_offset_mins, status, is_training_required, action_plan_json, training_transcript, creation_date, last_run_log) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tuple(new_task.model_dump().values())
    )
    db.commit()
    db.close()
    print(f"API: Created rich task '{request.title}'")
    return new_task

@app.get("/tasks/{user_id}", response_model=list[Task])
async def list_tasks_for_user(user_id: str):
    """Fetches all feature-rich tasks for a given user from the database."""
    db = sqlite3.connect(DB_NAME)
    db.row_factory = sqlite3.Row
    cursor = db.cursor()
    cursor.execute("SELECT * FROM tasks WHERE user_id = ?", (user_id,))
    tasks = [dict(row) for row in cursor.fetchall()]
    db.close()
    return tasks

@app.post("/tasks/{task_id}/complete_training")
async def complete_task_training(task_id: str, action_plan: list, transcript: str):
    """Saves the recorded action plan and transcript after a training session."""
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    action_plan_str = json.dumps(action_plan)
    cursor.execute(
        "UPDATE tasks SET action_plan_json = ?, training_transcript = ?, status = 'trained' WHERE id = ?",
        (action_plan_str, transcript, task_id)
    )
    if cursor.rowcount == 0:
        db.close()
        raise HTTPException(status_code=404, detail="Task not found")
    db.commit()
    db.close()
    print(f"API: Saved training data for task {task_id}")
    return {"status": "success", "task_id": task_id}

@app.post("/register-push-token")
async def register_push_token(request: PushTokenRequest):
    """Saves or updates a user's device push token."""
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    cursor.execute("INSERT OR REPLACE INTO push_tokens (user_id, token) VALUES (?, ?)", (request.user_id, request.token))
    db.commit()
    db.close()
    print(f"API: Registered push token for user {request.user_id}")
    return {"status": "success"}

# --- Direct Agent Execution Endpoints (For Testing & "Run Now") ---
@app.post("/execute/browse")
async def execute_browse_task(request: BrowseTaskRequest):
    session = await session_service.create_session(app_name="remo_app", user_id=request.user_id)
    agent_input = Content(role="user", parts=[Part(text=f"Please browse to: {request.url}")])
    final_result = "Agent did not produce a final response."
    events = browse_runner.run_async(user_id=request.user_id, session_id=session.id, new_message=agent_input)
    async for event in events:
        if event.is_final_response(): final_result = event.content.parts[0].text
    return {"status": "completed", "session_id": session.id, "agent_result": final_result}

@app.post("/execute/think")
async def execute_thinker_task(request: ThinkerTaskRequest):
    print(f"API: Received thinker task for goal: '{request.goal}'")
    session = await session_service.create_session(
        app_name="remo_app",
        user_id=request.user_id,
        state={"user_goal": request.goal, "start_url": request.url, "page_observation": ""}
    )
    agent_input = Content(role="user", parts=[Part(text="Start task.")])
    final_result = "Thinker agent finished without a final text response."
    async for event in thinker_runner.run_async(user_id=request.user_id, session_id=session.id, new_message=agent_input):
        if event.is_final_response(): final_result = event.content.parts[0].text
    return {"status": "completed", "final_result": final_result, "session_id": session.id}

@app.websocket("/ws/record/{task_id}/{user_id}")
async def websocket_record_session(websocket: WebSocket, task_id: str, user_id: str):
    """Establishes a WebSocket and starts an interactive rrweb recording session."""
    await websocket.accept()
    print(f"API: WebSocket connection accepted for task {task_id}")
    # In a real app, you'd fetch the task's URL from the DB.
    start_url = "https://google.github.io/adk-docs/"
    try:
        await start_interactive_session(url=start_url, websocket=websocket)
    except Exception as e:
        print(f"WebSocket session for task {task_id} encountered an error: {e}")
    finally:
        print(f"WebSocket connection for task {task_id} closed.")

# --- Background Scheduler ---
@repeat_every(seconds=60, wait_first=True)
async def check_reminders() -> None:
    """Periodically checks the DB for due reminders and sends push notifications."""
    print("Scheduler: Checking for due reminders...")
    db = sqlite3.connect(DB_NAME)
    cursor = db.cursor()
    current_time_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("SELECT id, user_id, title FROM tasks WHERE due_time <= ? AND status = 'pending'", (current_time_iso,))
    due_reminders = cursor.fetchall()
    
    if not due_reminders:
        print("Scheduler: No reminders due at this time.")
        db.close()
        return

    for task_id, user_id, title in due_reminders:
        cursor.execute("SELECT token FROM push_tokens WHERE user_id = ?", (user_id,))
        token_row = cursor.fetchone()
        if token_row:
            push_token = token_row[0]
            print(f"Scheduler: Sending notification for '{title}' to user {user_id}")
            message = messaging.Message(
                notification=messaging.Notification(title="Remo Reminder!", body=title),
                token=push_token,
            )
            try:
                messaging.send(message)
                cursor.execute("UPDATE tasks SET status = 'notified' WHERE id = ?", (task_id,))
                db.commit()
                print(f"Scheduler: Task {task_id} marked as 'notified'.")
            except Exception as e:
                print(f"FCM Error for task {task_id}: {e}")
    
    db.close()