from fastapi import APIRouter, HTTPException, status, Path as FastApiPath, Body, Depends, UploadFile, BackgroundTasks, Form
from typing import Any, Dict, Optional, Annotated # Added Optional for HttpUrl, moved Annotated here
import datetime # Required for JobStatusResponse
from pathlib import Path
from fastapi.responses import FileResponse
import uuid
import traceback

from app.models import (
    TranslationJobRequest,
    TranslationJobCreateResponse,
    JobStatusResponse,
    JobStatusProgress,
    HttpUrl # Ensure HttpUrl is imported if used in models directly for type hint
)
from app.services import translation_job_service, file_service
from app.core.config import settings, Settings # For constructing detail_url if needed AND for type hint
from app.core.config import get_settings

router = APIRouter()

@router.post(
    "/",
    response_model=TranslationJobCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and start a new translation job using a previously uploaded file.",
    description=(
        "Initiates a translation job using a `file_id` obtained from the file upload endpoint. "
        "All parameters for the job must be provided as form fields."
    )
)
async def create_translation_job(
    # 没有默认值的参数（包括 FastAPI 特殊参数和依赖项）放在前面
    background_tasks: BackgroundTasks,
    settings: Annotated[Settings, Depends(get_settings)],
    # 作业参数通过 Form 传递
    file_id: str = Form(..., description="The unique ID of the file previously uploaded via the /files/upload endpoint."),
    original_filename: Optional[str] = Form(None, description="(Optional but recommended) The original filename associated with the file_id. Helps in identifying the correct file if needed."),
    original_text_column: str = Form(..., description="Name or letter of the column in the Excel file containing the text to be translated (e.g., 'A' or 'Source Text')."),
    translated_text_column_name: str = Form("Translated Text", description="Desired name for the new column that will contain the translated text."),
    source_lang: str = Form("en", description="Source language code (e.g., 'en')."),
    target_lang: str = Form("zh", description="Target language code (e.g., 'zh')."),
    project_name: Optional[str] = Form(None, description="Optional name for the translation project."),
    texts_per_chunk: Optional[int] = Form(
        default=None, 
        ge=1, 
        le=200, # Match model limits
        description="Optional: Number of lines per chunk for Zhipu batch processing. Uses server default if not provided."
    )
):
    """
    Creates a new translation job based on a `file_id` from a previous upload.
    User provides job parameters like column names and language settings. 
    The ZhipuAI API key is taken from server settings.
    """
    try:
        if not settings.ZHIPU_API_KEY:
            print("Error: ZHIPU_API_KEY is not configured in settings.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error: Zhipu AI API Key is not set. Please contact the administrator."
            )
        
        job_request = TranslationJobRequest(
            file_id=file_id, 
            original_filename=original_filename, 
            original_text_column=original_text_column,
            translated_text_column_name=translated_text_column_name, 
            source_language=source_lang,
            target_language=target_lang,
            zhipu_api_key=settings.ZHIPU_API_KEY, 
            project_name=project_name,
            # model and tag_patterns will use defaults from Pydantic model if not passed via Form
            # texts_per_chunk will be handled by service layer using global config
            texts_per_chunk=texts_per_chunk # Assign the form value to the model field
        )
        
        job_response = await translation_job_service.create_and_process_translation_job(
            job_request=job_request,
            background_tasks=background_tasks
        )

        if job_response:
            if hasattr(job_response, 'details_url') and settings.SERVER_HOST and settings.API_V1_STR:
                 details_url_str = f"{settings.SERVER_HOST.rstrip('/')}{settings.API_V1_STR.rstrip('/')}/translation-jobs/{job_response.job_id}/status"
                 try:
                     job_response.details_url = HttpUrl(details_url_str)
                 except Exception as e:
                     print(f"Warning: Could not construct valid details_url: {e}")
                     job_response.details_url = None
            return job_response
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create translation job due to an unexpected error in the service layer."
            )
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Unexpected error in create_translation_job endpoint: {type(e).__name__} - {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred while creating the translation job: {str(e)}"
        )

@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    summary="Get the status of a specific translation job.",
    description="Retrieves the current status, progress, and other details of a translation job by its ID."
)
async def get_job_status(
    job_id: str = FastApiPath(..., description="The ID of the translation job to query.", example="a1b2c3d4-e5f6-7890-1234-567890abcdef")
):
    """
    Get the status of a translation job.

    - **job_id**: The unique identifier of the job.
    """
    job_data = await translation_job_service.get_translation_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Translation job with ID '{job_id}' not found.")

    request_details = job_data.get("request_details", {})
    
    progress_data = JobStatusProgress(
        total_items=job_data.get("original_texts_count", 0),
        processed_items=job_data.get("translated_texts_count", 0),
        failed_items=0, # Placeholder for now
        progress_percentage=100.0 if job_data.get("status") == "completed" else 0.0
    )

    download_url_val = None
    if job_data.get("status") == "completed" and settings.SERVER_HOST:
        base_url = str(settings.SERVER_HOST).rstrip('/')
        download_url_str = f"{base_url}{settings.API_V1_STR}/translation-jobs/{job_id}/download"
        try:
            download_url_val = HttpUrl(download_url_str)
        except Exception:
            download_url_val = None # Or log a warning
            
    return JobStatusResponse(
        job_id=job_id,
        status=job_data.get("status", "unknown"),
        message=f"Job status for {job_id}. Original texts: {job_data.get('original_texts_count',0)}, Translated: {job_data.get('translated_texts_count',0)}.",
        created_at=job_data.get("created_at", datetime.datetime.now(datetime.timezone.utc)),
        updated_at=job_data.get("updated_at", datetime.datetime.now(datetime.timezone.utc)),
        progress=progress_data,
        download_url=download_url_val
    )

@router.get(
    "/{job_id}/download",
    summary="Download the translated Excel file for a completed job.",
    response_class=FileResponse,
    responses={
        200: {
            "description": "The translated Excel file.",
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/octet-stream": {} # Fallback
            }
        },
        404: {"description": "Job not found or translated file not available."},
        409: {"description": "Job is not yet completed."}
    }
)
async def download_translated_file(
    job_id: str = FastApiPath(..., description="The ID of the completed translation job.")
):
    """
    Allows downloading the Excel file containing the translated text
    once the translation job is completed and the file has been generated.
    """
    job_data = await translation_job_service.get_translation_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Translation job with ID '{job_id}' not found.")

    if job_data.get("status") != "completed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Translation job '{job_id}' is not yet completed. Current status: {job_data.get('status')}")

    output_file_path_str = job_data.get("output_file_path")
    if not output_file_path_str:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Translated file not available for job ID '{job_id}'. It might have failed during generation or the job is incomplete.")

    output_file_path = Path(output_file_path_str)
    if not output_file_path.exists() or not output_file_path.is_file():
        print(f"Error: Output file path found in job store for job '{job_id}' but file does not exist at '{output_file_path}'.")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Translated file for job ID '{job_id}' seems to be missing from the server.")

    original_filename_base = "translated_output"
    try:
        original_filename = job_data.get("request_details", {}).get("original_filename", f"job_{job_id}_translated.xlsx")
        original_filename_base = Path(original_filename).stem
    except Exception:
        pass 
        
    download_filename = f"{original_filename_base}_{job_id}_translated.xlsx"

    return FileResponse(
        path=output_file_path,
        filename=download_filename,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )

# Placeholder for future download endpoint
# @router.get(
#     "/{job_id}/download",
#     summary="Download the translated Excel file for a completed job.",
#     response_class=FileResponse or StreamingResponse # Will be used here
# )
# async def download_translated_file(
#     job_id: str = FastApiPath(..., description="The ID of the completed translation job.")
# ):
#     # Logic to find the translated file path from JOB_STORE or a designated output directory
#     # Serve the file
#     raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Download endpoint not implemented yet.") 