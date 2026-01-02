# Backend Setup

## Prerequisites

### 1. Python Dependencies
Install the required Python packages:
```bash
pip install -r requirements.txt
```

### 2. Redis Server (Required for Persistent Memory)
The application uses Redis to store chat history and resume contexts. You must have a Redis server running locally.

**Windows Installation (Easiest)**
1. Download the [Redis-x64-3.0.504.msi](https://github.com/microsoftarchive/redis/releases/download/win-3.0.504/Redis-x64-3.0.504.msi).
2. Run the installer and ensure "Add to PATH" is checked.
3. Open a new terminal and type `redis-cli ping`. It should return `PONG`.

**Docker Installation**
```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

**Note:** If Redis is NOT running, the application will automatically fall back to **in-memory storage**. This means the app will work, but chat history will be lost every time you restart the backend server.

## Running the App

Start the server:
```bash
uvicorn main:app --reload
```

## CLI Agent Demo
To test the agent logic directly in the terminal:
```bash
python agent.py
```
You can enter a session ID to resume a previous conversation (if Redis is running).
