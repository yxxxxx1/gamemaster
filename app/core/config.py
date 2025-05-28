from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from pathlib import Path
from typing import Optional # Added for ZHIPU_API_KEY

class Settings(BaseSettings):
    APP_NAME: str = "AI Game Localization File Translation Tool"
    API_V1_STR: str = "/api/v1"
    
    # Resolve PROJECT_ROOT_DIR correctly, assuming this config.py is in app/core/
    PROJECT_ROOT_DIR: Path = Path(__file__).resolve().parent.parent.parent
    TEMP_FILES_DIR: Path = PROJECT_ROOT_DIR / "app" / "temp_files" # Directly define the path
    OUTPUT_FILES_DIR: Path = PROJECT_ROOT_DIR / "app" / "output_files" # Added output directory
    SERVER_HOST: Optional[str] = "http://localhost:8000" # Added for constructing full URLs

    # Optional: Load ZHIPU_API_KEY directly from environment if you prefer
    # This allows it to be None if not set, and you can handle it in your service layer
    ZHIPU_API_KEY: str 

    # Create directories if they don't exist when settings are loaded
    def __init__(self, **values):
        super().__init__(**values)
        os.makedirs(self.TEMP_FILES_DIR, exist_ok=True)
        os.makedirs(self.OUTPUT_FILES_DIR, exist_ok=True) # Create output directory as well
        # print(f"DEBUG: TEMP_FILES_DIR in Settings init: {self.TEMP_FILES_DIR}") # For debugging
        # print(f"DEBUG: OUTPUT_FILES_DIR in Settings init: {self.OUTPUT_FILES_DIR}")

    model_config = SettingsConfigDict(
        env_file= str(PROJECT_ROOT_DIR / ".env"), # Load .env from project root
        env_file_encoding='utf-8',
        extra="ignore" # Ignore extra fields from .env if any
    )

settings = Settings()

# Dependency function to get settings
def get_settings():
    return settings

# For debugging during development, you can print paths:
print(f"DEBUG: Project Root Dir (from config.py): {settings.PROJECT_ROOT_DIR}")
print(f"DEBUG: Temp Files Dir (from config.py): {settings.TEMP_FILES_DIR}")
print(f"DEBUG: Output Files Dir (from config.py): {settings.OUTPUT_FILES_DIR}") # Added debug print for output dir
if settings.ZHIPU_API_KEY:
    print(f"DEBUG: ZHIPU_API_KEY is loaded. Value (first 5 chars): {settings.ZHIPU_API_KEY[:5]}")
else:
    print("DEBUG: ZHIPU_API_KEY is NOT loaded from .env or not set.") 