# AI Game Localization File Translation Tool

This project is an AI-powered tool to assist with the translation of game localization files (Excel format).

## Features

- Excel file upload
- Tag and symbol protection during translation
- AI model translation (default: Zhipu AI Batch API)
- Customizable tag patterns
- ... (more features to be added)

## Setup and Installation

(Instructions to be added - e.g., using PDM or pip)

1.  Clone the repository.
2.  Install dependencies: `pdm install` (if using PDM) or `pip install -r requirements.txt`
3.  Run the development server: `pdm run uvicorn app.main:app --reload` or `uvicorn app.main:app --reload`

## API Documentation

Once the server is running, API documentation will be available at `/docs` (Swagger UI) or `/redoc` (ReDoc UI) relative to the API V1 prefix (e.g. `/api/v1/docs`). 