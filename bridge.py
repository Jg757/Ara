import asyncio
import websockets
import json
import os
import ssl
import httpx
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("XAI_API_KEY")
XAI_URL = "wss://api.x.ai/v1/realtime"
XAI_CHAT_URL = "https://api.x.ai/v1/chat/completions"

# Setup SSL context for xAI (unverified as requested/working)
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Vision processing via xAI Chat API
async def process_image_vision(image_data_url: str, prompt: str = "Describe what you see in this image in detail.") -> str:
    """Send image to xAI Vision API and get text description"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                XAI_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "grok-2-vision-latest",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}},
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ],
                    "max_tokens": 1000
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                description = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                print(f"[Vision] Got description: {description[:100]}...")
                return description
            else:
                print(f"[Vision] API error: {response.status_code} - {response.text}")
                return f"Error analyzing image: {response.status_code}"
    except Exception as e:
        print(f"[Vision] Error: {e}")
        return f"Error processing image: {str(e)}"

async def proxy_handler(client_ws):
    print("Browser connected.")
    headers = {"Authorization": f"Bearer {API_KEY}"}
    
    try:
        # Connect to xAI
        async with websockets.connect(XAI_URL, additional_headers=headers, ssl=ssl_context) as xai_ws:
            print("Connected to xAI.")
            
            # Send initial config
            # Load instructions from persona.txt
            try:
                with open("persona.txt", "r") as f:
                    persona_instructions = f.read().strip()
            except Exception as e:
                print(f"Warning: Could not load persona.txt: {e}")
                persona_instructions = "You are a helpful voice assistant."

            # Load Memory (to inject as conversation context, not instructions)
            try:
                from memory import MemoryManager
                memory_context = MemoryManager.load_memory()
                print(f"Loaded memory: {len(memory_context)} chars")
            except Exception as e:
                print(f"Warning: Could not load memory: {e}")
                memory_context = ""

            # Combine persona + memory (original working approach)
            full_instructions = f"{persona_instructions}\n\n{memory_context}"
            print(f"Persona: {len(persona_instructions)} chars, Memory: {len(memory_context)} chars")
            print(f"Total instructions: {len(full_instructions)} chars")

            config = {
                "type": "session.update",
                "session": {
                    "voice": "Ara",
                    "modalities": ["audio", "text"],
                    "instructions": full_instructions,
                    "input_audio_transcription": {"model": "whisper-1"},
                    "turn_detection": None,  # Disabled - client controls commit via push-to-talk
                    "tools": [
                        {"type": "web_search"},
                        {"type": "x_search"}
                    ]
                }
            }
            await xai_ws.send(json.dumps(config))

            # Task 1: Browser -> xAI (with memory preloading)
            async def browser_to_xai():
                async for message in client_ws:
                    # Parse message to check if it's a text message that needs memory context
                    try:
                        data = json.loads(message)
                        msg_type = data.get('type', '')
                        
                        # If user sends a text message, search for relevant memories
                        if msg_type == 'conversation.item.create':
                            item = data.get('item', {})
                            if item.get('type') == 'message' and item.get('role') == 'user':
                                content = item.get('content', [])
                                for c in content:
                                    if c.get('type') == 'input_text':
                                        user_text = c.get('text', '')
                                        if user_text:
                                            # Search vector memory for relevant context
                                            try:
                                                from vector_memory import search_memories
                                                relevant = search_memories(user_text, n_results=5)
                                                if relevant and len(relevant) > 50:
                                                    # Inject relevant memories as context
                                                    context_item = {
                                                        "type": "conversation.item.create",
                                                        "item": {
                                                            "type": "message",
                                                            "role": "system",
                                                            "content": [{
                                                                "type": "input_text",
                                                                "text": f"[Relevant context from past conversations]{relevant}"
                                                            }]
                                                        }
                                                    }
                                                    await xai_ws.send(json.dumps(context_item))
                                                    print(f"[Memory] Injected {len(relevant)} chars of context")
                                            except Exception as e:
                                                print(f"[Memory] Search error: {e}")
                                                
                                    # Check for image content that needs vision processing
                                    if c.get('type') == 'image_url':
                                        image_url = c.get('image_url', {}).get('url', '')
                                        if image_url.startswith('data:image'):
                                            print(f"[Vision] Processing image...")
                                            # Get vision description
                                            description = await process_image_vision(image_url)
                                            
                                            # Replace image with text description
                                            c['type'] = 'input_text'
                                            c['text'] = f"[I'm showing you an image. Here's what I see: {description}. Please respond to this image.]"
                                            del c['image_url']
                                            
                                            # Update the message with modified content
                                            message = json.dumps(data)
                                            print(f"[Vision] Converted image to text description")
                    except Exception as e:
                        print(f"[Bridge] Parse error: {e}")  # Not JSON or parse error, just forward
                    
                    # Forward original message (or modified if vision processed)
                    await xai_ws.send(message)

            # Task 2: xAI -> Browser (with memory saving)
            async def xai_to_browser():
                async for message in xai_ws:
                    # Forward message to browser
                    await client_ws.send(message)
                    
                    # Parse and save transcripts to memory
                    try:
                        data = json.loads(message)
                        msg_type = data.get('type', '')
                        
                        # Save user's speech transcription
                        if msg_type == 'conversation.item.input_audio_transcription.completed':
                            transcript = data.get('transcript', '')
                            if transcript and transcript.strip():
                                MemoryManager.save_turn('user', transcript.strip())
                                # Also add to vector memory
                                try:
                                    from vector_memory import add_memory
                                    add_memory('user', transcript.strip())
                                except:
                                    pass
                                print(f"Saved user: {transcript[:50]}...")
                        
                        # Save Ara's text response
                        elif msg_type == 'response.audio_transcript.done':
                            transcript = data.get('transcript', '')
                            if transcript and transcript.strip():
                                MemoryManager.save_turn('assistant', transcript.strip())
                                # Also add to vector memory
                                try:
                                    from vector_memory import add_memory
                                    add_memory('assistant', transcript.strip())
                                except:
                                    pass
                                print(f"Saved Ara: {transcript[:50]}...")
                                
                    except Exception as e:
                        pass  # Don't break on parse errors

            # Run both
            await asyncio.gather(browser_to_xai(), xai_to_browser())

    except Exception as e:
        print(f"Bridge connection error: {e}")
        try:
             await client_ws.close()
        except:
            pass
    print("Disconnecting.")

async def main():
    print("Starting Bridge on ws://localhost:8765")
    async with websockets.serve(proxy_handler, "localhost", 8765):
        await asyncio.get_running_loop().create_future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping bridge.")
