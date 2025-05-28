from typing import List

from fastapi import APIRouter

from app.models import (
    DefaultTagPattern,
    DefaultTagPatternsResponse,
    SupportedLanguage,
    SupportedLanguagesResponse,
)
from app.core.config import settings # To potentially get language lists if defined there

router = APIRouter()

# In a real application, these might come from a configuration file, a database,
# or be dynamically generated based on available translation models/services.

SUPPORTED_SOURCE_LANGUAGES = [
    SupportedLanguage(code="en", name="English"),
    SupportedLanguage(code="zh", name="Chinese"),
    SupportedLanguage(code="ja", name="Japanese"),
    SupportedLanguage(code="ko", name="Korean"),
    SupportedLanguage(code="de", name="German"),
    SupportedLanguage(code="fr", name="French"),
    # Add more as needed
]

SUPPORTED_TARGET_LANGUAGES = [
    SupportedLanguage(code="en", name="English"),
    SupportedLanguage(code="zh", name="Chinese"),
    SupportedLanguage(code="ja", name="Japanese"),
    SupportedLanguage(code="ko", name="Korean"),
    SupportedLanguage(code="de", name="German"),
    SupportedLanguage(code="fr", name="French"),
    # Add more as needed
]

DEFAULT_TAG_REGEX_PATTERNS = [
    DefaultTagPattern(
        name="Brace Variables",
        regex=r"{\$.*?}",
        description="Matches variables enclosed in curly braces, like {$playerName}."
    ),
    DefaultTagPattern(
        name="HTML-like Tags",
        regex=r"<[^>]+>",
        description="Matches general HTML-like tags, like <B> or <color=red>."
    ),
    DefaultTagPattern(
        name="Unity Rich Text Tags",
        regex=r"<\/?(b|i|size|color|material|quad|sprite|link|nobr|page|indent|align|mark|mspace|width|style|gradient|cspace|font|voffset|line-height|pos|space|noparse|uppercase|lowercase|smallcaps|sup|sub)(=[^>]*)?>",
        description="Matches common Unity rich text tags like <b>, <i>, <color=red>, <size=20>."
    ),
    DefaultTagPattern(
        name="Percentage Variables",
        regex=r"%%.*?%%",
        description="Matches variables enclosed in double percentage signs, like %%token%%."
    ),
    DefaultTagPattern(
        name="String Format Specifiers (Python-style)",
        regex=r"%[\d\.]*[sdfeEgGxXoc]",
        description="Matches Python-style string format specifiers like %s, %d, %.2f."
    ),
]


@router.get(
    "/languages",
    response_model=SupportedLanguagesResponse,
    summary="Get Supported Languages",
    description="Retrieves a list of supported source and target languages for translation.",
)
async def get_supported_languages():
    """
    Provides lists of languages that the service can translate from (source)
    and to (target).
    """
    return SupportedLanguagesResponse(
        source_languages=SUPPORTED_SOURCE_LANGUAGES,
        target_languages=SUPPORTED_TARGET_LANGUAGES,
    )


@router.get(
    "/tag-patterns",
    response_model=DefaultTagPatternsResponse,
    summary="Get Default Tag Regex Patterns",
    description="Retrieves a list of recommended default regular expression patterns for tag protection.",
)
async def get_default_tag_patterns():
    """
    Provides a list of default regular expressions that can be used to identify
    and protect common placeholder tags found in game localization files.
    """
    return DefaultTagPatternsResponse(patterns=DEFAULT_TAG_REGEX_PATTERNS) 