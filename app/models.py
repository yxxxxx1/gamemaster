# app/models.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, HttpUrl # type: ignore
import datetime
import uuid # For generating job_id if needed within models, or usually in service layer
import enum # Add this import

# --- General Models ---
class APIBaseModel(BaseModel):
    class Config:
        from_attributes = True # Replaces orm_mode in Pydantic v2
        # For FastAPI to convert between camelCase (JSON) and snake_case (Python)
        # alias_generator = lambda string: ''.join(word.capitalize() if i != 0 else word for i, word in enumerate(string.split('_')))
        # populate_by_name = True # Replaces allow_population_by_field_name
        pass

# --- File Upload Models ---
class FileUploadResponse(APIBaseModel):
    file_id: str = Field(..., description="Unique identifier for the uploaded file.")
    filename: str = Field(..., description="Original name of the uploaded file.")
    uploaded_at: datetime.datetime = Field(..., description="Timestamp of when the file was uploaded.")
    content_type: Optional[str] = Field(None, description="Content type of the uploaded file.")
    size_kb: Optional[float] = Field(None, description="Size of the uploaded file in kilobytes.")
    message: str
    file_url: Optional[HttpUrl] = None


# --- Translation Job Models ---
class TranslationServiceConfig(APIBaseModel):
    provider: str = Field("zhipu_ai", description="Translation service provider.", examples=["zhipu_ai"],Frozen=True)
    api_key: str = Field(..., description="API Key for the translation service.", examples=["your_api_key_here"])
    use_batch_api: bool = Field(True, description="Whether to use the batch API endpoint.", examples=[True], Frozen=True)
    model: Optional[str] = Field(None, description="Specific model name for the translation service, if applicable.", examples=["glm-4"])

class TranslationJobRequest(APIBaseModel):
    file_id: str = Field(..., description="The unique ID of the uploaded Excel file.", example="xxxx-xxxx-xxxx-xxxx")
    original_filename: str = Field(..., description="The original filename of the uploaded Excel file (e.g., 'my_texts.xlsx'). Used to locate the file.", example="localization_sheet_v1.xlsx")
    source_language: str = Field(..., description="Source language code (e.g., 'en', 'ja').", example="en")
    target_language: str = Field(..., description="Target language code (e.g., 'zh', 'ko').", example="zh")
    original_text_column: str = Field(
        ...,
        description="Identifier for the column in the Excel file containing the original text. Can be a column letter (e.g., 'A') or a column header name (e.g., 'Source Text').",
        example="A"
    )
    translated_text_column_name: str = Field(
        ...,
        description="The desired name for the new column that will contain the translated text.",
        example="Translated Text (ZH)"
    )
    zhipu_api_key: str = Field(
        ...,
        description="Your Zhipu AI API Key. This will be used to authenticate with the translation service.",
        example="YOUR_API_KEY_HERE"
    )
    tag_patterns: Optional[List[str]] = Field(
        default_factory=lambda: [r"{\$.*?}", r"<[^>]+>"], # Example default patterns
        description="A list of regular expressions to identify and protect tags/placeholders within the text. "
                    "Defaults to patterns for {$variable} and <html_tag> style tags.",
        example=[r"{\$.*?}", r"<[^>]+>", r"%%.*?%%"]
    )
    project_name: Optional[str] = Field(
        default=None,
        description="An optional name for the translation project, for organizational purposes.",
        example="My Game Localization Project v1"
    )
    model: Optional[str] = Field(None, description="Optional Zhipu AI model name to be used for translation. Defaults to the system default if not provided.")
    texts_per_chunk: Optional[int] = Field(
        default=None, # If None, service will use global config or a hardcoded default
        ge=1, 
        le=200, # Example limits, adjust as needed for Zhipu API
        description="Optional: Number of text lines to bundle into a single sub-request within a Zhipu batch job. "
                    "Overrides server default if provided. Affects API call frequency and data per call."
    )
    # We might add custom_glossary later if needed, keeping it simple for now as per initial doc.
    # custom_glossary: Optional[Dict[str, str]] = Field(
    #     default=None,
    #     description="Optional custom glossary for specific term translations (source_term: target_term).",
    #     example={"Developer Mode": "开发者模式"}
    # )

    class Config:
        json_schema_extra = {
            "example": {
                "file_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
                "original_filename": "game_dialogue_chapter1.xlsx",
                "source_language": "en",
                "target_language": "zh",
                "original_text_column": "SourceString",
                "translated_text_column_name": "Chinese Translation",
                "zhipu_api_key": "your.secret.api.key.from.zhipu",
                "tag_patterns": [r"{\$.*?}", r"<unity_rich_text_tag.*?>"],
                "project_name": "Project Alpha - UI Strings"
            }
        }

# --- Enum for Job Status --- 
class TranslationJobStatus(str, enum.Enum):
    PENDING = "pending"      # 新增：任务已创建，等待处理
    PROCESSING = "processing"  # 新增：任务正在处理中
    PROCESSING_CHUNKS = "processing_chunks"  # New status: Main job is actively managing/waiting for chunks
    COMPLETED = "completed"    # 任务已成功完成
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # New status: If some chunks failed but others succeeded
    FAILED = "failed"        # 任务处理失败
    # 你可以根据需要添加更多状态，例如 CANCELLING, CANCELLED, VALIDATING_INPUT 等

class TranslationJobCreateResponse(APIBaseModel):
    job_id: str = Field(..., description="The unique ID assigned to the translation job.", example=str(uuid.uuid4()))
    status: TranslationJobStatus # 使用枚举类型
    message: Optional[str] = Field(default=None, description="An optional message regarding the job creation.", example="Translation job successfully queued.")
    created_at: datetime.datetime = Field(..., description="Timestamp of when the job was created.")
    details_url: Optional[HttpUrl] = Field(default=None, description="URL to get the status/details of this job.", example="http://localhost:8000/api/v1/translation-jobs/xxxx-xxxx-xxxx-xxxx/status")

# We will also need models for Job Status and other responses later,
# such as JobStatusResponse, SupportedLanguage, etc.
# For now, focusing on the creation part.

class JobStatusProgress(APIBaseModel):
    total_items: int = Field(..., description="Total number of text items to translate.")
    processed_items: int = Field(0, description="Number of text items processed so far.")
    failed_items: int = Field(0, description="Number of text items that failed to translate.")
    progress_percentage: float = Field(0.0, ge=0, le=100, description="Overall progress percentage.")

class JobStatusResponse(APIBaseModel):
    job_id: str = Field(..., description="The unique ID of the translation job.")
    status: TranslationJobStatus # 使用枚举类型
    message: Optional[str] = Field(default=None, description="A message providing more details about the current status.")
    original_filename: Optional[str] = Field(default=None, description="The original filename of the uploaded Excel file.")
    created_at: datetime.datetime = Field(..., description="Timestamp of when the job was created.")
    updated_at: Optional[datetime.datetime] = Field(default=None, description="Timestamp of the last status update.")
    progress: Optional[JobStatusProgress] = Field(default=None, description="Detailed progress information if available.")
    download_url: Optional[HttpUrl] = Field(default=None, description="URL to download the translated file once the job is completed.")
    error_details: Optional[str] = Field(default=None, description="Error details if the job failed or partially failed.")

# Models for configuration endpoints (as per Dev Guide 5.1.2 & 5.1.4)
class SupportedLanguage(APIBaseModel):
    code: str = Field(..., description="Language code (e.g., 'en', 'zh').", example="en")
    name: str = Field(..., description="Human-readable language name (e.g., 'English', 'Chinese').", example="English")

class SupportedLanguagesResponse(APIBaseModel):
    supported_languages: List[SupportedLanguage]

class DefaultTagPattern(APIBaseModel):
    name: str = Field(..., description="A descriptive name for the tag pattern.", example="Brace Variables")
    pattern: str = Field(..., description="The regular expression pattern.", example=r"{\$.*?}")
    description: Optional[str] = Field(default=None, description="Explanation of what this pattern matches.")

class DefaultTagPatternsResponse(APIBaseModel):
    default_patterns: List[DefaultTagPattern]

class ErrorDetail(APIBaseModel):
    loc: Optional[List[str]] = None
    msg: str
    type: str

class HTTPValidationError(APIBaseModel):
    detail: Optional[List[ErrorDetail]] = None

    class Config:
        json_schema_extra = {
            "example": {
                "detail": [
                    {
                        "loc": ["body", "source_language"],
                        "msg": "field required",
                        "type": "value_error.missing"
                    }
                ]
            }
        }

# A generic error response model could also be useful
class GenericErrorResponse(APIBaseModel):
    detail: str

    class Config:
        json_schema_extra = {
            "example": {
                "detail": "An unexpected error occurred."
            }
        }

# --- Config API Models ---
class SupportedLanguage(APIBaseModel):
    code: str = Field(..., description="Language code.")
    name: str = Field(..., description="Human-readable language name.")

class SupportedLanguagesResponse(APIBaseModel):
    source_languages: List[SupportedLanguage]
    target_languages: List[SupportedLanguage]

class DefaultTagPattern(APIBaseModel):
    name: str = Field(..., description="Name of the tag pattern.")
    regex: str = Field(..., description="Regular expression for the pattern.")
    description: Optional[str] = Field(None, description="Description of what the pattern matches.")

class DefaultTagPatternsResponse(APIBaseModel):
    patterns: List[DefaultTagPattern]

# --- Error Model (FastAPI handles HTTPException well, but you can define custom ones if needed) ---
class ErrorDetail(APIBaseModel):
    type: Optional[str] = Field(None, description="Custom error type code.")
    message: str = Field(..., description="A human-readable error message.")
    fields: Optional[Dict[str, Any]] = Field(None, description="Details for specific field errors during validation.") # Changed to Dict[str, Any] for flexibility

class ErrorResponse(APIBaseModel): # This can be used with custom exception handlers
    detail: ErrorDetail 