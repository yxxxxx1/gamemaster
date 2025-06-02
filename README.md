# AI Game Localization File Translation Tool

This project is an AI-powered tool to assist with the translation of game localization files (Excel format).

## Features

* Excel file upload
* Tag and symbol protection during translation
* AI model translation (default: Zhipu AI Batch API)
* Customizable tag patterns
* Chunk-based text processing with configurable chunk size
* Real-time translation progress monitoring
* Background task processing with status updates
* Comprehensive error handling and logging

## Version History

### v1.1 (Current)
* Implemented chunk-based text processing mechanism
* Added support for customizable chunk size via `texts_per_chunk` parameter
* Optimized Zhipu API integration with improved batch processing
* Enhanced error handling and logging
* Added detailed progress tracking for translation tasks
* Improved status monitoring with background polling

### v1.0
* Initial release with basic translation functionality
* Support for Excel file processing
* Integration with Zhipu AI translation service
* Basic tag protection mechanism

## Setup and Installation

1. Clone the repository:
```bash
git clone https://github.com/yxxxxx1/gamemaster.git
cd gamemaster
```

2. Install dependencies:
```bash
# Using PDM
pdm install

# Or using pip
pip install -r requirements.txt
```

3. Run the development server:
```bash
uvicorn app.main:app --reload
```

## API Documentation

Once the server is running, API documentation will be available at:
* Swagger UI: `/api/v1/docs`
* ReDoc UI: `/api/v1/redoc`

## Key Features in Detail

### Chunk Processing
The system now supports processing large text files by breaking them into manageable chunks:
* Configurable chunk size via `texts_per_chunk` parameter
* Default chunk size: 10 texts
* Automatic chunk management and result aggregation
* Progress tracking for each chunk

### Translation Process
1. Upload Excel file
2. Configure translation parameters:
   * Source and target languages
   * Column specifications
   * Chunk size (optional)
   * Tag patterns (optional)
3. Start translation
4. Monitor progress in real-time
5. Download translated file when complete

### Error Handling
* Comprehensive error logging
* Detailed status updates
* Graceful failure handling
* Automatic retry mechanisms for API calls

## Contributing

Feel free to submit issues and enhancement requests!

## License

This project is licensed under the MIT License - see the LICENSE file for details. 