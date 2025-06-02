from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from app.services.translation_quality_service import TranslationQualityService, QualityScore
from app.core.config import get_settings, Settings

router = APIRouter()

class TranslationEvaluationRequest(BaseModel):
    """翻译评估请求"""
    source_text: str
    translated_text: str
    source_lang: str = "en"
    target_lang: str = "zh"
    job_id: Optional[str] = None

class TranslationEvaluationResponse(BaseModel):
    """翻译评估响应"""
    job_id: Optional[str]
    overall_score: float
    tag_preservation_score: float
    format_preservation_score: float
    semantic_accuracy_score: float
    fluency_score: float
    issues: List[str]
    suggestions: List[str]
    evaluation_time: datetime

class ExcelQualityEvaluationResponse(BaseModel):
    result_file: str  # 评估结果Excel文件的路径或下载链接

@router.post(
    "/evaluate",
    response_model=TranslationEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="评估翻译质量",
    description="对翻译文本进行质量评估，包括标签保留、格式保留、语义准确性和流畅度等方面。"
)
async def evaluate_translation(
    request: TranslationEvaluationRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings)
) -> TranslationEvaluationResponse:
    """
    评估翻译质量
    
    - **source_text**: 源文本
    - **translated_text**: 翻译后的文本
    - **source_lang**: 源语言代码（默认：en）
    - **target_lang**: 目标语言代码（默认：zh）
    - **job_id**: 可选的作业ID，用于关联评估结果
    """
    try:
        quality_service = TranslationQualityService()
        
        # 执行评估
        evaluation_result = await quality_service.evaluate_translation(
            source_text=request.source_text,
            translated_text=request.translated_text,
            source_lang=request.source_lang,
            target_lang=request.target_lang
        )
        
        # 如果有job_id，在后台保存评估结果
        if request.job_id:
            background_tasks.add_task(
                quality_service.save_evaluation_result,
                request.job_id,
                evaluation_result
            )
        
        return TranslationEvaluationResponse(
            job_id=request.job_id,
            overall_score=evaluation_result.overall_score,
            tag_preservation_score=evaluation_result.tag_preservation_score,
            format_preservation_score=evaluation_result.format_preservation_score,
            semantic_accuracy_score=evaluation_result.semantic_accuracy_score,
            fluency_score=evaluation_result.fluency_score,
            issues=evaluation_result.issues,
            suggestions=evaluation_result.suggestions,
            evaluation_time=datetime.now()
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"评估过程中发生错误: {str(e)}"
        )

@router.post(
    "/evaluate_excel",
    response_model=ExcelQualityEvaluationResponse,
    summary="批量评估Excel翻译质量",
    description="上传Excel文件并指定源文本和翻译文本列，对每一行进行翻译质量评估，返回带评估结果的新Excel文件。"
)
async def evaluate_excel_translation_quality(
    file: UploadFile = File(..., description="上传的Excel文件"),
    source_col: str = Form(..., description="源文本列名"),
    target_col: str = Form(..., description="翻译文本列名"),
    source_lang: str = Form("en", description="源语言代码"),
    target_lang: str = Form("zh", description="目标语言代码")
) -> ExcelQualityEvaluationResponse:
    """
    批量评估Excel文件中的翻译质量
    """
    try:
        # 保存上传的文件
        temp_path = f"app/temp_files/{file.filename}"
        with open(temp_path, "wb") as f_out:
            f_out.write(await file.read())

        # 评估
        quality_service = TranslationQualityService()
        df = await quality_service.evaluate_excel_translations(
            excel_path=temp_path,
            source_col=source_col,
            target_col=target_col,
            source_lang=source_lang,
            target_lang=target_lang
        )

        # 保存结果
        output_path = temp_path.replace('.xlsx', '_evaluated.xlsx')
        quality_service.save_excel_evaluation_result(df, output_path)

        # 返回结果文件路径（可根据需要返回下载链接）
        return ExcelQualityEvaluationResponse(result_file=output_path)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"批量评估过程中发生错误: {str(e)}"
        )

@router.get(
    "/download_evaluation_file",
    response_class=FileResponse,
    summary="下载Excel评估结果文件"
)
async def download_evaluation_file(file_path: str):
    return FileResponse(file_path, filename=file_path.split('/')[-1])

@router.get(
    "/evaluation/{job_id}",
    response_model=TranslationEvaluationResponse,
    status_code=status.HTTP_200_OK,
    summary="获取翻译评估结果",
    description="获取指定作业ID的翻译质量评估结果。"
)
async def get_evaluation_result(
    job_id: str,
    settings: Settings = Depends(get_settings)
) -> TranslationEvaluationResponse:
    """
    获取翻译评估结果
    
    - **job_id**: 作业ID
    """
    try:
        quality_service = TranslationQualityService()
        result_file = f"app/output_files/quality_evaluations/evaluation_{job_id}.json"
        
        # TODO: 实现从文件读取评估结果的逻辑
        
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"未找到作业ID为 {job_id} 的评估结果"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取评估结果时发生错误: {str(e)}"
        ) 