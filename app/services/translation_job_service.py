import datetime
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
import asyncio
import traceback

from fastapi import HTTPException, status, BackgroundTasks, UploadFile

from app.models import TranslationJobRequest, TranslationJobCreateResponse, TranslationJobStatus as AppTranslationJobStatus
from app.services import file_service
from app.services import zhipu_ai_service
from app.services.zhipu_ai_service import TaskStatus as ZhipuTaskStatus
from app.core.config import settings

# Global job store for this service
JOB_STORE: Dict[str, Dict[str, Any]] = {}

# TODO: Make these configurable if necessary, potentially via settings
ZHIPU_API_BASE_URL = "https://open.bigmodel.cn/api/paas"
# Token expiration time in seconds (e.g., 1 hour)
TOKEN_EXPIRATION_SECONDS = 3600
# Polling interval in seconds - increased for longer running jobs
POLLING_INTERVAL_SECONDS = 10  # Changed from 5 to 10 seconds to reduce API calls
# Max polling attempts - increased to cover ~20 minutes
MAX_POLLING_ATTEMPTS = 120     # 120 attempts × 10 seconds = 1200 seconds = 20 minutes

# Standard model if not specified by user or if batch API has a default
DEFAULT_ZHIPU_MODEL = "glm-4"

async def _update_job_store_callback(
    job_id: str, 
    status_from_zhipu: ZhipuTaskStatus, 
    **kwargs: Any
) -> None:
    """Callback function to be invoked by zhipu_ai_service to update JOB_STORE."""
    print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Received update for job_id '{job_id}'. Status: {status_from_zhipu}. Kwargs: {kwargs}")
    if job_id not in JOB_STORE:
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: ERROR - Job ID '{job_id}' not found in JOB_STORE. Ignoring callback.")
        return

    job_entry = JOB_STORE[job_id]
    job_entry["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

    # Map ZhipuTaskStatus to AppTranslationJobStatus if needed, or ensure consistency
    # For now, let's assume direct usage or a mapping step
    job_entry["status"] = status_from_zhipu.value # Store the string value of the enum

    if "progress" in kwargs:
        job_entry["progress_percentage"] = kwargs["progress"]
    
    if "error" in kwargs:
        job_entry["error_message"] = kwargs["error"]
        job_entry["status"] = AppTranslationJobStatus.FAILED.value # Ensure our app status reflects failure

    if "zhipu_batch_id" in kwargs: # Store the actual zhipu batch id for reference
        job_entry["zhipu_batch_id_actual"] = kwargs["zhipu_batch_id"]

    if status_from_zhipu == ZhipuTaskStatus.COMPLETED:
        translations = kwargs.get("result")
        if translations:
            job_entry["translations"] = translations # Store raw translations
            job_entry["translated_texts_count"] = len(translations)
            job_entry["status"] = AppTranslationJobStatus.COMPLETED.value # Final app status
            job_entry["progress_percentage"] = 100
            
            print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Job '{job_id}' completed. Translations count: {len(translations)}.")
            
            # Attempt to write results to Excel
            try:
                request_details = job_entry.get("request_details", {})
                original_file_id = request_details.get("file_id")
                original_file_path_str = job_entry.get("file_path_processed") # Path of the uploaded source file
                
                if original_file_path_str and original_file_id: # Ensure we have the path
                    original_file_path = Path(original_file_path_str)
                    original_text_col = request_details.get("original_text_column", "original_text") # Default if not in request
                    translated_text_col_name = request_details.get("translated_text_column_name", "translated_text")
                    project_name = request_details.get("project_name")
                    
                    print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Attempting to write translated Excel for job '{job_id}'.")
                    # This function needs to be implemented in file_service or here
                    # It should take the original file, add/update a column with translations, and save as a new file.
                    output_file_path = await file_service.write_excel_with_translations(
                        original_file_path=original_file_path,
                        translations=translations,
                        original_text_column_name=original_text_col,
                        new_translated_column_name=translated_text_col_name,
                        project_name=project_name, # Optional, for naming output file
                        base_filename_suffix="_translated"
                    )
                    job_entry["output_file_path"] = str(output_file_path)
                    print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Translated Excel saved for job '{job_id}' at: {output_file_path}")
                else:
                    print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: WARNING - Could not write translated Excel for job '{job_id}'. Missing original_file_path or file_id.")
                    existing_error_message_path = job_entry.get("error_message") or ""
                    new_error_part_path = "Results obtained, but failed to write output Excel file due to missing path info."
                    if existing_error_message_path:
                        job_entry["error_message"] = (existing_error_message_path + "; " + new_error_part_path).strip()
                    else:
                        job_entry["error_message"] = new_error_part_path.strip()
                    # Optionally, do not mark as fully FAILED if translations are available but file write failed.
                    # job_entry["status"] = AppTranslationJobStatus.COMPLETED_WITH_ISSUES.value # If you add such a status

            except Exception as e_write:
                print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: ERROR writing translated Excel for job '{job_id}': {type(e_write).__name__} - {e_write}")
                traceback.print_exc()
                existing_error_message = job_entry.get("error_message") or ""
                new_error_write = f"Results obtained, but failed to write output Excel file: {e_write}"
                if existing_error_message:
                    job_entry["error_message"] = (existing_error_message + "; " + new_error_write).strip()
                else:
                    job_entry["error_message"] = new_error_write.strip()
                # Mark as FAILED or a special status if file writing is critical
                job_entry["status"] = AppTranslationJobStatus.FAILED.value # Or COMPLETED_WITH_ERRORS
        else:
            print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Job '{job_id}' reported as COMPLETED by Zhipu, but no results found in callback kwargs.")
            job_entry["status"] = AppTranslationJobStatus.FAILED.value
            job_entry["error_message"] = "Zhipu reported task completion, but translation results were missing."
            job_entry["progress_percentage"] = 100 # It did complete on Zhipu side

    elif status_from_zhipu == ZhipuTaskStatus.FAILED:
        job_entry["status"] = AppTranslationJobStatus.FAILED.value
        if "error" not in job_entry or not job_entry["error"] : # If zhipu_service didn't already set it
             job_entry["error_message"] = kwargs.get("error", "Zhipu AI task failed without specific details.")
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: Job '{job_id}' FAILED. Error: {job_entry['error_message']}")
    
    print(f"[{datetime.datetime.now(datetime.timezone.utc)}] TJS_CALLBACK: JOB_STORE updated for '{job_id}': Status='{job_entry['status']}', Progress={job_entry.get('progress_percentage')}")

async def create_and_process_translation_job(
    job_request: TranslationJobRequest,
    background_tasks: BackgroundTasks
) -> TranslationJobCreateResponse:
    """创建并处理翻译任务"""
    job_id = str(uuid.uuid4())
    current_time = datetime.datetime.now(datetime.timezone.utc)

    # Ensure ZHIPU_API_KEY is available from settings
    if not settings.ZHIPU_API_KEY:
        print("[translation_job_service] CRITICAL ERROR: ZHIPU_API_KEY is not configured.")
        # This should ideally be caught by the router/endpoint layer, but good to have a check.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: Zhipu AI API Key is not set."
        )

    # Initialize JOB_STORE entry
    initial_job_data = {
        "job_id": job_id,
        "status": AppTranslationJobStatus.PENDING.value,
        "request_details": job_request.model_dump(), # Original request details
        "file_path_processed": None, # Path to the originally uploaded file after saving
        "output_file_path": None,    # Path to the new Excel file with translations
        "original_texts_count": 0,
        "translated_texts_count": 0,
        "progress_percentage": 0,
        "created_at": current_time,
        "updated_at": current_time,
        "zhipu_batch_id_actual": None, # To store the actual batch ID from Zhipu
        "error_message": None,
        "translations": None, # Store the list of translated strings
        "message": "Job initiated."
    }
    JOB_STORE[job_id] = initial_job_data

    try:
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Starting job: {job_id} for file_id: {job_request.file_id}, original_filename: {job_request.original_filename}")
        
        # 1. Get file path and read Excel content
        file_path = await file_service.get_file_path(job_request.file_id)
        if not file_path or not await asyncio.to_thread(Path(file_path).exists):
            JOB_STORE[job_id]["status"] = AppTranslationJobStatus.FAILED.value
            JOB_STORE[job_id]["error_message"] = f"Uploaded file not found for file_id: {job_request.file_id}"
            JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=JOB_STORE[job_id]["error_message"])
        
        JOB_STORE[job_id]["file_path_processed"] = str(file_path)
        JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Reading Excel for job: {job_id} from path: {file_path}")
        original_texts = await file_service.read_excel_column(
            file_path=file_path,
            column_identifier=job_request.original_text_column
        )
        JOB_STORE[job_id]["original_texts_count"] = len(original_texts)
        JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

        if not original_texts:
            JOB_STORE[job_id]["status"] = AppTranslationJobStatus.FAILED.value
            JOB_STORE[job_id]["error_message"] = "No texts found in the specified column."
            JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
            # No need to raise HTTPException here if we return a proper response later, but for now it's fine.
            print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Job {job_id} failed: No texts found.")
            # The calling router will likely catch this if it expects a specific structure
            # For now, this will bubble up as an exception handled by the generic exception handler below if not caught by API layer.
            # Consider returning a specific error response if create_translation_job is called directly not from router
            raise ValueError("No texts found in the specified column of the Excel file.") # Raise ValueError to be caught by specific handler
        
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Found {len(original_texts)} texts for job: {job_id}. Calling Zhipu AI.")
        
        # 2. Call Zhipu AI service with callback
        zhipu_submission_info = await zhipu_ai_service.translate_batch(
            texts=original_texts,
            api_key=job_request.zhipu_api_key, # This should come from job_request or settings
            source_lang=job_request.source_language,
            target_lang=job_request.target_language,
            model=job_request.model or zhipu_ai_service.DEFAULT_ZHIPU_MODEL,
            main_job_id=job_id,  # Correctly passing main_job_id
            update_callback=_update_job_store_callback # Correctly passing the callback
        )

        # 3. Update JOB_STORE with Zhipu submission details
        JOB_STORE[job_id]["zhipu_batch_id_actual"] = zhipu_submission_info.get("zhipu_batch_id")
        # Initial status update after submission, background task will provide further updates
        # The first callback from background_poll_status will set it to PROCESSING with progress
        # So, we can keep it PENDING or set to a specific "SUBMITTED_TO_ZHIPU" status if desired.
        # For now, let's rely on the first callback to set it to PROCESSING.
        # JOB_STORE[job_id]["status"] = AppTranslationJobStatus.PROCESSING.value 
        JOB_STORE[job_id]["message"] = zhipu_submission_info.get("message", "Task submitted to Zhipu AI for processing.")
        JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Zhipu AI Batch ID {JOB_STORE[job_id]['zhipu_batch_id_actual']} submitted for job: {job_id}. Waiting for callback.")

        return TranslationJobCreateResponse(
            job_id=job_id,
            status=JOB_STORE[job_id]["status"], # Return current status, likely PENDING or as set by initial callback if fast enough
            message=JOB_STORE[job_id]["message"],
            created_at=initial_job_data["created_at"],
            # details_url can be constructed here if your router structure is fixed
        )

    except ValueError as ve: # Catch specific ValueError from no texts found
        if job_id in JOB_STORE:
            JOB_STORE[job_id]["status"] = AppTranslationJobStatus.FAILED.value
            JOB_STORE[job_id]["error_message"] = str(ve)
            JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] ValueError in create_and_process_translation_job for job {job_id}: {ve}")
        # This will be caught by the router if it calls this function
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    except HTTPException as http_exc: # Catch HTTPExceptions from zhipu_ai_service or file_service
        if job_id in JOB_STORE:
            JOB_STORE[job_id]["status"] = AppTranslationJobStatus.FAILED.value
            JOB_STORE[job_id]["error_message"] = http_exc.detail
            JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] HTTPException in create_and_process_translation_job for job {job_id}: {http_exc.detail}")
        raise http_exc # Re-raise to be handled by the API router
    
    except Exception as e:
        error_message_detail = f"An unexpected error occurred in TJS: {type(e).__name__} - {str(e)}"
        if job_id in JOB_STORE:
            JOB_STORE[job_id]["status"] = AppTranslationJobStatus.FAILED.value
            JOB_STORE[job_id]["error_message"] = error_message_detail
            JOB_STORE[job_id]["updated_at"] = datetime.datetime.now(datetime.timezone.utc)
        
        print(f"[{datetime.datetime.now(datetime.timezone.utc)}] [translation_job_service] Error in create_and_process_translation_job for job {job_id}: {error_message_detail}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process translation job due to an internal server error: {error_message_detail}"
        )

async def get_translation_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves the status and data of a translation job from the in-memory store."""
    return JOB_STORE.get(job_id)

async def get_translation_job_status_for_api(job_id: str) -> Optional[Dict[str, Any]]:
    """Helper to retrieve job status, to be called by the router.
       Formats the response slightly, e.g., ensuring datetime is isoformat.
    """
    job_data = JOB_STORE.get(job_id)
    if job_data:
        # Ensure datetimes are in a consistent string format for the API response if not already
        # This is more relevant if JOB_STORE stores actual datetime objects that need serialization
        # For now, assuming they are already ISO strings or will be handled by Pydantic model if one is used for response.
        return job_data 
    return None

# We will add functions later to:
# - Actually write the translated content back to a new Excel file. -> Handled in callback
# - Handle cleanup of temporary files if needed. 