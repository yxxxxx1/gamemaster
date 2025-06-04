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

# Import settings
from app.core.config import settings

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
DEFAULT_ZHIPU_MODEL = "GLM-4-Plus" # Example, check documentation for batch API compatible models

# Placeholder for original newline characters
ORIGINAL_NEWLINE_PLACEHOLDER = "___ORIGINAL_NL___"

# New constant for chunking texts
# TEXTS_PER_CHUNK = 10 # Removed, will use settings.ZHIPU_TEXTS_PER_CHUNK

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
    print(f"[{datetime.now()}] ZP_POLL_DEBUG: *** background_poll_status TASK STARTING for ZhipuBatchID: {zhipu_batch_id}, MainJob: {main_job_id}, Chunk: {chunk_id} ***")
    try:
        headers = {
            "Authorization": f"Bearer {generate_zhipu_token(api_key)}",
            "Accept": "application/json"
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            attempts = 0
            while attempts < MAX_POLLING_ATTEMPTS:
                attempts += 1
                print(f"[{datetime.now()}] ZP_POLL: Attempt {attempts}/{MAX_POLLING_ATTEMPTS} for ZhipuBatchID: {zhipu_batch_id}")
                try:
                    if attempts > 1 and (time.time() * 1000) % (TOKEN_EXPIRATION_SECONDS * 1000 / 2) < (POLLING_INTERVAL_SECONDS * 1000 * 2):
                        print(f"[{datetime.now()}] ZP_POLL: Refreshing token for ZhipuBatchID: {zhipu_batch_id}")
                        headers["Authorization"] = f"Bearer {generate_zhipu_token(api_key)}"
                    
                    status_response = await client.get(f"{ZHIPU_API_BASE_URL}/v4/batches/{zhipu_batch_id}", headers=headers)
                    status_response.raise_for_status()
                    status_result = status_response.json()
                    current_zhipu_job_status = status_result.get("status")
                    print(f"[{datetime.now()}] ZP_POLL: ZhipuBatchID '{zhipu_batch_id}' status: '{current_zhipu_job_status}'")

                    if current_zhipu_job_status == "completed":
                        output_file_id = status_result.get("output_file_id")
                        if not output_file_id:
                            error_msg = "Zhipu batch job completed but no output_file_id found"
                            await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                            break 
                        await update_callback(main_job_id, TaskStatus.COMPLETED, progress=100, zhipu_output_file_id=output_file_id, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        break 
                    elif current_zhipu_job_status in ["failed", "cancelled"]:
                        error_message = f"Zhipu batch job '{zhipu_batch_id}' {current_zhipu_job_status}. Details: {status_result.get('errors')}"
                        await update_callback(main_job_id, TaskStatus.FAILED, error=error_message, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        break 
                    else: 
                        progress = 0
                        if status_result.get("request_counts"):
                            total_reqs = status_result["request_counts"].get("total", 1) 
                            completed_reqs = status_result["request_counts"].get("completed", 0)
                            if total_reqs > 0:
                                progress = int((completed_reqs / total_reqs) * 100)
                        await update_callback(main_job_id, TaskStatus.PROCESSING, progress=progress, zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                
                except httpx.HTTPStatusError as http_err:
                    print(f"[{datetime.now()}] ZP_POLL_ERROR: HTTPStatusError for ZhipuBatchID {zhipu_batch_id}: {http_err.response.status_code} - {http_err.response.text}")
                    if 400 <= http_err.response.status_code < 500 and http_err.response.status_code not in [429]: 
                        await update_callback(main_job_id, TaskStatus.FAILED, error=str(http_err), zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
                        break 
                except Exception as e_poll_loop:
                    print(f"[{datetime.now()}] ZP_POLL_ERROR: Unexpected error in polling loop for ZhipuBatchID {zhipu_batch_id}: {type(e_poll_loop).__name__} - {e_poll_loop}")
                    traceback.print_exc()
                
                await asyncio.sleep(POLLING_INTERVAL_SECONDS)
            else: 
                await update_callback(main_job_id, TaskStatus.FAILED, error=f"Polling timeout for ZhipuBatchID {zhipu_batch_id}", zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
    except Exception as e_outer_poll:
        print(f"[{datetime.now()}] ZP_POLL_CRITICAL: Unhandled exception in background_poll_status for ZhipuBatchID {zhipu_batch_id}: {type(e_outer_poll).__name__} - {e_outer_poll}")
        traceback.print_exc()
        try:
            await update_callback(main_job_id, TaskStatus.FAILED, error=f"Critical poller error: {e_outer_poll}", zhipu_batch_id=zhipu_batch_id, chunk_id=chunk_id)
        except Exception as e_cb_critical:
            print(f"[{datetime.now()}] ZP_POLL_CRITICAL: Failed to call update_callback during critical error: {e_cb_critical}")

async def download_and_process_results(
    api_key: str, 
    output_file_id: str,
    chunk_details_map: Dict[str, Dict[str, Any]] 
) -> List[str]:
    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Starting download for output_file_id: {output_file_id}")
    headers = {
        "Authorization": f"Bearer {generate_zhipu_token(api_key)}",
    }
    async with httpx.AsyncClient(timeout=60.0) as client: 
        try:
            results_response = await client.get(
                f"{ZHIPU_API_BASE_URL}/v4/files/{output_file_id}/content", 
                headers=headers
            )
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: GET /files/{output_file_id}/content status: {results_response.status_code}")
            results_response.raise_for_status()
            results_content = results_response.text
            translated_texts_map: Dict[str, List[str]] = {}
            lines = results_content.strip().split('\n')
            for i, line in enumerate(lines):
                if not line:
                    continue
                try:
                    result_item = json.loads(line)
                    custom_id = result_item.get("custom_id")
                    current_chunk_translations: List[str] = []
                    chunk_detail = chunk_details_map.get(custom_id, {"count": 0, "original_lines": []})
                    num_original_lines_in_chunk = chunk_detail.get("count", 0)
                    original_lines_for_this_chunk = chunk_detail.get("original_lines", [])
                    raw_model_response_body = result_item.get("response", {}).get("body", {})
                    translated_text_chunk_from_model = "[Could not extract from model response]"
                    if not isinstance(raw_model_response_body, dict):
                        for _ in range(num_original_lines_in_chunk): current_chunk_translations.append("[Invalid Response Body Format]")
                    elif raw_model_response_body.get("error"):
                        error_msg = raw_model_response_body['error'].get('message', 'Unknown error')
                        for _ in range(num_original_lines_in_chunk): current_chunk_translations.append(f"[Error: {error_msg}]")
                    elif "choices" in raw_model_response_body and raw_model_response_body["choices"]:
                        if isinstance(raw_model_response_body["choices"], list) and len(raw_model_response_body["choices"]) > 0:
                            choice = raw_model_response_body["choices"][0]
                            if isinstance(choice, dict) and "message" in choice and isinstance(choice["message"], dict):
                                translated_text_chunk_from_model = choice["message"].get("content", "").strip()
                                if not translated_text_chunk_from_model:
                                    for _ in range(num_original_lines_in_chunk): current_chunk_translations.append("[Empty Translation From Model]")
                                else:
                                    split_translations = translated_text_chunk_from_model.split('\n')
                                    if len(split_translations) < num_original_lines_in_chunk:
                                        print(f"-" * 80)
                                        print(f"[{datetime.now()}] DOWNLOAD_PROCESS: WARNING - Missing lines for custom_id: {custom_id}")
                                        print(f"  Expected lines: {num_original_lines_in_chunk}, Got lines: {len(split_translations)}")
                                        print(f"  Original lines in chunk ({custom_id}):")
                                        for idx, ol in enumerate(original_lines_for_this_chunk):
                                            print(f"    {idx+1}: {ol[:1000]}{'...' if len(ol) > 1000 else ''}")
                                        raw_model_output_str = translated_text_chunk_from_model
                                        max_raw_chars = 200 
                                        if len(raw_model_output_str) > max_raw_chars * 2 + 20: 
                                            print(f"  Raw model output for chunk ({custom_id}) (first/last {max_raw_chars} chars of {len(raw_model_output_str)} total):\n{raw_model_output_str[:max_raw_chars]} ...\n... {raw_model_output_str[-max_raw_chars:]}")
                                        else:
                                            print(f"  Raw model output for chunk ({custom_id}):\n{raw_model_output_str}")
                                        split_list_log = split_translations 
                                        max_elements_to_log = 3 
                                        max_chars_per_element = 100 
                                        print(f"  Split translations for chunk ({custom_id}) (length: {len(split_list_log)}):")
                                        if len(split_list_log) > max_elements_to_log * 2 + 1:
                                            for i_item in range(max_elements_to_log):
                                                item_str = str(split_list_log[i_item])
                                                print(f"    Item {i_item}: {item_str[:max_chars_per_element]}{'...' if len(item_str) > max_chars_per_element else ''}")
                                            print(f"    ... ({len(split_list_log) - 2 * max_elements_to_log} more items) ...")
                                            for i_item in range(len(split_list_log) - max_elements_to_log, len(split_list_log)):
                                                item_str = str(split_list_log[i_item])
                                                print(f"    Item {i_item}: {item_str[:max_chars_per_element]}{'...' if len(item_str) > max_chars_per_element else ''}")
                                        else:
                                            for i_item, item_log in enumerate(split_list_log):
                                                item_str = str(item_log)
                                                print(f"    Item {i_item}: {item_str[:max_chars_per_element]}{'...' if len(item_str) > max_chars_per_element else ''}")
                                        print(f"-" * 80)
                                        current_chunk_translations.extend(split_translations)
                                        for _ in range(num_original_lines_in_chunk - len(split_translations)):
                                            current_chunk_translations.append("[Missing Line Translation]")
                                    elif len(split_translations) > num_original_lines_in_chunk and num_original_lines_in_chunk > 0:
                                        current_chunk_translations.extend(split_translations[:num_original_lines_in_chunk])
                                    else: 
                                        current_chunk_translations.extend(split_translations)
                            else:
                                for _ in range(num_original_lines_in_chunk): current_chunk_translations.append("[Malformed choice/message structure]")
                        else:
                            for _ in range(num_original_lines_in_chunk): current_chunk_translations.append("[Empty or invalid choices list]")
                    else:
                        for _ in range(num_original_lines_in_chunk): current_chunk_translations.append("[No choices in response body]")
                    restored_chunk_translations = [tl.replace(ORIGINAL_NEWLINE_PLACEHOLDER, "\n") for tl in current_chunk_translations]
                    translated_texts_map[custom_id] = restored_chunk_translations
                except json.JSONDecodeError as je:
                    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: JSONDecodeError parsing line {i+1}: '{line[:100]}...'. Error: {je}")
                except Exception as e_line:
                    print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Exception parsing line {i+1}: '{line[:100]}...'. Error: {type(e_line).__name__} - {e_line}")
            final_flat_translations: List[str] = []
            max_chunk_n = 0
            if translated_texts_map:
                custom_ids_found = sorted(
                    [cid for cid in translated_texts_map.keys() if cid and cid.startswith("request-")],
                    key=lambda x: int(x.split('-')[1]) if len(x.split('-')) > 1 and x.split('-')[1].isdigit() else float('inf')
                )
                max_chunk_n = int(custom_ids_found[-1].split('-')[1]) if custom_ids_found and custom_ids_found[-1].split('-')[1].isdigit() else 0
            expected_custom_ids_in_order = [f"request-{i+1}" for i in range(max_chunk_n)]
            for current_chunk_custom_id in expected_custom_ids_in_order:
                translations_for_this_chunk = translated_texts_map.get(current_chunk_custom_id)
                if translations_for_this_chunk:
                    final_flat_translations.extend(translations_for_this_chunk)
                else:
                    num_lines_in_missing_chunk_detail = chunk_details_map.get(current_chunk_custom_id, {"count": 0})
                    num_lines_in_missing_chunk = num_lines_in_missing_chunk_detail.get("count", 0)
                    for _ in range(num_lines_in_missing_chunk):
                        final_flat_translations.append(f"[Missing Translation for entire chunk {current_chunk_custom_id}]")
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Reconstructed final_flat_translations list with {len(final_flat_translations)} items.")
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Function finished successfully.")
            return final_flat_translations
        except httpx.HTTPStatusError as http_err:
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: HTTPStatusError during download: {http_err.response.status_code} - {http_err.response.text}")
            traceback.print_exc()
            raise 
        except Exception as e:
            print(f"[{datetime.now()}] DOWNLOAD_PROCESS: Unexpected error: {type(e).__name__} - {str(e)}")
            traceback.print_exc()
            raise 

async def translate_batch(
    texts: List[str],
    api_key: str,
    source_lang: str,
    target_lang: str,
    model: str = "glm-4",
    main_job_id: Optional[str] = None,
    update_callback: Optional[Callable] = None,
    texts_per_chunk: Optional[int] = None
) -> Dict[str, Any]: 
    print(f"[{datetime.now()}] ZP_AI_SERVICE: translate_batch initiated for {len(texts)} texts. MainJob: {main_job_id}")
    current_job_chunk_details_map: Dict[str, Dict[str, Any]] = {}
    try:
        # 使用传入的 texts_per_chunk 参数，如果未提供则使用默认值 10
        chunk_size = texts_per_chunk if texts_per_chunk is not None else 10
        chunks = [texts[i:i + chunk_size] for i in range(0, len(texts), chunk_size)]
        
        # 为每个块创建请求
        jsonl_lines = []
        for chunk_idx, chunk_texts in enumerate(chunks, 1):
            current_custom_id = f"request-{chunk_idx}"
            current_job_chunk_details_map[current_custom_id] = {
                "original_lines": chunk_texts,
                "count": len(chunk_texts)
            }
            
            processed_text_chunk_for_model = [line.replace("\n", ORIGINAL_NEWLINE_PLACEHOLDER) for line in chunk_texts]
            user_content_for_chunk = "\n".join(processed_text_chunk_for_model)
            
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"你是一个专业的游戏本地化翻译专家。"
                        f"请将用户提供的游戏文本从{source_lang}准确翻译成{target_lang}。"
                        f"用户输入的多行文本已使用换行符 '\n' 作为不同文本行之间的分隔。"
                        f"原文中固有的实际换行符已被特殊占位符 '{ORIGINAL_NEWLINE_PLACEHOLDER}' 替代。在翻译时，请将此占位符理解为原文中的实际换行，并在译文的对应位置将其准确地翻译和还原为实际的换行符或保留此占位符。"
                        f"至关重要：您的输出必须包含与输入完全相同数量的文本行。输入中的每一行（由 '\n' 分隔）必须在您的输出中有一个对应的翻译行（同样由 '\n' 分隔）。如果您翻译的某一行结果为空，您必须仍然输出一个空行（即，如果原文某行为空，译文也应为空行；如果原文某行有内容但译文逻辑上为空，也应输出空行）。总行数不得有任何偏差，必须为{len(chunk_texts)}行。"
                        f"务必完整保留原文中的所有其他特殊符号、标签和格式（例如游戏中的变量占位符 {{{{player_name}}}} 或格式标签 <color=red>text</color>）。"
                        f"除非 '{ORIGINAL_NEWLINE_PLACEHOLDER}' 指示，否则不要在单行译文内部随意添加或删除 '\n' 换行符。"
                        f"请确保翻译符合游戏风格，保持角色对话的自然流畅，并适应目标语言的文化习惯。"
                    )
                },
                {
                    "role": "user",
                    "content": user_content_for_chunk 
                }
            ]
            
            request_line_data = {
                "custom_id": current_custom_id,
                "method": "POST",
                "url": "/v4/chat/completions", 
                "body": {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.1 
                }
            }
            jsonl_lines.append(json.dumps(request_line_data, ensure_ascii=False))
        
        # 将所有请求合并成一个 JSONL 文件
        jsonl_content = "\n".join(jsonl_lines)
        
        jwt_token = generate_zhipu_token(api_key)
        async with httpx.AsyncClient(timeout=120.0) as client: 
            upload_headers = {"Authorization": f"Bearer {jwt_token}"}
            files_for_upload = {"file": ("batch_requests.jsonl", jsonl_content.encode('utf-8'), "application/jsonl")}
            data_for_upload = {"purpose": "batch"}
            upload_response = await client.post(f"{ZHIPU_API_BASE_URL}/v4/files", headers=upload_headers, files=files_for_upload, data=data_for_upload)
            if upload_response.status_code != 200:
                error_msg = f"Zhipu file upload failed: {upload_response.status_code} - {upload_response.text}"
                if update_callback: await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=None)
                return {"status": "error", "message": error_msg}
            
            uploaded_file_id = upload_response.json().get("id")
            if not uploaded_file_id:
                error_msg = f"Zhipu file upload succeeded but no file ID returned. Response: {upload_response.text}"
                if update_callback: await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=None)
                return {"status": "error", "message": error_msg}
            
            print(f"[{datetime.now()}] ZP_AI_SERVICE: File uploaded to Zhipu. File ID: {uploaded_file_id}")
            batch_creation_headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}
            batch_payload = {
                "input_file_id": uploaded_file_id, 
                "endpoint": "/v4/chat/completions", 
                "completion_window": "24h", 
                "metadata": {"job_id": main_job_id or "unknown_job"}
            }
            batch_response = await client.post(f"{ZHIPU_API_BASE_URL}/v4/batches", headers=batch_creation_headers, json=batch_payload)
            if batch_response.status_code != 200:
                error_msg = f"Zhipu batch task creation failed: {batch_response.status_code} - {batch_response.text}"
                if update_callback: await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=f"upload_id_{uploaded_file_id}")
                return {"status": "error", "message": error_msg}
            
            batch_id = batch_response.json().get("id")
            if not batch_id:
                error_msg = f"Zhipu batch task creation succeeded but no batch ID returned. Response: {batch_response.text}"
                if update_callback: await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=f"upload_id_{uploaded_file_id}_no_batch_id")
                return {"status": "error", "message": error_msg}
            
            print(f"[{datetime.now()}] ZP_AI_SERVICE: Batch task created with Zhipu. Batch ID: {batch_id}. MainJob: {main_job_id}")
            if update_callback:
                await update_callback(main_job_id, TaskStatus.PROCESSING, progress=1, zhipu_batch_id=batch_id)
            
            return {
                "status": "success",
                "batch_job_id": batch_id,
                "placeholders_map": {},  # 如果需要标签保护，这里需要添加
                "chunk_details_map": current_job_chunk_details_map
            }
    except Exception as e_outer:
        error_msg = f"Unexpected outer error in translate_batch: {type(e_outer).__name__} - {str(e_outer)}"
        print(f"[{datetime.now()}] ZP_AI_SERVICE CRITICAL: {error_msg}. MainJob: {main_job_id}")
        traceback.print_exc()
        if update_callback: 
            _zhipu_batch_id_for_error = locals().get("batch_id", "translate_batch_outer_error")
            await update_callback(main_job_id, TaskStatus.FAILED, error=error_msg, zhipu_batch_id=_zhipu_batch_id_for_error)
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