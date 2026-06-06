"""
Core AI Service.

Handles chat history (Redis) and OpenAI API interaction with strict user isolation.
"""

import json
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
import os

from core.config import get_settings
from cache.redis_client import cache_get, cache_set, make_key
from core.constants import RedisKeys
from services.ai_tools import TOOLS, TOOL_REGISTRY

# We initialize the client dynamically to ensure it picks up changes
def get_ai_client() -> Optional[AsyncOpenAI]:
    settings = get_settings()
    # Read from .env manually if settings doesn't pick it up yet without a reload
    api_key = settings.ai_api_key or os.environ.get("AI_API_KEY")
    base_url = settings.ai_base_url or os.environ.get("AI_BASE_URL")
    
    if api_key:
        return AsyncOpenAI(
            base_url=base_url if base_url else None,
            api_key=api_key
        )
    return None

async def _get_chat_history(user_id: int) -> List[Dict[str, Any]]:
    key = make_key(RedisKeys.AI_CHAT_HISTORY, user_id=user_id)
    history = await cache_get(key)
    if not history:
        return []
    
    cleaned_history = []
    for msg in history:
        if msg.get("role") == "tool":
            continue
        if msg.get("tool_calls"):
            continue
        cleaned_history.append(msg)
        
    return cleaned_history

async def _save_chat_history(user_id: int, history: List[Dict[str, Any]]) -> None:
    # Filter out intermediate tool calls to save tokens and prevent API errors
    cleaned_history = []
    for msg in history:
        if msg.get("role") == "tool":
            continue
        if msg.get("tool_calls"):
            continue
        cleaned_history.append(msg)

    key = make_key(RedisKeys.AI_CHAT_HISTORY, user_id=user_id)
    # Keep only last 20 messages to save context limit
    if len(cleaned_history) > 20:
        # Keep system prompt if present
        if cleaned_history[0]["role"] == "system":
            cleaned_history = [cleaned_history[0]] + cleaned_history[-19:]
        else:
            cleaned_history = cleaned_history[-20:]
    await cache_set(key, cleaned_history, ttl=86400 * 7) # expire in 7 days

async def chat_with_ai(user_id: int, user_message: str) -> str:
    """
    Main entry point for AI chat.
    Returns the AI's natural language response, OR a JSON string if an action is proposed.
    """
    client = get_ai_client()
    if not client:
        return "❌ AI is not configured. Please add AI_API_KEY to your .env file."
        
    history = await _get_chat_history(user_id)
    
    # System prompt - always ensure the latest agent.md is used
    system_content = "You are the Lucid Ads Personal AI Assistant."
    try:
        with open("agent.md", "r", encoding="utf-8") as f:
            system_content = f.read()
    except Exception:
        pass
        
    if not history:
        history.append({"role": "system", "content": system_content})
    elif history[0]["role"] == "system":
        history[0]["content"] = system_content
    else:
        history.insert(0, {"role": "system", "content": system_content})
        
    history.append({"role": "user", "content": user_message})
    
    try:
        MAX_TURNS = 5
        for _ in range(MAX_TURNS):
            response = await client.chat.completions.create(
                model="deepseek-v4-flash-free",
                messages=history,
                tools=TOOLS,
                tool_choice="auto"
            )
            
            message = response.choices[0].message
            
            # Create a safe assistant dictionary preserving reasoning_content if present
            assistant_dict = {"role": "assistant", "content": message.content}
            reasoning = getattr(message, "reasoning_content", None)
            if not reasoning and hasattr(message, "model_extra") and message.model_extra:
                reasoning = message.model_extra.get("reasoning_content")
            if reasoning:
                assistant_dict["reasoning_content"] = reasoning

            # --- DSML Fallback Parser ---
            # Some endpoints leak DeepSeek's internal XML tool format instead of native JSON.
            parsed_tool_calls = message.tool_calls or []
            if not parsed_tool_calls and message.content and "DSML" in message.content and "invoke name" in message.content:
                try:
                    import uuid
                    parts = message.content.split('<| |DSML| |invoke name="')
                    if len(parts) > 1:
                        func_name = parts[1].split('">')[0].strip()
                        args = {}
                        for param_part in parts[2:]:
                            param_name = param_part.split('">')[0].strip()
                            param_value = param_part.split('">')[1].split('<')[0].strip()
                            args[param_name] = param_value
                        
                        class MockFunction:
                            def __init__(self, name, arguments):
                                self.name = name
                                self.arguments = arguments
                        class MockToolCall:
                            def __init__(self, id, function):
                                self.id = id
                                self.type = "function"
                                self.function = function
                                
                        tc = MockToolCall(
                            id=f"call_{uuid.uuid4().hex[:8]}",
                            function=MockFunction(name=func_name, arguments=json.dumps(args))
                        )
                        parsed_tool_calls.append(tc)
                        assistant_dict["content"] = None # Treat as pure tool call
                except Exception:
                    pass
            # ----------------------------

            if not parsed_tool_calls:
                # No more tool calls, this is the final message!
                history.append(assistant_dict)
                await _save_chat_history(user_id, history)
                return message.content or "Done."

            # We have tool calls
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments
                    }
                } for tc in parsed_tool_calls
            ]
            history.append(assistant_dict)
            
            # Execute tools
            for tool_call in parsed_tool_calls:
                func_name = tool_call.function.name
                try:
                    func_args = json.loads(tool_call.function.arguments)
                except Exception:
                    func_args = {}
                
                if func_name in TOOL_REGISTRY:
                    # Execute tool securely
                    tool_result = await TOOL_REGISTRY[func_name](user_id, func_args)
                        
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": str(tool_result)
                    })
                else:
                    history.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": "Error: Tool not found."
                    })
            
            # Loop will continue and ask LLM what to do with the tool result

        # Exceeded max turns
        await _save_chat_history(user_id, history)
        return "⚠️ AI Error: Too many nested tool calls."
        
    except Exception as e:
        return f"⚠️ AI Error: {str(e)}"
