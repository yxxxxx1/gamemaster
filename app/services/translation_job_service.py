import datetime
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import asyncio
import traceback
import time

from fastapi import HTTPException, status, BackgroundTasks, UploadFile

from app.models import TranslationJobRequest, TranslationJobCreateResponse, TranslationJobStatus as AppTranslationJobStatus
from app.services import file_service
from app.services import zhipu_ai_service
from app.services.zhipu_ai_service import TaskStatus as ZhipuTaskStatus
from app.services.tag_protection_service import TagProtectionService
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Global job store for this service
JOB_STORE: Dict[str, Dict[str, Any]] = {}

# 创建TagProtectionService实例
tag_service = TagProtectionService()

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

def _parse_custom_id_for_sorting(custom_id: str) -> Tuple[int, int]:
    """
    Parses custom_id like 'request_jobId_chunk_CHUNKIDX_LINEIDX' into (CHUNKIDX, LINEIDX) for sorting.
    Returns (float('inf'), float('inf')) on failure to parse, pushing malformed IDs to the end.
    """
    try:
        # Find "chunk_" and then extract indices. This is more robust to job_id containing underscores.
        parts = custom_id.split("_")
        chunk_keyword_idx = -1
        # Iterate to find "chunk" as job_id itself might have underscores
        for i, part_val in enumerate(parts):
            if part_val == "chunk" and i + 2 < len(parts): # Need two more parts for chunk_idx and line_idx
                chunk_keyword_idx = i
                break
        
        if chunk_keyword_idx != -1:
            chunk_idx = int(parts[chunk_keyword_idx + 1])
            line_idx = int(parts[chunk_keyword_idx + 2])
            return chunk_idx, line_idx
        else:
            logger.warning(f"Could not parse chunk and line indices from custom_id: {custom_id} - 'chunk' keyword not found or insufficient parts.")
            return (float('inf'), float('inf'))
    except (ValueError, IndexError) as e:
        logger.warning(f"Error parsing custom_id '{custom_id}' for sorting: {e}")
        return (float('inf'), float('inf'))

async def _update_job_store_callback(
    main_job_id: str, 
    status_from_zhipu: ZhipuTaskStatus, 
    zhipu_batch_id: str,
    **kwargs: Any
) -> None:
    logger.info(f"TJS_CALLBACK: Received update for MainJobId '{main_job_id}', ZhipuBatchID '{zhipu_batch_id}'. Status: {status_from_zhipu}. Kwargs: {kwargs}")
    if main_job_id not in JOB_STORE:
        logger.error(f"TJS_CALLBACK: ERROR - MainJobId '{main_job_id}' not found in JOB_STORE. Ignoring callback for ZhipuBatchID '{zhipu_batch_id}'.")
        return

    job_entry = JOB_STORE[main_job_id]
    job_entry["updated_at"] = datetime.datetime.now(datetime.timezone.utc)

    # 更新任务状态
    if status_from_zhipu == ZhipuTaskStatus.COMPLETED:
        zhipu_output_file_id = kwargs.get("zhipu_output_file_id")
        if zhipu_output_file_id:
            logger.info(f"TJS_CALLBACK: ZhipuBatchID '{zhipu_batch_id}' (MainJobId '{main_job_id}') completed. Output File ID: {zhipu_output_file_id}. Downloading results.")
            try:
                # 获取必要的映射和API密钥
                api_key = job_entry["zhipu_api_key"]
                placeholders_map = job_entry["placeholders_map"]
                chunk_details_map = job_entry["chunk_details_map"]
                tag_maps = job_entry["tag_maps"]  # 获取标签映射

                processed_results = await zhipu_ai_service.download_and_process_results(
                    api_key=api_key,
                    output_file_id=zhipu_output_file_id,
                    chunk_details_map=chunk_details_map
                )

                # 还原翻译结果中的标签
                restored_results = []
                for translated_text, tag_map in zip(processed_results, tag_maps):
                    restored_text = tag_service.restore_tags(translated_text, tag_map)
                    restored_results.append(restored_text)

                # 更新任务状态和结果
                job_entry.update({
                    "status": AppTranslationJobStatus.COMPLETED.value,
                    "progress_percentage": 100,
                    "aggregated_translations": restored_results,  # 使用还原后的结果
                    "translated_texts_count": len(restored_results),
                    "message": "Translation completed successfully."
                })

                # 写入Excel文件
                try:
                    request_details = job_entry.get("request_details", {})
                    original_file_id = request_details.get("file_id")
                    original_file_path_str = job_entry.get("file_path_processed")
                    
                    if original_file_path_str and original_file_id:
                        output_file_path = await file_service.write_excel_with_translations(
                            original_file_path=Path(original_file_path_str),
                            translations=job_entry["aggregated_translations"],
                            original_text_column_name=request_details.get("original_text_column", "original_text"),
                            new_translated_column_name=request_details.get("translated_text_column_name", "translated_text"),
                            project_name=request_details.get("project_name"),
                            base_filename_suffix="_translated"
                        )
                        job_entry["output_file_path"] = str(output_file_path)
                        logger.info(f"TJS_CALLBACK: Translated Excel saved for MainJobId '{main_job_id}' at: {output_file_path}")
                    else:
                        logger.warning(f"TJS_CALLBACK: Could not write Excel for MainJobId '{main_job_id}'. Missing path info.")
                        job_entry["error_message"] = "Failed to write output Excel (missing path)."
                except Exception as e_write_excel:
                    logger.error(f"TJS_CALLBACK: ERROR writing Excel for MainJobId '{main_job_id}': {e_write_excel}", exc_info=True)
                    job_entry["error_message"] = f"Failed to write output Excel: {e_write_excel}"
                    job_entry["status"] = AppTranslationJobStatus.COMPLETED_WITH_ISSUES.value

            except Exception as e_download:
                logger.error(f"TJS_CALLBACK: ERROR downloading/processing results for ZhipuBatchID '{zhipu_batch_id}': {e_download}", exc_info=True)
                job_entry.update({
                    "status": AppTranslationJobStatus.FAILED.value,
                    "error_message": f"Failed to download/process results: {e_download}"
                })
        else:
            logger.warning(f"TJS_CALLBACK: ZhipuBatchID '{zhipu_batch_id}' completed but no zhipu_output_file_id provided.")
            job_entry.update({
                "status": AppTranslationJobStatus.FAILED.value,
                "error_message": "Zhipu batch completed but no output_file_id found"
            })
    
    elif status_from_zhipu == ZhipuTaskStatus.FAILED:
        error_msg = kwargs.get("error", "Unknown error")
        job_entry.update({
            "status": AppTranslationJobStatus.FAILED.value,
            "error_message": f"Translation failed: {error_msg}"
        })
        logger.warning(f"TJS_CALLBACK: ZhipuBatchID '{zhipu_batch_id}' (MainJobId '{main_job_id}') FAILED. Error: {error_msg}")
    
    elif status_from_zhipu == ZhipuTaskStatus.PROCESSING:
        progress = kwargs.get("progress", 0)
        job_entry.update({
            "status": AppTranslationJobStatus.PROCESSING.value,
            "progress_percentage": progress,
            "message": f"Translation in progress: {progress}%"
        })
        logger.info(f"TJS_CALLBACK: MainJobId '{main_job_id}' progress: {progress}%")

    logger.info(f"TJS_CALLBACK: JOB_STORE updated for MainJobId '{main_job_id}': Status='{job_entry['status']}', Progress={job_entry.get('progress_percentage')}%")

async def create_and_process_translation_job(
    job_request: TranslationJobRequest,
    background_tasks: BackgroundTasks
) -> TranslationJobCreateResponse:
    job_id = str(uuid.uuid4())
    current_time = datetime.datetime.now(datetime.timezone.utc)

    if not settings.ZHIPU_API_KEY:
        logger.critical("CRITICAL ERROR: ZHIPU_API_KEY is not configured.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server configuration error: Zhipu AI API Key is not set."
        )

    initial_job_data = {
        "job_id": job_id,
        "status": AppTranslationJobStatus.PENDING.value,
        "request_details": job_request.model_dump(),
        "file_path_processed": None,
        "output_file_path": None,
        "original_texts_count": 0,
        "translated_texts_count": 0,
        "progress_percentage": 0,
        "created_at": current_time,
        "updated_at": current_time,
        "zhipu_api_key": job_request.zhipu_api_key,
        "placeholders_map": {},
        "chunk_details_map": {},
        "zhipu_batch_id": None,
        "error_message": None,
        "aggregated_translations": None,
        "message": "Job initiated.",
        "tag_maps": []  # 新增：存储每个文本的标签映射
    }
    JOB_STORE[job_id] = initial_job_data

    try:
        logger.info(f"Starting job: {job_id} for file_id: {job_request.file_id}, original_filename: {job_request.original_filename}")
        
        file_path = await file_service.get_file_path(job_request.file_id)
        if not file_path or not await asyncio.to_thread(Path(file_path).exists):
            error_msg = f"Uploaded file not found for file_id: {job_request.file_id}"
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": error_msg, "updated_at": datetime.datetime.now(datetime.timezone.utc)})
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        
        JOB_STORE[job_id]["file_path_processed"] = str(file_path)
        
        original_texts = await file_service.read_excel_column(
            file_path=file_path,
            column_identifier=job_request.original_text_column
        )
        JOB_STORE[job_id]["original_texts_count"] = len(original_texts)

        if not original_texts:
            error_msg = "No texts found in the specified column."
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": error_msg, "updated_at": datetime.datetime.now(datetime.timezone.utc)})
            raise ValueError(error_msg)
        
        logger.info(f"Found {len(original_texts)} texts for job: {job_id}. Processing tags and calling Zhipu AI service.")
        
        # 保护所有文本中的标签
        protected_texts = []
        tag_maps = []
        for text in original_texts:
            protected_text, tag_map = tag_service.protect_tags(text)
            protected_texts.append(protected_text)
            tag_maps.append(tag_map)
        
        # 更新任务数据
        JOB_STORE[job_id]["tag_maps"] = tag_maps
        
        # 将所有文本合并到一个批量任务中
        zhipu_response_data = await zhipu_ai_service.translate_batch(
            texts=protected_texts,  # 使用保护后的文本
            api_key=job_request.zhipu_api_key,
            source_lang=job_request.source_language,
            target_lang=job_request.target_language,
            model=job_request.model or zhipu_ai_service.DEFAULT_ZHIPU_MODEL,
            main_job_id=job_id,
            texts_per_chunk=job_request.texts_per_chunk
        )

        zhipu_batch_id = zhipu_response_data.get("batch_job_id")  # 现在只获取一个batch_id
        placeholders_map = zhipu_response_data.get("placeholders_map", {})
        chunk_details_map = zhipu_response_data.get("chunk_details_map", {})

        if not zhipu_batch_id:
            error_msg = "Zhipu AI service did not return a batch job ID."
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": error_msg, "updated_at": datetime.datetime.now(datetime.timezone.utc)})
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_msg)

        JOB_STORE[job_id].update({
            "placeholders_map": placeholders_map,
            "chunk_details_map": chunk_details_map,
            "zhipu_batch_id": zhipu_batch_id,
            "status": AppTranslationJobStatus.PROCESSING.value,
            "message": "Batch job submitted to Zhipu AI for processing. Polling started.",
            "updated_at": datetime.datetime.now(datetime.timezone.utc)
        })

        # 启动单个后台轮询任务
        background_tasks.add_task(
            zhipu_ai_service.background_poll_status,
            main_job_id=job_id,
            zhipu_batch_id=zhipu_batch_id,
            api_key=job_request.zhipu_api_key,
            update_callback=_update_job_store_callback
        )
        logger.info(f"Job {job_id}: Started background polling task for Zhipu batch ID: {zhipu_batch_id}")

        return TranslationJobCreateResponse(
            job_id=job_id,
            status=JOB_STORE[job_id]["status"],
            message=JOB_STORE[job_id]["message"],
            created_at=initial_job_data["created_at"],
        )

    except ValueError as ve:
        if job_id in JOB_STORE:
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": str(ve), "updated_at": datetime.datetime.now(datetime.timezone.utc)})
        logger.warning(f"ValueError in create_and_process_translation_job for job {job_id}: {ve}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))

    except HTTPException as http_exc:
        if job_id in JOB_STORE:
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": http_exc.detail, "updated_at": datetime.datetime.now(datetime.timezone.utc)})
        logger.warning(f"HTTPException in create_and_process_translation_job for job {job_id}: {http_exc.detail}", exc_info=True)
        raise http_exc
    
    except Exception as e:
        error_message_detail = f"An unexpected error occurred in TJS create_and_process: {type(e).__name__} - {str(e)}"
        if job_id in JOB_STORE:
            JOB_STORE[job_id].update({"status": AppTranslationJobStatus.FAILED.value, "error_message": error_message_detail, "updated_at": datetime.datetime.now(datetime.timezone.utc)})
        logger.error(f"Error in create_and_process_translation_job for job {job_id}: {error_message_detail}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_message_detail
        )

async def get_translation_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    return JOB_STORE.get(job_id)

async def get_translation_job_status_for_api(job_id: str) -> Optional[Dict[str, Any]]:
    job_data = JOB_STORE.get(job_id)
    if job_data:
        # Create a copy to avoid modifying JOB_STORE directly if further processing is done here
        response_data = job_data.copy()
        # Ensure datetimes are ISO strings if they are datetime objects
        for key in ["created_at", "updated_at"]:
            if isinstance(response_data.get(key), datetime.datetime):
                response_data[key] = response_data[key].isoformat()
        
        # Optionally, simplify or prune what's returned to the API
        # For example, 'placeholders_map' or 'chunk_details_map' might be too large or internal.
        # 'aggregated_translations' might also be too large for a status check; usually a separate download endpoint for results.
        # For now, returning most of it for debugging.
        # Consider removing or summarizing large fields like 'aggregated_translations', 'placeholders_map' for API status.
        # response_data.pop("placeholders_map", None)
        # response_data.pop("chunk_details_map", None)
        # if response_data.get("aggregated_translations"):
        #    response_data["message"] += " Translations are available." # Indicate availability without sending all data
        #    response_data.pop("aggregated_translations")


        return response_data
    return None

# We will add functions later to:
# - Actually write the translated content back to a new Excel file. -> Handled in callback
# - Handle cleanup of temporary files if needed. 