from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn # For direct run option

# Import settings first to ensure TEMP_FILES_DIR is created if needed
from .core.config import settings
# Import routers later when they are defined
from .routers import files as files_router # Changed to import the module
from .routers import jobs as jobs_router # Added import for jobs_router
from .routers import config_api as config_router # Corrected import to use config_api
# from .routers import config_api_router
# from .models import ErrorResponse # For custom error responses if needed

# Lifespan events for startup and shutdown
@asynccontextmanager
async def lifespan(current_app: FastAPI):
    print(f"Starting up application: {settings.APP_NAME}...")
    # Perform any startup activities here
    # e.g., connecting to database, loading configurations, ensuring temp_files dir exists
    # The directory creation is now handled in settings itself upon instantiation.
    yield
    print(f"Shutting down application: {settings.APP_NAME}...")
    # Perform any shutdown activities here

app = FastAPI(
    title=settings.APP_NAME,
    description="API for translating game localization Excel files using AI, with tag protection.",
    version="0.1.0", # You can make this dynamic from settings too
    lifespan=lifespan,
    openapi_url=f"{settings.API_V1_STR}/openapi.json", # Standard OpenAPI path
    docs_url=f"{settings.API_V1_STR}/docs", # Swagger UI
    redoc_url=f"{settings.API_V1_STR}/redoc" # ReDoc UI
)

# Placeholder for health check or root endpoint
@app.get("/", tags=["Health Check"], summary="Root endpoint for health check.")
async def read_root():
    """
    Simple health check endpoint.
    Returns a welcome message indicating the API is running.
    """
    return {"message": f"Welcome to the {settings.APP_NAME} API!"}

# --- Include routers (to be implemented and uncommented later) ---
# from .routers.files import router as files_router
# from .routers.jobs import router as jobs_router
# from .routers.config import router as config_api_router

app.include_router(files_router.router, prefix=f"{settings.API_V1_STR}/files", tags=["File Operations"])
app.include_router(jobs_router.router, prefix=f"{settings.API_V1_STR}/translation-jobs", tags=["Translation Jobs"])
app.include_router(config_router.router, prefix=settings.API_V1_STR + "/config", tags=["Configuration"])


# --- CORS Middleware (Uncomment and configure if needed for your frontend) ---
# from fastapi.middleware.cors import CORSMiddleware
# origins = [
#     "http://localhost",          # Example: Local development (React default)
#     "http://localhost:8080",     # Example: Local development (Vue default)
#     "http://localhost:5173",     # Example: Local development (Vite default)
#     # Add your frontend production domain(s) here
# ]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"], # Allows all methods
#     allow_headers=["*"], # Allows all headers
# )

# This part is for easily running the app with `python -m app.main` for development from project root
# Or `python main.py` if you are inside the app directory.
# For production, you'd typically use: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
if __name__ == "__main__":
    # This allows running `python app/main.py` from project root
    # For `uvicorn app.main:app --reload` to work correctly, this __main__ block is not strictly necessary for uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, app_dir="app")

@app.get("/health", tags=["Health Check"])
async def health_check():
    return {"status": "ok"} 