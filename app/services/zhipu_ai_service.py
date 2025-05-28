import httpx
import asyncio
import json
import time
import jwt # New dependency: PyJWT
import io
from typing import List, Dict, Any, Optional, Tuple, Callable
from fastapi import HTTPException, status, BackgroundTasks
from datetime import datetime
import traceback

# 添加任务状态枚举
from enum import Enum
class TaskStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

# 全局任务状态存储（实际项目中应该使用数据库）
# translation_tasks: Dict[str, Dict] = {}

# TODO: Make these configurable if necessary, potentially via settings
ZHIPU_API_BASE_URL = "https://open.bigmodel.cn/api/paas"
# Token expiration time in seconds (e.g., 1 hour)
TOKEN_EXPIRATION_SECONDS = 3600
# Polling interval in seconds - increased for longer running jobs
POLLING_INTERVAL_SECONDS = 10  # Changed from 5 to 10 seconds to reduce API calls
# Max polling attempts - increased to cover ~20 minutes
MAX_POLLING_ATTEMPTS = 540     # Increased from 120 to 540 (90 minutes at 10s interval)

# Placeholder for Zhipu AI Batch API endpoint - this was for the stub.
# We will use specific endpoints like /v4/files and /v4/batches
# ZHIPU_BATCH_API_ENDPOINT = "https://example.com/zhipu/batch_translate" # Not used anymore

# Standard model if not specified by user or if batch API has a default
DEFAULT_ZHIPU_MODEL = "glm-4" # Example, check documentation for batch API compatible models

# --- Helper function to generate Zhipu API JWT token ---
def generate_zhipu_token(api_key: str) -> str:
    """
    Generates a JWT token for Zhipu AI API authentication.
    The api_key is expected in the format "id.secret".
    """
    try:
        key_id, secret = api_key.split(".")
    except ValueError:
        # This error occurs if the api_key is not in "id.secret" format
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Zhipu API Key format. Expected 'id.secret'."
        )
    except Exception as e:
        # Catch any other unexpected error during split
        print(f"Error splitting API Key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing Zhipu API Key."
        )

    payload = {
        "api_key": key_id,
        "exp": int(round(time.time() * 1000)) + TOKEN_EXPIRATION_SECONDS * 1000,
        "timestamp": int(round(time.time() * 1000)),
    }
    # HS256 is the algorithm Zhipu uses
    token = jwt.encode(
        payload,
        secret,
        algorithm="HS256",
        headers={"alg": "HS256", "sign_type": "SIGN"}
    )
    return token

# REMOVING create_translation_task, get_task_status, update_task_status as zhipu_ai_service will no longer manage this state directly.
# The calling service (translation_job_service) will manage the main job state.

async def background_poll_status(
    main_job_id: str,       # ID of the job in the calling service (e.g., translation_job_service)
    zhipu_batch_id: str,    # ID of the batch job from Zhipu API
    api_key: str,
    update_callback: Callable, # Callback function to update state in the calling service
    chunk_id: Optional[str] = None # New: ID of the chunk if this is part of a larger job
) -> None:
    """后台轮询智谱批量任务状态，并通过回调更新主服务中的作业状态"""
    print(f"[{datetime.now()}] ZP_POLL_DEBUG: *** background_poll_status TASK ATTEMPTING TO START for ZhipuBatchID: {zhipu_batch_id}, Chunk: {chunk_id} ***")
    try:
        print(f"\n\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"[{datetime.now()}] !!! ZHIPU_BACKGROUND_POLL_STATUS HAS STARTED !!! For Main Job ID: {main_job_id}, Zhipu Batch ID: {zhipu_batch_id}, Chunk ID: {chunk_id or 'N/A'}")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n\n")
        # 新增日志：确认函数开始
        print(f"[{datetime.now()}] ZP_POLL_DEBUG: background_poll_status ENTERED for ZhipuBatchID: {zhipu_batch_id}, Chunk: {chunk_id}")

        headers = {
            "Authorization": f"Bearer {generate_zhipu_token(api_key)}",
            "Accept": "application/json"
        }
        
        async with httpx.AsyncClient(timeout=60.0) as client:
            attempts = 0
            while attempts < MAX_POLLING_ATTEMPTS:
                attempts += 1
                print(f"[{datetime.now()}] ZP_POLL_DEBUG: Attempt {attempts}/{MAX_POLLING_ATTEMPTS} for ZhipuBatchID: {zhipu_batch_id}, Chunk: {chunk_id}. About to make API call.")
                try:
                    if attempts > 1 and time.time() % (TOKEN_EXPIRATION_SECONDS // 2) < POLLING_INTERVAL_SECONDS * 2:
                        print(f"[{datetime.now()}] ZHIPU_BACKGROUND_POLL: Refreshing Zhipu token for Zhipu Batch ID: {zhipu_batch_id}")
                        headers["Authorization"] = f"Bearer {generate_zhipu_token(api_key)}"

                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: Calling Zhipu API: GET /v4/batches/{zhipu_batch_id}")
                    status_response = await client.get(
                        f"{ZHIPU_API_BASE_URL}/v4/batches/{zhipu_batch_id}",
                        headers=headers
                    )
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: Zhipu API call completed. Status code: {status_response.status_code} for ZhipuBatchID: {zhipu_batch_id}")
                    status_response.raise_for_status()
                    status_result = status_response.json()
                    current_zhipu_job_status = status_result.get("status")
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: ZhipuBatchID '{zhipu_batch_id}' raw status from API: '{current_zhipu_job_status}'")

                    if current_zhipu_job_status == "completed":
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: ZhipuBatchID '{zhipu_batch_id}' is COMPLETED. Preparing to call update_callback.")
                        output_file_id = status_result.get("output_file_id")
                        if not output_file_id:
                            error_msg = "Zhipu batch job completed but no output_file_id found"
                            print(f"[{datetime.now()}] ZP_POLL_DEBUG: Calling update_callback for ZhipuBatchID '{zhipu_batch_id}' with FAILED (no output_file_id).")
                            await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                            print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for FAILED (no output_file_id) ZhipuBatchID '{zhipu_batch_id}'. Breaking loop.")
                            break

                        results = await download_and_process_results(client, headers, output_file_id)
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: Results downloaded for ZhipuBatchID {zhipu_batch_id}. Calling update_callback with COMPLETED.")
                        await update_callback(main_job_id, TaskStatus.COMPLETED, progress=100, result=results, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for COMPLETED ZhipuBatchID '{zhipu_batch_id}'. Breaking loop.")
                        break

                    elif current_zhipu_job_status in ["failed", "cancelled"]:
                        error_message = f"Zhipu batch job '{zhipu_batch_id}' {current_zhipu_job_status}"
                        if status_result.get("errors", {}).get("data"):
                            error_message += f". Details: {status_result['errors']['data'][0].get('message')}"
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: ZhipuBatchID '{zhipu_batch_id}' is FAILED/CANCELLED. Calling update_callback.")
                        await update_callback(main_job_id, TaskStatus.FAILED, error=error_message, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for FAILED/CANCELLED ZhipuBatchID '{zhipu_batch_id}'. Breaking loop.")
                        break
                    else:
                        current_progress = 0
                        if current_zhipu_job_status == "validating": current_progress = 10
                        elif current_zhipu_job_status == "queued": current_progress = 20
                        elif current_zhipu_job_status == "running": current_progress = 50
                        elif current_zhipu_job_status == "finalizing": current_progress = 90
                        
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: ZhipuBatchID '{zhipu_batch_id}' is {current_zhipu_job_status}. Calling update_callback with PROCESSING.")
                        if attempts == 1:
                             await update_callback(main_job_id, TaskStatus.PROCESSING, progress=current_progress if current_progress > 0 else 5, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        elif current_progress > 0:
                             await update_callback(main_job_id, TaskStatus.PROCESSING, progress=current_progress, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for PROCESSING ZhipuBatchID '{zhipu_batch_id}'.")

                except httpx.HTTPStatusError as http_err:
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: HTTPStatusError for ZhipuBatchID {zhipu_batch_id}: {http_err.response.status_code} - {http_err.response.text}")
                    if 400 <= http_err.response.status_code < 500 and http_err.response.status_code not in [429]:
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: Calling update_callback for ZhipuBatchID '{zhipu_batch_id}' with FAILED (HTTPStatusError).")
                        await update_callback(main_job_id, TaskStatus.FAILED, error=f"Zhipu API client error: {http_err.response.status_code} - {http_err.response.text}", zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for FAILED (HTTPStatusError) ZhipuBatchID '{zhipu_batch_id}'. Breaking loop.")
                        break
                except Exception as e:
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: Unexpected EXCEPTION in polling loop for ZhipuBatchID {zhipu_batch_id}: {type(e).__name__} - {str(e)}")
                    traceback.print_exc()
                    pass
                
                if attempts < MAX_POLLING_ATTEMPTS:
                    # Placeholder for current_zhipu_job_status if not defined due to an early error in the try block
                    status_to_log = "unknown (error in previous step)"
                    if 'current_zhipu_job_status' in locals() or 'current_zhipu_job_status' in globals():
                        status_to_log = current_zhipu_job_status
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: ZhipuBatchID '{zhipu_batch_id}' status '{status_to_log}'. Sleeping for {POLLING_INTERVAL_SECONDS}s.")
                    await asyncio.sleep(POLLING_INTERVAL_SECONDS)
                else:
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: Max polling attempts reached for ZhipuBatchID {zhipu_batch_id}. Calling update_callback with FAILED (timeout).")
                    await update_callback(main_job_id, TaskStatus.FAILED, error=f"Polling timeout after {MAX_POLLING_ATTEMPTS} attempts for Zhipu Batch ID {zhipu_batch_id}.", zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                    print(f"[{datetime.now()}] ZP_POLL_DEBUG: update_callback called for FAILED (timeout) ZhipuBatchID '{zhipu_batch_id}'.")
            
            print(f"[{datetime.now()}] ZP_POLL_DEBUG: background_poll_status EXITED for ZhipuBatchID: {zhipu_batch_id}, Chunk: {chunk_id}. Attempts: {attempts}")

    except Exception as e_outer: # Catch any exception from the entire function body
        print(f"[{datetime.now()}] ZP_POLL_CRITICAL_ERROR: Unhandled exception in background_poll_status for ZhipuBatchID {zhipu_batch_id}, Chunk {chunk_id}: {type(e_outer).__name__} - {str(e_outer)}")
        traceback.print_exc()
        # Optionally, try to call the callback with a failure status if possible and if update_callback is safe to call
        if 'update_callback' in locals() and update_callback and main_job_id and zhipu_batch_id : # Check if essential args are available
            try:
                await update_callback(main_job_id, TaskStatus.FAILED, error=f"Critical unhandled error in poller: {str(e_outer)}", zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                print(f"[{datetime.now()}] ZP_POLL_CRITICAL_ERROR: Called update_callback with FAILED status due to unhandled exception.")
            except Exception as e_cb_critical:
                print(f"[{datetime.now()}] ZP_POLL_CRITICAL_ERROR: Exception while calling update_callback during critical error handling: {type(e_cb_critical).__name__} - {str(e_cb_critical)}")

async def download_and_process_results(
    client: httpx.AsyncClient,
    headers: Dict[str, str],
    output_file_id: str
) -> List[str]:
    """下载并处理结果文件"""
    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Starting download for output_file_id: {output_file_id}")
    try:
        results_response = await client.get(
            f"{ZHIPU_API_BASE_URL}/v4/files/{output_file_id}/content",
            headers=headers
        )
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: GET /files/{output_file_id}/content status: {results_response.status_code}")
        results_response.raise_for_status() # Will raise an exception for 4xx/5xx errors
        results_content = results_response.text
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Results content downloaded. Length: {len(results_content)} chars.")

        translated_texts_map = {}
        lines = results_content.strip().split('\n')
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Parsing {len(lines)} lines from results content.")

        for i, line in enumerate(lines):
            if not line:
                # print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Skipping empty line {i+1}.")
                continue
            try:
                # print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Parsing line {i+1}: {line[:100]}...") # Log only first 100 chars
                result_item = json.loads(line)
                custom_id = result_item.get("custom_id")
                
                # Adjusting path to the actual translation content based on observed batch API output
                # The actual response from the model is nested inside response.body
                raw_model_response_outer = result_item.get("response", {})
                model_response_body = raw_model_response_outer.get("body", {}) # Get the 'body' which contains the chat completion response

                if not isinstance(model_response_body, dict): # Ensure body is a dict
                    translated_texts_map[custom_id] = "[Invalid Response Body Format]"
                    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Invalid response body format (not a dict) for custom_id {custom_id} in line: {line[:100]}")
                    continue

                if model_response_body.get("error"):
                    error_msg = model_response_body['error'].get('message', 'Unknown error')
                    translated_texts_map[custom_id] = f"[Error: {error_msg}]"
                    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Error in result for custom_id {custom_id}: {error_msg}")
                elif "choices" in model_response_body and model_response_body["choices"]:
                    # Ensure choices is a list and has at least one element
                    if isinstance(model_response_body["choices"], list) and len(model_response_body["choices"]) > 0:
                        choice = model_response_body["choices"][0]
                        if isinstance(choice, dict) and "message" in choice and isinstance(choice["message"], dict):
                            translated_text = choice["message"].get("content", "").strip()
                            translated_texts_map[custom_id] = translated_text or "[Empty Translation]"
                            # print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Parsed custom_id {custom_id} successfully.")
                        else:
                            translated_texts_map[custom_id] = "[Malformed choice/message structure]"
                            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Malformed choice/message structure for custom_id {custom_id} in line: {line[:100]}")
                    else:
                        translated_texts_map[custom_id] = "[Empty or invalid choices list]"
                        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Empty or invalid choices list for custom_id {custom_id} in line: {line[:100]}")
                else:
                    translated_texts_map[custom_id] = "[No choices in response body]"
                    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: No choices found in response body for custom_id {custom_id} in line: {line[:100]}")
            except json.JSONDecodeError as je:
                print(f"[{datetime.now()}] DOWNLOAD_PROCESS: JSONDecodeError parsing line {i+1}: {line[:150]}. Error: {je}")
                # Add a placeholder for this custom_id if it can be inferred or is important
                # translated_texts_map[f"error_parsing_line_{i+1}"] = "[JSON Decode Error]"
            except Exception as e_line:
                print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Exception parsing line {i+1}: {line[:150]}. Error: {type(e_line).__name__} - {e_line}")
                # translated_texts_map[f"error_processing_line_{i+1}"] = "[Line Processing Error]"


        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Finished parsing lines. translated_texts_map contains {len(translated_texts_map)} items.")

        # 按顺序重建翻译结果列表
        # Assuming the number of original texts is somehow known or can be inferred for robust reordering.
        # For now, this relies on custom_id being request-1, request-2, ...
        # If texts were passed to this function, we could use len(texts)
        # Let's assume the map will have at most MAX_POLLING_ATTEMPTS entries if we don't know original length
        # A better way would be to pass the original number of texts or rely on a fixed number of custom_ids
        
        # For this reconstruction to be robust, we need to know how many 'request-N' were originally submitted.
        # Let's find the max N from the custom_ids we successfully parsed.
        max_n = 0
        if translated_texts_map:
            for cid in translated_texts_map.keys():
                if cid and cid.startswith("request-"):
                    try:
                        num = int(cid.split("-")[1])
                        if num > max_n:
                            max_n = num
                    except (ValueError, IndexError):
                        pass # Malformed custom_id, ignore for max_n calculation

        final_translations = []
        if max_n > 0: # If we found at least one valid request-N
            for i in range(max_n):
                custom_id_to_find = f"request-{i+1}"
                final_translations.append(translated_texts_map.get(custom_id_to_find, f"[Missing Translation for {custom_id_to_find}]"))
        else: # Fallback if no valid custom_ids or map is empty
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: translated_texts_map was empty or no valid custom_ids like 'request-N' found. Returning empty list or map values if any.")
            # As a simple fallback, just return the values we have, order might be wrong.
            # Or, if you expect all N items, fill with placeholders if original_texts_count was available.
            final_translations = list(translated_texts_map.values())


        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Reconstructed final_translations list with {len(final_translations)} items.")
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Function finished successfully.")
        return final_translations

    except httpx.HTTPStatusError as http_err:
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: HTTPStatusError during download: {http_err.response.status_code} - {http_err.response.text}")
        traceback.print_exc()
        # Propagate the error or return an empty list / specific error indicator
        raise # Or handle more gracefully, e.g., return an empty list and log
    except Exception as e:
        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Unexpected error: {type(e).__name__} - {str(e)}")
        traceback.print_exc()
        # Propagate the error or return an empty list / specific error indicator
        raise # Or handle more gracefully

async def translate_batch(
    texts: List[str],
    api_key: str,
    source_lang: str,
    target_lang: str,
    model: str = "glm-4",
    main_job_id: Optional[str] = None,
    update_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """
    提交批量翻译请求（单文件模式）并直接处理轮询逻辑。
    使用智谱AI的文件上传和批处理API。
    """
    print(f"[{datetime.now()}] ZP_AI: Starting translation batch (single file mode) for texts count: {len(texts)}")
    
    try:
        jsonl_lines = []
        for i, text in enumerate(texts, 1):
            current_custom_id = f"request_{i}" # Simplified custom_id
            
            messages = [
                {
                    "role": "system",
                    "content": f"你是一个专业的翻译助手。请将文本从{source_lang}准确翻译成{target_lang}，保持原文的格式和标签不变。"
                },
                {
                    "role": "user",
                    "content": f"请翻译以下文本：\n{text}"
                }
            ]
            
            # Each line in JSONL is a JSON object specifying the individual request
            request_line_data = {
                "custom_id": current_custom_id,
                "method": "POST",
                "url": "/v4/chat/completions",
                "body": {
                    "model": model,
                    "messages": messages,
                }
            }
            jsonl_lines.append(json.dumps(request_line_data, ensure_ascii=False))
        
        jsonl_content = "\n".join(jsonl_lines)
        print(f"[{datetime.now()}] ZP_AI DEBUG: Generated JSONL content (first 500 chars): {jsonl_content[:500]}")

        jwt_token = generate_zhipu_token(api_key)
        
        async with httpx.AsyncClient(timeout=120.0) as client: # Increased timeout for potentially larger files
            # 2. 上传JSONL文件
            print(f"[{datetime.now()}] ZP_AI: Uploading JSONL file...")
            upload_headers = {"Authorization": f"Bearer {jwt_token}"}
            
            file_content_bytes = jsonl_content.encode('utf-8')
            # For httpx, files should be structured correctly.
            # The 'file' part should be a tuple: (filename, file-like-object OR bytes, content_type)
            files_for_upload = {
                "file": ("batch_translate_requests.jsonl", file_content_bytes, "application/jsonl")
            }
            # Other form data like 'purpose' should go into the 'data' argument
            data_for_upload = {
                "purpose": "batch"
            }
            
            print(f"[{datetime.now()}] ZP_AI DEBUG: Uploading file with size: {len(file_content_bytes)} bytes, data: {data_for_upload}")
            
            upload_response = await client.post(
                f"{ZHIPU_API_BASE_URL}/v4/files",
                headers=upload_headers, # Only Auth header here
                files=files_for_upload, # File part
                data=data_for_upload    # Other form data like 'purpose'
            )
            
            print(f"[{datetime.now()}] ZP_AI DEBUG: Upload response status: {upload_response.status_code}")
            print(f"[{datetime.now()}] ZP_AI DEBUG: Upload response content: {upload_response.text}")
            
            if upload_response.status_code != 200:
                error_msg = f"Failed to upload JSONL file: {upload_response.text}"
                if update_callback:
                    await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
                return {"status": "error", "message": error_msg}

            try:
                file_data = upload_response.json()
            except json.JSONDecodeError as e:
                error_msg = f"Failed to parse upload response: {str(e)}, Response text: {upload_response.text}"
                if update_callback:
                    await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
                return {"status": "error", "message": error_msg}
            
            uploaded_file_id = file_data.get("id")
            
            if not uploaded_file_id:
                error_msg = f"No file ID (uploaded_file_id) in response: {file_data}"
                if update_callback:
                    await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
                return {"status": "error", "message": error_msg}
            
            print(f"[{datetime.now()}] ZP_AI: File uploaded successfully. Uploaded File ID: {uploaded_file_id}")
            
            # 3. 创建批处理任务
            print(f"[{datetime.now()}] ZP_AI: Creating batch task...")
            batch_creation_headers = {
                "Authorization": f"Bearer {jwt_token}",
                "Content-Type": "application/json"
            }
            
            # Payload for creating the batch job, referencing the uploaded file
            batch_creation_payload = {
                "input_file_id": uploaded_file_id, # Use the ID of the uploaded JSONL file
                "endpoint": "/v4/chat/completions", # Specify the endpoint for requests in the file
                "completion_window": "24h", # Optional: How long to wait for completion
                "metadata": { 
                    "job_id": main_job_id or "unknown_job"
                }
            }
            print(f"[{datetime.now()}] ZP_AI DEBUG: Batch creation payload: {json.dumps(batch_creation_payload, ensure_ascii=False)}")

            batch_response = await client.post(
                f"{ZHIPU_API_BASE_URL}/v4/batches",
                headers=batch_creation_headers,
                json=batch_creation_payload
            )
            
            print(f"[{datetime.now()}] ZP_AI DEBUG: Batch creation response status: {batch_response.status_code}")
            print(f"[{datetime.now()}] ZP_AI DEBUG: Batch creation response content: {batch_response.text}")

            if batch_response.status_code != 200: # Zhipu usually returns 200 for successful batch submission
                error_msg = f"Failed to create batch task: {batch_response.text}"
                if update_callback:
                    await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
                return {"status": "error", "message": error_msg}
            
            batch_data = batch_response.json()
            batch_id = batch_data.get("id")
            
            if not batch_id:
                error_msg = "No batch ID (Zhipu Batch Job ID) received from Zhipu AI"
                if update_callback:
                    await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
                return {"status": "error", "message": error_msg}
            
            print(f"[{datetime.now()}] ZP_AI: Batch task created successfully. Zhipu Batch Job ID: {batch_id}")
            
            # 4. 轮询任务状态 (Polling logic remains largely the same, using polling_headers)
            polling_headers = { # Headers for polling and result download
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/json"
            }
            attempts = 0
            # ... (rest of the polling and result processing logic) ...
            # Ensure to use polling_headers for client.get calls in the loop and for result download
            # Make sure the `download_and_process_results` function is called correctly with client and polling_headers
            # ...
            while attempts < MAX_POLLING_ATTEMPTS:
                try:
                    # Token refresh logic might be needed if polling is very long, simplified for now
                    # if attempts > 0 and (attempts * POLLING_INTERVAL_SECONDS) > (TOKEN_EXPIRATION_SECONDS - 60):
                    #     print(f"[{datetime.now()}] ZP_AI: Refreshing token for polling batch {batch_id}")
                    #     jwt_token = generate_zhipu_token(api_key)
                    #     polling_headers["Authorization"] = f"Bearer {jwt_token}"

                    status_response = await client.get(
                        f"{ZHIPU_API_BASE_URL}/v4/batches/{batch_id}", # Use the Zhipu Batch Job ID
                        headers=polling_headers
                    )
                    
                    # ... (status check and callback logic as before) ...
                    # ... (on "completed", call download_and_process_results with client, polling_headers, and output_file_id)
                    # Example for completion part:
                    if status_response.status_code != 200:
                        print(f"[{datetime.now()}] ZP_AI WARNING: Status check failed for batch {batch_id}: {status_response.text}")
                        await asyncio.sleep(POLLING_INTERVAL_SECONDS)
                        attempts += 1
                        continue
                    
                    status_data = status_response.json()
                    current_zhipu_status = status_data.get("status", "unknown")
                    print(f"[{datetime.now()}] ZP_AI INFO: Batch {batch_id} status: {current_zhipu_status}, attempt {attempts+1}/{MAX_POLLING_ATTEMPTS}")

                    # Callback with current status
                    if update_callback:
                        # Determine app_status based on current_zhipu_status
                        app_status_for_callback = TaskStatus.PROCESSING 
                        if current_zhipu_status == "completed": app_status_for_callback = TaskStatus.COMPLETED
                        elif current_zhipu_status in ["failed", "cancelled"]: app_status_for_callback = TaskStatus.FAILED
                        
                        # Simplified progress, Zhipu Batch API provides total/completed/failed counts
                        progress_percentage = 0
                        if status_data.get("request_counts"):
                            total_reqs = status_data["request_counts"].get("total", 0)
                            completed_reqs = status_data["request_counts"].get("completed", 0)
                            if total_reqs > 0:
                                progress_percentage = int((completed_reqs / total_reqs) * 100)
                        
                        if app_status_for_callback != TaskStatus.COMPLETED: # Only update progress if not yet final
                             await update_callback(
                                main_job_id,
                                app_status_for_callback,
                                zhipu_batch_id=batch_id, 
                                progress=progress_percentage
                            )

                    if current_zhipu_status == "completed":
                        output_file_id = status_data.get("output_file_id") # This is the ID of the file containing results
                        error_file_id = status_data.get("error_file_id") # This is the ID of the file containing errors

                        if error_file_id:
                             print(f"[{datetime.now()}] ZP_AI INFO: Batch {batch_id} completed with an error file ID: {error_file_id}. Check its content.")
                             # Optionally download and log error file content here

                        if not output_file_id:
                            error_msg = f"Batch job {batch_id} completed but no output_file_id found."
                            print(f"[{datetime.now()}] ZP_AI ERROR: {error_msg}")
                            if update_callback:
                                await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=batch_id)
                            return {"status": "error", "message": error_msg, "zhipu_batch_id": batch_id}

                        print(f"[{datetime.now()}] ZP_AI: Batch {batch_id} completed. Output File ID: {output_file_id}. Fetching results...")
                        
                        translations = await download_and_process_results(client, polling_headers, output_file_id)
                        
                        print(f"[{datetime.now()}] ZP_AI: Translations processed for batch {batch_id}. Count: {len(translations)}")
                        if update_callback:
                            await update_callback(
                                main_job_id, 
                                TaskStatus.COMPLETED, 
                                result=translations, 
                                zhipu_batch_id=batch_id, 
                                progress=100
                            )
                        return {"status": "success", "translations": translations, "zhipu_batch_id": batch_id}
                    
                    elif current_zhipu_status in ["failed", "cancelled"]:
                        error_detail = status_data.get("errors", {}).get("data", [{}])[0].get("message", "No specific error message from Zhipu.")
                        error_msg = f"Batch job {batch_id} {current_zhipu_status}: {error_detail}"
                        print(f"[{datetime.now()}] ZP_AI ERROR: {error_msg}")
                        if update_callback:
                            await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=batch_id)
                        return {"status": "error", "message": error_msg, "zhipu_batch_id": batch_id}
                    
                    await asyncio.sleep(POLLING_INTERVAL_SECONDS)
                    attempts += 1
                
                except httpx.HTTPStatusError as http_err_poll:
                    print(f"[{datetime.now()}] ZP_AI ERROR: HTTPStatusError during polling batch {batch_id}: {http_err_poll.response.status_code} - {http_err_poll.response.text}")
                    # If it's a client error (4xx) that's not a rate limit, it might be unrecoverable for this batch
                    if 400 <= http_err_poll.response.status_code < 500 and http_err_poll.response.status_code != 429:
                        if update_callback:
                            await update_callback(main_job_id, TaskStatus.FAILED, error=f"Polling failed: {http_err_poll.response.text}", zhipu_batch_id=batch_id)
                        return {"status": "error", "message": f"Polling failed for batch {batch_id}", "zhipu_batch_id": batch_id}
                    # For 5xx or 429, just sleep and retry
                    await asyncio.sleep(POLLING_INTERVAL_SECONDS) # Sleep even on HTTP error before retrying poll
                    attempts +=1 # Still count as an attempt

                except Exception as e_poll:
                    print(f"[{datetime.now()}] ZP_AI ERROR during polling batch {batch_id}: {type(e_poll).__name__} - {str(e_poll)}")
                    traceback.print_exc()
                    # Decide if this is a fatal error for the polling loop or if we should continue polling after a delay
                    # For now, let's try to continue polling after a delay
                    await asyncio.sleep(POLLING_INTERVAL_SECONDS)
                    attempts += 1 # Count as an attempt
            
            # Polling timeout
            error_msg = f"Polling timeout after {MAX_POLLING_ATTEMPTS} attempts for Zhipu Batch Job ID: {batch_id}"
            print(f"[{datetime.now()}] ZP_AI ERROR: {error_msg}")
            if update_callback:
                await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=batch_id)
            return {"status": "error", "message": error_msg, "zhipu_batch_id": batch_id}
    
    except Exception as e_outer:
        error_msg = f"Unexpected outer error in translate_batch: {type(e_outer).__name__} - {str(e_outer)}"
        print(f"[{datetime.now()}] ZP_AI CRITICAL ERROR: {error_msg}")
        traceback.print_exc()
        if update_callback:
            await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg)
        return {"status": "error", "message": error_msg}

# Example usage (for testing this service directly if needed):
# async def main_test():
#     sample_texts = ["Hello, world!", "How are you today?", "This is a test."]
#     api_key = "YOUR_ACTUAL_ZHIPU_API_KEY" # Replace with your key for testing
#     source_lang = "en"
#     target_lang = "zh"
#     try:
#         translations = await translate_batch(sample_texts, api_key, source_lang, target_lang)
#         for original, translated in zip(sample_texts, translations):
#             print(f"Original: {original} -> Translated: {translated}")
#     except HTTPException as e:
#         print(f"HTTP Exception: {e.status_code} - {e.detail}")
#     except Exception as e:
#         print(f"General Exception: {e}")

# if __name__ == "__main__":
#     asyncio.run(main_test()) 