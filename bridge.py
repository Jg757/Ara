import asyncio
import websockets
import json
import os
import ssl
from datetime import datetime
from zoneinfo import ZoneInfo
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

# Pending Google data to inject after response.done
# Format: {"type": "emails"|"calendar"|"files", "data": [...]}
pending_google_data = None

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
                profile_context = MemoryManager.load_user_profile()
                print(f"Loaded memory: {len(memory_context)} chars, profile: {len(profile_context)} chars")
            except Exception as e:
                print(f"Warning: Could not load memory: {e}")
                memory_context = ""
                profile_context = ""

            # Inject current date/time and elapsed time since last contact
            now = datetime.now(ZoneInfo("America/New_York"))
            time_context = f"\n\n[CURRENT TIME]\nRight now it is {now.strftime('%A, %B %d, %Y at %I:%M %p')} (Eastern Time).\n"

            # Calculate how long since Will last talked to you
            try:
                last_time_str = MemoryManager.get_last_interaction_time()
                if last_time_str:
                    last_time = datetime.fromisoformat(last_time_str)
                    elapsed = now - last_time
                    total_seconds = int(elapsed.total_seconds())
                    
                    if total_seconds < 120:
                        elapsed_desc = "just moments ago"
                    elif total_seconds < 3600:
                        mins = total_seconds // 60
                        elapsed_desc = f"about {mins} minutes ago"
                    elif total_seconds < 86400:
                        hours = total_seconds // 3600
                        elapsed_desc = f"about {hours} hour{'s' if hours != 1 else ''} ago"
                    elif total_seconds < 604800:
                        days = total_seconds // 86400
                        elapsed_desc = f"{days} day{'s' if days != 1 else ''} ago"
                    else:
                        weeks = total_seconds // 604800
                        days = (total_seconds % 604800) // 86400
                        if days > 0:
                            elapsed_desc = f"{weeks} week{'s' if weeks != 1 else ''} and {days} day{'s' if days != 1 else ''} ago"
                        else:
                            elapsed_desc = f"{weeks} week{'s' if weeks != 1 else ''} ago"
                    
                    time_context += f"Will last spoke to you {elapsed_desc} (on {last_time.strftime('%A, %B %d at %I:%M %p')}).\n"
                    print(f"[Time] Last contact: {elapsed_desc}")
            except Exception as e:
                print(f"[Time] Could not calculate elapsed time: {e}")

            # Combine persona + profile + time + memory
            full_instructions = f"{persona_instructions}{profile_context}{time_context}{memory_context}"
            print(f"Persona+Profile: {len(persona_instructions)+len(profile_context)} chars, Memory: {len(memory_context)} chars")
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
                        {"type": "x_search"},
                        {
                            "type": "function",
                            "function": {
                                "name": "retrieve_email",
                                "description": "Retrieve email data from Will's Gmail account using pre-authorized access. Use this when Will asks about his emails, inbox, or messages.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Optional search query for emails (e.g., subject or sender). Leave empty for recent emails."},
                                        "max_results": {"type": "integer", "description": "Maximum number of emails to return.", "default": 5}
                                    },
                                    "required": []
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "retrieve_calendar",
                                "description": "Retrieve calendar events from Will's Google Calendar using pre-authorized access. Use this when Will asks about his schedule, calendar, or upcoming events.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "max_results": {"type": "integer", "description": "Maximum number of events to return.", "default": 5}
                                    },
                                    "required": []
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "retrieve_files",
                                "description": "Retrieve file list from Will's Google Drive using pre-authorized access. Use this when Will asks about his files, documents, or drive.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Optional search query for files."},
                                        "max_results": {"type": "integer", "description": "Maximum number of files to return.", "default": 10}
                                    },
                                    "required": []
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "read_file_content",
                                "description": "Read the actual content of a specific file from Will's Google Drive. Use this when Will asks to read, open, or see the content of a specific file. First use retrieve_files to find the file, then use this to read it.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "file_name": {"type": "string", "description": "The name of the file to read (from the file list)."},
                                        "file_id": {"type": "string", "description": "The ID of the file to read (from the file list)."}
                                    },
                                    "required": []
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "create_calendar_event",
                                "description": "Create a new event on Will's Google Calendar. Use this when Will asks to schedule, add, or create a meeting, appointment, or event.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "summary": {"type": "string", "description": "Title/name of the event."},
                                        "start_time": {"type": "string", "description": "Start time in ISO format (e.g., '2024-12-22T15:00:00')."},
                                        "end_time": {"type": "string", "description": "End time in ISO format (e.g., '2024-12-22T16:00:00')."},
                                        "description": {"type": "string", "description": "Optional description or notes."},
                                        "location": {"type": "string", "description": "Optional location."}
                                    },
                                    "required": ["summary", "start_time", "end_time"]
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "send_email",
                                "description": "Send an email from Will's Gmail account. Use this when Will asks to send, compose, or email someone.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "to": {"type": "string", "description": "Recipient email address."},
                                        "subject": {"type": "string", "description": "Email subject line."},
                                        "body": {"type": "string", "description": "Email body content."}
                                    },
                                    "required": ["to", "subject", "body"]
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "write_to_sheet",
                                "description": "Write or append data to a Google Sheet. Use this when Will asks to add data, update a spreadsheet, or log information.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "spreadsheet_name": {"type": "string", "description": "Name of the spreadsheet to write to."},
                                        "spreadsheet_id": {"type": "string", "description": "ID of the spreadsheet (if known)."},
                                        "data": {"type": "array", "description": "Data to write as rows (array of arrays).", "items": {"type": "array", "items": {"type": "string"}}},
                                        "append": {"type": "boolean", "description": "If true, append to existing data. If false, overwrite.", "default": True}
                                    },
                                    "required": ["data"]
                                }
                            }
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "retrieve_contacts",
                                "description": "Retrieve contacts from Will's Google Contacts. Use this when Will asks about his contacts, phone numbers, or wants to find someone's contact information.",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "query": {"type": "string", "description": "Optional search query to find a specific contact by name."},
                                        "max_results": {"type": "integer", "description": "Maximum number of contacts to return.", "default": 10}
                                    },
                                    "required": []
                                }
                            }
                        }
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
                        
                        # Handle knowledge base commands
                        if msg_type == 'kb.store':
                            # Store document in knowledge base
                            doc_name = data.get('name', 'Untitled')
                            doc_content = data.get('content', '')
                            doc_type = data.get('doc_type', 'text')
                            try:
                                from knowledge_base import add_document
                                chunks = add_document(doc_name, doc_content, doc_type)
                                # Send confirmation back to browser
                                await client_ws.send(json.dumps({
                                    "type": "kb.stored",
                                    "name": doc_name,
                                    "chunks": chunks
                                }))
                                print(f"[KnowledgeBase] Stored '{doc_name}' ({chunks} chunks)")
                            except Exception as e:
                                print(f"[KnowledgeBase] Store error: {e}")
                                await client_ws.send(json.dumps({
                                    "type": "kb.error",
                                    "error": str(e)
                                }))
                            continue  # Don't forward to xAI
                        
                        elif msg_type == 'kb.list':
                            # List all stored documents
                            try:
                                from knowledge_base import list_documents
                                docs = list_documents()
                                await client_ws.send(json.dumps({
                                    "type": "kb.documents",
                                    "documents": docs
                                }))
                            except Exception as e:
                                print(f"[KnowledgeBase] List error: {e}")
                            continue  # Don't forward to xAI
                        
                        elif msg_type == 'kb.delete':
                            # Delete a document
                            doc_name = data.get('name', '')
                            try:
                                from knowledge_base import delete_document
                                count = delete_document(doc_name)
                                await client_ws.send(json.dumps({
                                    "type": "kb.deleted",
                                    "name": doc_name,
                                    "chunks": count
                                }))
                            except Exception as e:
                                print(f"[KnowledgeBase] Delete error: {e}")
                            continue  # Don't forward to xAI
                        
                        # ============ GOOGLE SERVICE HANDLERS ============
                        
                        elif msg_type == 'google.emails':
                            # Get recent emails
                            max_results = data.get('max_results', 10)
                            query = data.get('query', None)
                            try:
                                from google_services import get_google_services
                                gs = get_google_services()
                                if query:
                                    emails = gs.search_emails(query, max_results)
                                else:
                                    emails = gs.get_recent_emails(max_results)
                                await client_ws.send(json.dumps({
                                    "type": "google.emails.result",
                                    "emails": emails
                                }))
                                print(f"[Google] Retrieved {len(emails)} emails")
                            except Exception as e:
                                print(f"[Google] Email error: {e}")
                                await client_ws.send(json.dumps({
                                    "type": "google.error",
                                    "error": str(e)
                                }))
                            continue
                        
                        elif msg_type == 'google.files':
                            # List or search Google Drive files
                            query = data.get('query', None)
                            max_results = data.get('max_results', 20)
                            try:
                                from google_services import get_google_services
                                gs = get_google_services()
                                if query:
                                    files = gs.search_files(query, max_results)
                                else:
                                    files = gs.list_files(max_results)
                                await client_ws.send(json.dumps({
                                    "type": "google.files.result",
                                    "files": files
                                }))
                                print(f"[Google] Retrieved {len(files)} files")
                            except Exception as e:
                                print(f"[Google] Drive error: {e}")
                                await client_ws.send(json.dumps({
                                    "type": "google.error",
                                    "error": str(e)
                                }))
                            continue
                        
                        elif msg_type == 'google.file.content':
                            # Get content of a specific file
                            file_id = data.get('file_id', '')
                            try:
                                from google_services import get_google_services
                                gs = get_google_services()
                                content = gs.get_file_content(file_id)
                                await client_ws.send(json.dumps({
                                    "type": "google.file.content.result",
                                    "file_id": file_id,
                                    "content": content[:10000]  # Limit to 10k chars
                                }))
                                print(f"[Google] Retrieved file content ({len(content)} chars)")
                            except Exception as e:
                                print(f"[Google] File content error: {e}")
                                await client_ws.send(json.dumps({
                                    "type": "google.error",
                                    "error": str(e)
                                }))
                            continue
                        
                        elif msg_type == 'google.calendar':
                            # Get upcoming calendar events
                            max_results = data.get('max_results', 10)
                            try:
                                from google_services import get_google_services
                                gs = get_google_services()
                                events = gs.get_upcoming_events(max_results)
                                await client_ws.send(json.dumps({
                                    "type": "google.calendar.result",
                                    "events": events
                                }))
                                print(f"[Google] Retrieved {len(events)} calendar events")
                            except Exception as e:
                                print(f"[Google] Calendar error: {e}")
                                await client_ws.send(json.dumps({
                                    "type": "google.error",
                                    "error": str(e)
                                }))
                            continue
                        
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
                                            
                                            # Search knowledge base for relevant documents
                                            try:
                                                from knowledge_base import search_documents
                                                doc_context = search_documents(user_text, n_results=5)
                                                if doc_context and len(doc_context) > 50:
                                                    # Inject document context
                                                    doc_item = {
                                                        "type": "conversation.item.create",
                                                        "item": {
                                                            "type": "message",
                                                            "role": "system",
                                                            "content": [{
                                                                "type": "input_text",
                                                                "text": doc_context
                                                            }]
                                                        }
                                                    }
                                                    await xai_ws.send(json.dumps(doc_item))
                                                    print(f"[KnowledgeBase] Injected {len(doc_context)} chars of document context")
                                            except Exception as e:
                                                print(f"[KnowledgeBase] Search error: {e}")
                                            
                                            # ============ GOOGLE VOICE COMMANDS ============
                                            user_lower = user_text.lower()
                                            
                                            # Check for email commands - look for keywords
                                            email_keywords = ['email', 'gmail', 'inbox']
                                            if any(kw in user_lower for kw in email_keywords):
                                                try:
                                                    from google_services import get_google_services
                                                    gs = get_google_services()
                                                    emails = gs.get_recent_emails(5)
                                                    if emails:
                                                        email_summary = "\n\n[Here are your recent emails:]\n"
                                                        for i, e in enumerate(emails):
                                                            email_summary += f"{i+1}. From: {e['from'][:40]} | Subject: {e['subject'][:50]}...\n"
                                                        email_item = {
                                                            "type": "conversation.item.create",
                                                            "item": {
                                                                "type": "message",
                                                                "role": "system",
                                                                "content": [{"type": "input_text", "text": email_summary}]
                                                            }
                                                        }
                                                        await xai_ws.send(json.dumps(email_item))
                                                        print(f"[Google] Injected {len(emails)} emails as context")
                                                except Exception as e:
                                                    print(f"[Google] Email fetch error: {e}")
                                            
                                            # Check for Drive/files commands
                                            elif any(phrase in user_lower for phrase in ['my files', 'my documents', 'google drive', 'check drive', 'my drive']):
                                                try:
                                                    from google_services import get_google_services
                                                    gs = get_google_services()
                                                    files = gs.list_files(10)
                                                    if files:
                                                        file_summary = "\n\n[Here are your recent Google Drive files:]\n"
                                                        for i, f in enumerate(files):
                                                            file_summary += f"{i+1}. {f['name']}\n"
                                                        file_item = {
                                                            "type": "conversation.item.create",
                                                            "item": {
                                                                "type": "message",
                                                                "role": "system",
                                                                "content": [{"type": "input_text", "text": file_summary}]
                                                            }
                                                        }
                                                        await xai_ws.send(json.dumps(file_item))
                                                        print(f"[Google] Injected {len(files)} files as context")
                                                except Exception as e:
                                                    print(f"[Google] Drive fetch error: {e}")
                                            
                                            # Check for calendar commands
                                            elif any(phrase in user_lower for phrase in ['my calendar', 'calendar', 'my schedule', 'upcoming events', 'my events', "what's on my calendar"]):
                                                try:
                                                    from google_services import get_google_services
                                                    gs = get_google_services()
                                                    events = gs.get_upcoming_events(5)
                                                    if events:
                                                        event_summary = "\n\n[Here are your upcoming calendar events:]\n"
                                                        for i, e in enumerate(events):
                                                            event_summary += f"{i+1}. {e['summary']} - {e['start']}\n"
                                                        event_item = {
                                                            "type": "conversation.item.create",
                                                            "item": {
                                                                "type": "message",
                                                                "role": "system",
                                                                "content": [{"type": "input_text", "text": event_summary}]
                                                            }
                                                        }
                                                        await xai_ws.send(json.dumps(event_item))
                                                        print(f"[Google] Injected {len(events)} calendar events as context")
                                                    else:
                                                        no_events = {
                                                            "type": "conversation.item.create",
                                                            "item": {
                                                                "type": "message",
                                                                "role": "system",
                                                                "content": [{"type": "input_text", "text": "[The user's calendar shows no upcoming events.]"}]
                                                            }
                                                        }
                                                        await xai_ws.send(json.dumps(no_events))
                                                        print("[Google] No calendar events found")
                                                except Exception as e:
                                                    print(f"[Google] Calendar fetch error: {e}")
                                                
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
                global pending_google_data
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
                                # Trigger background fact extraction roughly every 5 messages
                                if not hasattr(client_ws, 'msg_count'):
                                    client_ws.msg_count = 0
                                client_ws.msg_count += 1
                                if client_ws.msg_count % 5 == 0:
                                    asyncio.create_task(run_background_fact_extraction())
                        
                        
                        # ============ HANDLE FUNCTION CALLS FROM ARA ============
                        # When Ara calls retrieve_email, retrieve_calendar, or retrieve_files
                        elif msg_type == 'response.function_call_arguments.done':
                            func_name = data.get('name', '')
                            call_id = data.get('call_id', '')
                            arguments_str = data.get('arguments', '{}')
                            
                            try:
                                arguments = json.loads(arguments_str) if arguments_str else {}
                            except:
                                arguments = {}
                            
                            print(f"[Function Call] {func_name} with args: {arguments}")
                            
                            output_data = None
                            
                            if func_name == 'retrieve_email':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    max_results = arguments.get('max_results', 5)
                                    query = arguments.get('query', None)
                                    
                                    if query:
                                        emails = gs.search_emails(query, max_results)
                                    else:
                                        emails = gs.get_recent_emails(max_results)
                                    
                                    # Format nicely for Ara
                                    email_list = []
                                    for e in emails:
                                        email_list.append({
                                            "from": e.get('from', 'Unknown'),
                                            "subject": e.get('subject', 'No subject'),
                                            "snippet": e.get('snippet', '')[:100]
                                        })
                                    output_data = {"emails": email_list, "count": len(email_list)}
                                    
                                    # Also send to client for display
                                    await client_ws.send(json.dumps({
                                        "type": "google.emails.result",
                                        "emails": emails
                                    }))
                                    print(f"[Function Call] Retrieved {len(emails)} emails")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Email error: {e}")
                            
                            elif func_name == 'retrieve_calendar':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    max_results = arguments.get('max_results', 5)
                                    events = gs.get_upcoming_events(max_results)
                                    
                                    event_list = []
                                    for e in events:
                                        event_list.append({
                                            "summary": e.get('summary', 'Untitled'),
                                            "start": e.get('start', 'Unknown'),
                                            "location": e.get('location', '')
                                        })
                                    output_data = {"events": event_list, "count": len(event_list)}
                                    
                                    # Also send to client for display
                                    await client_ws.send(json.dumps({
                                        "type": "google.calendar.result",
                                        "events": events
                                    }))
                                    print(f"[Function Call] Retrieved {len(events)} calendar events")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Calendar error: {e}")
                            
                            elif func_name == 'retrieve_files':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    max_results = arguments.get('max_results', 10)
                                    query = arguments.get('query', None)
                                    
                                    if query:
                                        files = gs.search_files(query, max_results)
                                    else:
                                        files = gs.list_files(max_results)
                                    
                                    file_list = []
                                    for f in files:
                                        file_list.append({
                                            "name": f.get('name', 'Unknown'),
                                            "mimeType": f.get('mimeType', ''),
                                            "id": f.get('id', '')
                                        })
                                    output_data = {"files": file_list, "count": len(file_list)}
                                    
                                    # Also send to client for display
                                    await client_ws.send(json.dumps({
                                        "type": "google.files.result",
                                        "files": files
                                    }))
                                    print(f"[Function Call] Retrieved {len(files)} files")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Files error: {e}")
                            
                            elif func_name == 'read_file_content':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    file_id = arguments.get('file_id', '')
                                    file_name = arguments.get('file_name', '')
                                    
                                    # If we have file_name but not file_id, search for it
                                    if file_name and not file_id:
                                        files = gs.search_files(file_name, 1)
                                        if files:
                                            file_id = files[0].get('id', '')
                                    
                                    if file_id:
                                        content = gs.get_file_content(file_id)
                                        
                                        # Check if this is an image that needs vision processing
                                        if content.startswith('__IMAGE_DATA_URL__'):
                                            image_data_url = content[len('__IMAGE_DATA_URL__'):]
                                            print(f"[Function Call] Image detected, sending to vision API...")
                                            description = await process_image_vision(image_data_url, 
                                                f"Describe what you see in this image in detail. The file is named '{file_name or 'unknown'}'.")
                                            output_data = {"content": description, "file_name": file_name or "image"}
                                            print(f"[Function Call] Vision description: {description[:100]}...")
                                        else:
                                            # Limit content to avoid token issues
                                            if len(content) > 5000:
                                                content = content[:5000] + "\n\n[Content truncated - file too long]"
                                            output_data = {"content": content, "file_name": file_name or "file"}
                                            print(f"[Function Call] Read file content ({len(content)} chars)")
                                    else:
                                        output_data = {"error": "File not found. Please specify the exact file name."}
                                        print(f"[Function Call] File not found: {file_name}")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Read file error: {e}")
                            
                            elif func_name == 'create_calendar_event':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    summary = arguments.get('summary', 'New Event')
                                    start_time = arguments.get('start_time', '')
                                    end_time = arguments.get('end_time', '')
                                    description = arguments.get('description', '')
                                    location = arguments.get('location', '')
                                    
                                    event = gs.create_event(summary, start_time, end_time, description, location)
                                    output_data = {"status": "created", "event_id": event.get('id'), "summary": summary, "start": start_time}
                                    print(f"[Function Call] Created calendar event: {summary}")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Calendar event error: {e}")
                            
                            elif func_name == 'send_email':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    to = arguments.get('to', '')
                                    subject = arguments.get('subject', '')
                                    body = arguments.get('body', '')
                                    
                                    result = gs.send_email(to, subject, body)
                                    output_data = {"status": "sent", "to": to, "subject": subject, "id": result.get('id')}
                                    print(f"[Function Call] Sent email to: {to}")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Send email error: {e}")
                            
                            elif func_name == 'write_to_sheet':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    spreadsheet_id = arguments.get('spreadsheet_id', '')
                                    spreadsheet_name = arguments.get('spreadsheet_name', '')
                                    data = arguments.get('data', [])
                                    append = arguments.get('append', True)
                                    
                                    # If we have name but not ID, search for it
                                    if spreadsheet_name and not spreadsheet_id:
                                        files = gs.search_files(spreadsheet_name, 5)
                                        for f in files:
                                            if 'spreadsheet' in f.get('mimeType', ''):
                                                spreadsheet_id = f.get('id')
                                                break
                                    
                                    if spreadsheet_id and data:
                                        if append:
                                            result = gs.append_sheet(spreadsheet_id, 'Sheet1', data)
                                        else:
                                            result = gs.write_sheet(spreadsheet_id, 'Sheet1', data)
                                        output_data = {"status": "written", "spreadsheet_id": spreadsheet_id, "rows_affected": len(data)}
                                        print(f"[Function Call] Wrote {len(data)} rows to sheet")
                                    else:
                                        output_data = {"error": "Spreadsheet not found or no data provided."}
                                        print(f"[Function Call] Sheet write failed - not found or no data")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Sheet write error: {e}")
                            
                            elif func_name == 'retrieve_contacts':
                                try:
                                    from google_services import get_google_services
                                    gs = get_google_services()
                                    max_results = arguments.get('max_results', 10)
                                    query = arguments.get('query', None)
                                    
                                    if query:
                                        contacts = gs.search_contacts(query, max_results)
                                    else:
                                        contacts = gs.get_contacts(max_results)
                                    
                                    contact_list = []
                                    for c in contacts:
                                        contact_list.append({
                                            "name": c.get('name', 'Unknown'),
                                            "email": c.get('email', ''),
                                            "phone": c.get('phone', ''),
                                            "organization": c.get('organization', '')
                                        })
                                    output_data = {"contacts": contact_list, "count": len(contact_list)}
                                    
                                    # Also send to client for display
                                    await client_ws.send(json.dumps({
                                        "type": "google.contacts.result",
                                        "contacts": contacts
                                    }))
                                    print(f"[Function Call] Retrieved {len(contacts)} contacts")
                                except Exception as e:
                                    output_data = {"error": str(e)}
                                    print(f"[Function Call] Contacts error: {e}")
                            
                            # Send function output back to xAI
                            if output_data and call_id:
                                await xai_ws.send(json.dumps({
                                    "type": "conversation.item.create",
                                    "item": {
                                        "type": "function_call_output",
                                        "call_id": call_id,
                                        "output": json.dumps(output_data)
                                    }
                                }))
                                # Trigger Ara to respond with the data
                                await xai_ws.send(json.dumps({"type": "response.create"}))
                                print(f"[Function Call] Sent output for {func_name}")
                        
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
             
    # Trigger final fact extraction on disconnect
    print("Client disconnected, running final fact extraction...")
    await run_background_fact_extraction()

async def run_background_fact_extraction():
    """Runs fact extraction on the recent memory buffer."""
    try:
        from memory import MemoryManager
        from fact_extractor import extract_facts
        
        # Load the recent history that hasn't been extracted yet
        # For safety, let's just grab the last 20 messages.
        # It's an overlapping window, but fact_extractor won't duplicate facts
        # if the attributes match existing ones.
        history = MemoryManager.load_memory()
        if not history.strip():
            return
            
        print("[FactExtractor] Running on recent conversation...")
        result = await extract_facts(history)
        new_facts = result.get("new_facts", [])
        
        if new_facts:
            MemoryManager.add_facts_to_profile(new_facts)
            print(f"[FactExtractor] Saved {len(new_facts)} new facts.")
        else:
            print("[FactExtractor] No new facts found.")
    except Exception as e:
        print(f"[FactExtractor] Error during background extraction: {e}")


async def main():
    port = int(os.getenv("PORT", 8765))
    host = "0.0.0.0"
    
    # Auto-index all memories into ChromaDB
    import threading
    def _index_memories():
        try:
            from vector_memory import init_vector_memory
            vm = init_vector_memory()
            vm.index_all_memories()
        except:
            pass
    
    threading.Thread(target=_index_memories, daemon=True).start()
    
    # Cloud Run Healthcheck handler using the newer websockets 14+ API
    # websockets.serve now handles process_request differently.
    async def process_request(connection, request):
        if request.path == "/" or request.path == "/health":
            import websockets.http11
            return websockets.http11.Response(200, "OK", [], b"OK\n")
        return None

    print(f"Starting Bridge on ws://{host}:{port}")
    async with websockets.serve(proxy_handler, host, port, process_request=process_request):
        await asyncio.get_running_loop().create_future()  # Run forever

if __name__ == "__main__":
    try:
        import os
        # Disable ChromaDB telemetry which crashes on Cloud Run
        os.environ["ANONYMIZED_TELEMETRY"] = "False"
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping bridge.")
