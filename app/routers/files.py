from fastapi import APIRouter, File, UploadFile, HTTPException, status, Depends
from typing import Annotated # For Python 3.9+ style type hints with Depends
import datetime
import uuid

from app.services import file_service
from app.core.config import Settings, get_settings
from app.models import FileUploadResponse
# from app.core.security import get_current_active_user # Example for protected endpoint if needed later

router = APIRouter()

@router.post("/upload", 
             response_model=FileUploadResponse, 
             status_code=status.HTTP_201_CREATED,
             summary="Upload an Excel file for translation.",
             description="Uploads an .xlsx or .xls file. The file will be saved temporarily on the server. "
                         "A unique file ID is returned, which can be used to start a translation job.")
async def upload_file_endpoint(
    # For protected endpoints, you might add: current_user: User = Depends(get_current_active_user),
    file: UploadFile, # FastAPI 会自动处理来自表单的 'file' 字段
    settings: Annotated[Settings, Depends(get_settings)]
):
    """
    Handles file uploads, saves the file using file_service, 
    and returns a response with the file_id and other metadata.
    """
    if not file:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file sent.")

    file_id = str(uuid.uuid4()) # 为新文件生成一个唯一的 ID
    current_time = datetime.datetime.now(datetime.timezone.utc) # 获取当前 UTC 时间
    
    try:
        # 调用 file_service.save_uploaded_file 时，确保传递了 file_id
        saved_file_path = await file_service.save_uploaded_file(
            file=file, 
            file_id=file_id # 这是必需的参数
        )
        
        # (可选) 构建文件的可访问 URL，如果你的应用需要直接提供文件访问
        # file_access_url = f"{settings.SERVER_HOST}{settings.API_V1_STR}/files/download/{file_id}/{file.filename}"
        # print(f"File accessible at: {file_access_url}") # 日志记录

        return FileUploadResponse(
            message="File uploaded successfully.",
            file_id=file_id,
            filename=file.filename,
            content_type=file.content_type or "application/octet-stream",
            size_kb=round(saved_file_path.stat().st_size / 1024, 2),
            uploaded_at=current_time,
            # file_url=file_access_url # 如果构建了 URL，可以包含在这里
        )
    except HTTPException as e:
        # 如果 save_uploaded_file 抛出 HTTPException，直接重新抛出
        raise e
    except Exception as e:
        # 捕获其他潜在错误，并返回一个标准的 500 错误
        print(f"Error during file upload endpoint: {type(e).__name__} - {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred during file upload: {str(e)}"
        )

# You might want a GET endpoint to check file status or metadata later, but not in scope for phase 0
# @router.get("/{file_id}/info", response_model=FileUploadResponse)
# async def get_file_info(file_id: str):
#     # Logic to retrieve file info if it were stored in a DB or manifest
#     # For now, this would require reconstructing info or having a manifest
#     raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="File info endpoint not implemented yet.")

# (可选) 添加一个下载端点示例，如果需要直接下载原始上传的文件
# @router.get("/download/{file_id}/{filename}")
# async def download_uploaded_file(file_id: str, filename: str):
#     try:
#         file_path = await file_service.get_file_path(file_id) # 你可能需要调整 get_file_path 以处理原始文件名或仅用id
#         if file_path.name != filename: # 简单的安全检查
#             raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename mismatch")
#         return FileResponse(file_path, filename=filename)
#     except HTTPException as e:
#         raise e
#     except Exception as e:
#         raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) 