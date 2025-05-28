from fastapi import FastAPI, BackgroundTasks
import time
from datetime import datetime
import os # For path joining

app = FastAPI()

# Define a directory for the log file (e.g., in the same directory as the script)
LOG_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(LOG_DIR, "mvp_bg_task.log")

def write_log_task(message: str):
    # Ensure the function starts by printing to console immediately
    print(f"[{datetime.now()}] MVP_BG_TASK_DEBUG: write_log_task started with message: '{message}'")
    
    # Simulate some work that might take time
    time.sleep(2) 
    
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now()}] {message}\n")
        print(f"[{datetime.now()}] MVP_BG_TASK_DEBUG: Message written to log file: '{LOG_FILE}'")
    except Exception as e:
        print(f"[{datetime.now()}] MVP_BG_TASK_DEBUG: ERROR writing to log file '{LOG_FILE}': {e}")
    
    print(f"[{datetime.now()}] MVP_BG_TASK_DEBUG: write_log_task finished.")

@app.post("/trigger-task/") # Changed to POST for clarity, can be GET too
async def trigger_background_task(background_tasks: BackgroundTasks):
    task_message = "Hello from MVP background task!"
    print(f"[{datetime.now()}] MVP_ENDPOINT_DEBUG: Endpoint /trigger-task/ called. Adding task with message: '{task_message}'")
    background_tasks.add_task(write_log_task, task_message)
    print(f"[{datetime.now()}] MVP_ENDPOINT_DEBUG: Task added to background_tasks.")
    return {"status": "success", "message": "Background task added. Check console and mvp_bg_task.log."}

if __name__ == "__main__":
    import uvicorn
    # Get the filename without the .py extension to use as the module name for Uvicorn
    module_name = os.path.splitext(os.path.basename(__file__))[0]
    print(f"To run this MVP, use: uvicorn {module_name}:app --port 8001")
    print(f"Then, send a POST request to http://localhost:8001/trigger-task/")
    # uvicorn.run(f"{module_name}:app", host="0.0.0.0", port=8001, reload=False) # Optional: run directly 