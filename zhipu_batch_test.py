import httpx
import time
import os
import json

# --- Configuration ---
ZHIPU_API_KEY = "3b27bf28511a466aac7b8eb203de88f0.L7GHV5ioYKHGJqhm" # Will be prompted
JSONL_FILE_PATH = "my_test_batch.jsonl" # Path to your .jsonl file

BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
UPLOAD_URL = f"{BASE_URL}/files"
BATCH_URL = f"{BASE_URL}/batches"

HEADERS = {
    "Accept": "application/json",
}

def get_api_key():
    global ZHIPU_API_KEY, HEADERS
    api_key_env = os.getenv("ZHIPU_API_KEY")
    if api_key_env:
        print("Found ZHIPU_API_KEY in environment variables.")
        ZHIPU_API_KEY = api_key_env
    else:
        ZHIPU_API_KEY = input("Please enter your Zhipu AI API Key: ").strip()
    
    if not ZHIPU_API_KEY:
        print("API Key is required. Exiting.")
        exit(1)
    HEADERS["Authorization"] = f"Bearer {ZHIPU_API_KEY}"
    

def upload_file(client: httpx.Client, file_path: str) -> str | None:
    print(f"Uploading file: {file_path}...")
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None
        
    files = {"file": (os.path.basename(file_path), open(file_path, "rb"), "application/jsonl")}
    data = {"purpose": "batch"}
    
    try:
        # Debug: Print request details before sending
        request = client.build_request("POST", UPLOAD_URL, files=files, data=data, headers=HEADERS)
        print(f"DEBUG: Request method before sending: {request.method}")
        print(f"DEBUG: Request URL: {request.url}")
        print(f"DEBUG: Request headers: {request.headers}")  # 打印请求头以便调试

        response = client.send(request)
        response.raise_for_status() # Raise an exception for HTTP errors
        result = response.json()
        file_id = result.get("id")
        print(f"File uploaded successfully. File ID: {file_id}")
        print(f"Full upload response: {json.dumps(result, indent=2)}")
        return file_id
    except httpx.HTTPStatusError as e:
        print(f"Error uploading file: {e}")
        print(f"Response content: {e.response.text}")
    except Exception as e:
        print(f"An unexpected error occurred during file upload: {e}")
    return None

def create_batch_job(client: httpx.Client, file_id: str) -> str | None:
    print(f"Creating batch job for file ID: {file_id}...")
    payload = {
        "input_file_id": file_id,
        "endpoint": "/v4/chat/completions",
        "completion_window": "24h",
        "method": "POST",
        "metadata": {
            "description": "SDK Test Batch Job via Python script"
        }
    }
    try:
        # Add Content-Type for POST request with JSON payload
        post_headers = HEADERS.copy()
        post_headers["Content-Type"] = "application/json"
        response = client.post(BATCH_URL, json=payload, headers=post_headers)
        response.raise_for_status()
        result = response.json()
        batch_id = result.get("id")
        print(f"Batch job created successfully. Batch ID: {batch_id}")
        print(f"Full batch creation response: {json.dumps(result, indent=2)}")
        return batch_id
    except httpx.HTTPStatusError as e:
        print(f"Error creating batch job: {e}")
        print(f"Response content: {e.response.text}")
    except Exception as e:
        print(f"An unexpected error occurred during batch job creation: {e}")
    return None

def check_batch_status(client: httpx.Client, batch_id: str) -> dict | None:
    print(f"Checking status for batch ID: {batch_id}...")
    try:
        response = client.get(f"{BATCH_URL}/{batch_id}", headers=HEADERS)
        response.raise_for_status()
        result = response.json()
        print(f"Batch status: {result.get('status')}")
        print(f"Full status response: {json.dumps(result, indent=2)}")
        return result
    except httpx.HTTPStatusError as e:
        print(f"Error checking batch status: {e}")
        print(f"Response content: {e.response.text}")
    except Exception as e:
        print(f"An unexpected error occurred while checking batch status: {e}")
    return None

def retrieve_batch_result_content(client: httpx.Client, file_id: str) -> str | None:
    print(f"Retrieving content for result file ID: {file_id}...")
    try:
        response = client.get(f"{UPLOAD_URL}/{file_id}/content", headers=HEADERS)
        response.raise_for_status()
        # The response for file content is typically the raw content, not JSON
        # However, Zhipu's batch output might be a JSONL string.
        result_content = response.text
        print("Successfully retrieved result file content.")
        # print(f"Result content: {result_content}") # Can be very long. Corrected to single line.
        return result_content
    except httpx.HTTPStatusError as e:
        print(f"Error retrieving result file content: {e}")
        print(f"Response content: {e.response.text}")
    except Exception as e:
        print(f"An unexpected error occurred while retrieving result file content: {e}")
    return None


def main():
    get_api_key()

    with httpx.Client(timeout=60.0) as client: # Increased timeout
        # Step 1: Upload file
        uploaded_file_id = upload_file(client, JSONL_FILE_PATH)
        if not uploaded_file_id:
            return

        # Step 2: Create batch job
        batch_job_id = create_batch_job(client, uploaded_file_id)
        if not batch_job_id:
            return

        # Step 3: Poll for batch job completion
        print(f"Polling status for batch job {batch_job_id} every 30 seconds...")
        final_status_info = None
        while True:
            status_info = check_batch_status(client, batch_job_id)
            if not status_info:
                print("Failed to get status, stopping.")
                return

            status = status_info.get("status")
            if status in ["completed", "failed", "cancelled"]:
                print(f"Batch job {status}. Final details:")
                print(json.dumps(status_info, indent=2, ensure_ascii=False))
                final_status_info = status_info
                break
            
            # Log progress if available
            if status_info.get("request_counts"):
                print(f"Progress: {status_info['request_counts']}")

            time.sleep(30) # Wait for 30 seconds before polling again

        # Step 4: Retrieve and print results if completed successfully
        if final_status_info and final_status_info.get("status") == "completed":
            output_file_id = final_status_info.get("output_file_id")
            error_file_id = final_status_info.get("error_file_id")

            if output_file_id:
                print(f"--- Output File (ID: {output_file_id}) ---")
                output_content = retrieve_batch_result_content(client, output_file_id)
                if output_content:
                    # Process and print each JSON line from the output
                    print("Output Content (parsed line by line):")
                    for line in output_content.strip().split('\n'):
                        if line:
                            try:
                                parsed_line = json.loads(line)
                                print(json.dumps(parsed_line, indent=2, ensure_ascii=False))
                            except json.JSONDecodeError:
                                print(f"Could not parse line as JSON: {line}")
                        
            if error_file_id:
                print(f"--- Error File (ID: {error_file_id}) ---")
                error_content = retrieve_batch_result_content(client, error_file_id)
                if error_content:
                    print("Error Content (parsed line by line):")
                    for line in error_content.strip().split('\n'):
                        if line:
                            try:
                                parsed_line = json.loads(line)
                                print(json.dumps(parsed_line, indent=2, ensure_ascii=False))
                            except json.JSONDecodeError:
                                print(f"Could not parse line as JSON: {line}")
        elif final_status_info:
            print(f"Batch job did not complete successfully. Status: {final_status_info.get('status')}")
            error_file_id = final_status_info.get("error_file_id")
            if error_file_id:
                print(f"--- Error File (ID: {error_file_id}) ---")
                error_content = retrieve_batch_result_content(client, error_file_id)
                if error_content:
                    print("Error Content (parsed line by line):")
                    for line in error_content.strip().split('\n'):
                        if line:
                            try:
                                parsed_line = json.loads(line)
                                print(json.dumps(parsed_line, indent=2, ensure_ascii=False))
                            except json.JSONDecodeError:
                                print(f"Could not parse line as JSON: {line}")


if __name__ == "__main__":
    main() 