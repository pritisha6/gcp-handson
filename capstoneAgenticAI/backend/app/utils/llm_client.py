"""Thin adapter over Groq's OpenAI-compatible chat completions API for forced
structured tool-use.

Shared by every service that asks the LLM for JSON-shaped output
(``RequirementExtractor``, ``ConflictResolver``, ``ThoughtGenerator``,
``HallucinationDetector``) so the request/response shape differences from
Anthropic's Messages API (which this project used before switching to Groq)
are handled in exactly one place:

- ``system`` is a message in the ``messages`` list, not a separate top-level param.
- A tool is described as ``{"type": "function", "function": {...}}``, and the
  existing Anthropic-style ``input_schema`` maps directly onto ``parameters``.
- ``tool_choice`` is ``{"type": "function", "function": {"name": ...}}``.
- The model's tool-call arguments come back as a **JSON string**
  (``choices[0].message.tool_calls[0].function.arguments``), not an
  already-parsed dict like Anthropic returns.
- Token usage fields are ``prompt_tokens``/``completion_tokens``, not
  ``input_tokens``/``output_tokens``.

Each calling service still owns its own retry decorator, exception
translation, and cost tracking; this module only adapts the wire format.
"""
import json
from typing import Any, Dict, Optional

from openai import OpenAI

from app.config import Settings, get_settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def get_llm_client(settings: Optional[Settings] = None) -> OpenAI:
    """Return an OpenAI-SDK client pointed at Groq's OpenAI-compatible endpoint."""
    settings = settings or get_settings()
    return OpenAI(api_key=settings.GROQ_API_KEY, base_url=GROQ_BASE_URL)


class ToolCallResult:
    """The parsed result of a forced tool call."""

    def __init__(self, arguments: Dict[str, Any], input_tokens: int, output_tokens: int) -> None:
        self.arguments = arguments
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def call_tool(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_content: str,
    tool_name: str,
    tool_description: str,
    input_schema: Dict[str, Any],
    max_tokens: int = 4096,
    temperature: float = 0.0,
) -> ToolCallResult:
    """Call the model, forcing it to respond via exactly one named tool.

    Args:
        client: A client from ``get_llm_client``.
        model: Groq model id.
        system_prompt: System instructions.
        user_content: The user-turn content (often a JSON-serialized payload).
        tool_name: The tool the model must call.
        tool_description: Shown to the model to explain the tool's purpose.
        input_schema: JSON Schema for the tool's arguments (the same shape
            used for Anthropic's ``input_schema`` maps directly to OpenAI's
            ``parameters``).
        max_tokens: Response token cap.
        temperature: Sampling temperature (0 for the closest thing to
            deterministic output this API offers).

    Returns:
        The parsed tool-call arguments plus token usage.

    Raises:
        ValueError: If the model didn't call the requested tool.
    """
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": input_schema,
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": tool_name}},
    )

    usage = response.usage
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

    message = response.choices[0].message
    tool_calls = message.tool_calls or []
    matching_call = next((tc for tc in tool_calls if tc.function.name == tool_name), None)
    if matching_call is None:
        raise ValueError(f"Model did not call the '{tool_name}' tool.")

    arguments = json.loads(matching_call.function.arguments)
    return ToolCallResult(arguments=arguments, input_tokens=input_tokens, output_tokens=output_tokens)
