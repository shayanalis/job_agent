"""Lightweight LLM service for initial job screening."""

import logging
from typing import Dict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_openai import ChatOpenAI

from config.settings import OPENAI_API_KEY, SCREENING_MODEL, LLM_TEMPERATURE
from src.agents.state import ScreeningResult
from src.prompts.prompt_templates import (
    SCREENING_SYSTEM_PROMPT,
    SCREENING_USER_PROMPT,
)

logger = logging.getLogger(__name__)


class ScreeningService:
    """Wrapper around a lightweight model to pre-screen job postings."""

    def __init__(self) -> None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not found in environment variables")

        # Prefer deterministic behaviour for screening, while respecting model constraints.
        default_temp_models = (
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-preview",
            "gpt-4.1",
            "gpt-4.1-mini",
        )

        requires_default_temp = any(
            SCREENING_MODEL.startswith(prefix) for prefix in default_temp_models
        )

        if requires_default_temp:
            temperature = 1.0
            logger.info(
                "Model %s requires default temperature=1.0; overriding deterministic setting",
                SCREENING_MODEL,
            )
        else:
            temperature = 0.0 if LLM_TEMPERATURE is None else LLM_TEMPERATURE

        self.client = ChatOpenAI(
            model=SCREENING_MODEL,
            temperature=temperature,
            api_key=OPENAI_API_KEY,
        )

        logger.info(
            "ScreeningService initialized with %s (temperature=%s)",
            SCREENING_MODEL,
            temperature,
        )

    def screen_job_posting(
        self, job_content: str, provided_metadata: Dict
    ) -> ScreeningResult:
        """Run the screening model on raw job posting content.

        Args:
            job_content: Raw job description or full posting content.
            provided_metadata: Metadata supplied by the extension (title, company, url, etc.).

        Returns:
            Parsed ScreeningResult object.
        """
        system_prompt = SCREENING_SYSTEM_PROMPT.format()

        user_prompt = SCREENING_USER_PROMPT.format(
            job_title=provided_metadata.get("title", "Not Specified"),
            company=provided_metadata.get("company", "Not Specified"),
            job_url=provided_metadata.get("job_url", provided_metadata.get("url", "")),
            job_content=job_content,
        )

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]

        try:
            response = self.client.invoke(messages)
            parser = JsonOutputParser(pydantic_object=ScreeningResult)
            result = parser.parse(response.content)
            screening = ScreeningResult(**result)

            logger.info(
                "Screening completed: block=%s, sponsorship=%s, questions=%d",
                screening.block_application,
                screening.sponsorship_status,
                len(screening.application_questions),
            )
            return screening
        except Exception as error:
            logger.error("Error during screening: %s", error)
            raise ValueError(f"Screening failed: {str(error)}")

