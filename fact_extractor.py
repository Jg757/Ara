import os
import json
import httpx
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("XAI_API_KEY")
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"

SYSTEM_PROMPT = """
You are a highly analytical AI core fact extractor for an assistant named Ara.
Your job is to read a transcript of a recent conversation between Ara and the User, and extract any concrete facts about the User.

A "fact" is a piece of information that is semi-permanent and useful to know for future conversations (e.g. name, preferences, family members, location, pets, car they drive, habits).
Do NOT extract transient information (e.g. "User is testing an app right now", "User just woke up", "User is having a good day").
Do NOT extract conversational filler or thoughts.
Do NOT hallucinate. Only extract what is explicitly stated by the user.

First, analyze the transcript. Then, output your findings in strict JSON format.

Example format:
{
    "new_facts": [
        {"subject": "User", "attribute": "favorite color", "value": "blue"},
        {"subject": "User", "attribute": "sibling name", "value": "John"}
    ]
}

CRITICAL INSTRUCTION: The above JSON is just an example of the structure. DO NOT output "blue" or "John" unless the user explicitly mentions them. Return an empty array if no new concrete facts are discussed.

If no new facts are found, return exactly:
{
    "new_facts": []
}

Output ONLY valid JSON. No markdown formatting or extra text.
"""

async def extract_facts(conversation_history: str) -> Dict[str, Any]:
    """
    Sends a chunk of conversation to the LLM to extract long-term facts.
    Returns a dictionary parsed from the LLM's JSON output.
    """
    if not API_KEY:
        print("[FactExtractor] Error: XAI_API_KEY not found in environment.")
        return {"new_facts": []}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                XAI_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-3",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f"Transcript:\n\n{conversation_history}"}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
            )

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                try:
                    result = json.loads(content)
                    return result
                except json.JSONDecodeError:
                    print(f"[FactExtractor] Error: Could not parse JSON from response:\n{content}")
                    return {"new_facts": []}
            else:
                print(f"[FactExtractor] API error: {response.status_code} - {response.text}")
                return {"new_facts": []}
    except Exception as e:
        print(f"[FactExtractor] Connection error: {e}")
        return {"new_facts": []}
