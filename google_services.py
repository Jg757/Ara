"""
Google Services Module for Ara
Provides access to Gmail, Google Drive, Sheets, and Calendar.
"""

import os
import json
import pickle
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

# Scopes for all Google services we need
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/calendar',
]

CREDENTIALS_FILE = 'google_credentials.json'
TOKEN_FILE = 'google_token.pickle'


class GoogleServices:
    """Unified access to Google services for Ara."""
    
    _instance = None
    _creds = None
    _gmail = None
    _drive = None
    _sheets = None
    _calendar = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        """Initialize Google services."""
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Google using OAuth2."""
        creds = None
        
        # Load existing token if available
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    raise FileNotFoundError(f"Missing {CREDENTIALS_FILE}. Please set up Google OAuth credentials.")
                
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=8082)  # Use different port to avoid conflict
            
            # Save the credentials for future use
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)
        
        self._creds = creds
        print("[GoogleServices] Authenticated successfully")
    
    @property
    def gmail(self):
        """Get Gmail service."""
        if self._gmail is None:
            self._gmail = build('gmail', 'v1', credentials=self._creds)
        return self._gmail
    
    @property
    def drive(self):
        """Get Google Drive service."""
        if self._drive is None:
            self._drive = build('drive', 'v3', credentials=self._creds)
        return self._drive
    
    @property
    def sheets(self):
        """Get Google Sheets service."""
        if self._sheets is None:
            self._sheets = build('sheets', 'v4', credentials=self._creds)
        return self._sheets
    
    @property
    def calendar(self):
        """Get Google Calendar service."""
        if self._calendar is None:
            self._calendar = build('calendar', 'v3', credentials=self._creds)
        return self._calendar
    
    # ============ GMAIL METHODS ============
    
    def get_recent_emails(self, max_results: int = 10) -> List[Dict]:
        """Get recent emails from inbox."""
        results = self.gmail.users().messages().list(
            userId='me', maxResults=max_results, labelIds=['INBOX']
        ).execute()
        
        messages = results.get('messages', [])
        emails = []
        
        for msg in messages:
            msg_detail = self.gmail.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg_detail.get('payload', {}).get('headers', [])}
            emails.append({
                'id': msg['id'],
                'from': headers.get('From', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'snippet': msg_detail.get('snippet', '')
            })
        
        return emails
    
    def search_emails(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search emails by query (e.g., 'from:john subject:invoice')."""
        results = self.gmail.users().messages().list(
            userId='me', q=query, maxResults=max_results
        ).execute()
        
        messages = results.get('messages', [])
        emails = []
        
        for msg in messages:
            msg_detail = self.gmail.users().messages().get(
                userId='me', id=msg['id'], format='metadata',
                metadataHeaders=['From', 'Subject', 'Date']
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg_detail.get('payload', {}).get('headers', [])}
            emails.append({
                'id': msg['id'],
                'from': headers.get('From', ''),
                'subject': headers.get('Subject', ''),
                'date': headers.get('Date', ''),
                'snippet': msg_detail.get('snippet', '')
            })
        
        return emails
    
    def get_email_content(self, msg_id: str) -> str:
        """Get full email content by ID."""
        msg = self.gmail.users().messages().get(
            userId='me', id=msg_id, format='full'
        ).execute()
        
        # Extract body
        payload = msg.get('payload', {})
        body = ''
        
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('mimeType') == 'text/plain':
                    import base64
                    data = part.get('body', {}).get('data', '')
                    if data:
                        body = base64.urlsafe_b64decode(data).decode('utf-8')
                        break
        else:
            import base64
            data = payload.get('body', {}).get('data', '')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8')
        
        return body
    
    def send_email(self, to: str, subject: str, body: str) -> Dict:
        """Send an email via Gmail."""
        import base64
        from email.mime.text import MIMEText
        
        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        
        # Encode the message
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        result = self.gmail.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        
        return {'id': result.get('id'), 'status': 'sent', 'to': to, 'subject': subject}
    
    # ============ GOOGLE DRIVE METHODS ============
    
    def list_files(self, max_results: int = 20, folder_id: str = None) -> List[Dict]:
        """List files in Drive."""
        query = f"'{folder_id}' in parents" if folder_id else None
        
        results = self.drive.files().list(
            pageSize=max_results,
            q=query,
            fields="files(id, name, mimeType, modifiedTime, size)"
        ).execute()
        
        return results.get('files', [])
    
    def search_files(self, query: str, max_results: int = 20) -> List[Dict]:
        """Search files by name or content."""
        search_query = f"name contains '{query}' or fullText contains '{query}'"
        
        results = self.drive.files().list(
            pageSize=max_results,
            q=search_query,
            fields="files(id, name, mimeType, modifiedTime, size)"
        ).execute()
        
        return results.get('files', [])
    
    def download_file(self, file_id: str, destination_path: str) -> str:
        """Download a file from Drive."""
        # Get file metadata to determine mime type
        file_meta = self.drive.files().get(fileId=file_id).execute()
        mime_type = file_meta.get('mimeType', '')
        
        # Handle Google Docs/Sheets/etc. - export to appropriate format
        if mime_type.startswith('application/vnd.google-apps'):
            if 'document' in mime_type:
                export_mime = 'application/pdf'
            elif 'spreadsheet' in mime_type:
                export_mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            elif 'presentation' in mime_type:
                export_mime = 'application/pdf'
            else:
                export_mime = 'application/pdf'
            
            request = self.drive.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = self.drive.files().get_media(fileId=file_id)
        
        with open(destination_path, 'wb') as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
        
        return destination_path
    
    def upload_file(self, file_path: str, folder_id: str = None) -> Dict:
        """Upload a file to Drive."""
        file_name = os.path.basename(file_path)
        
        file_metadata = {'name': file_name}
        if folder_id:
            file_metadata['parents'] = [folder_id]
        
        media = MediaFileUpload(file_path)
        file = self.drive.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, webViewLink'
        ).execute()
        
        return file
    
    def get_file_content(self, file_id: str) -> str:
        """Get text content of a file (works for text, PDFs, CSVs, Google Docs/Sheets)."""
        import tempfile
        
        file_meta = self.drive.files().get(fileId=file_id).execute()
        mime_type = file_meta.get('mimeType', '')
        file_name = file_meta.get('name', 'file')
        
        # Google Docs - export as plain text
        if mime_type == 'application/vnd.google-apps.document':
            request = self.drive.files().export_media(fileId=file_id, mimeType='text/plain')
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        
        # Google Sheets - export as CSV
        if mime_type == 'application/vnd.google-apps.spreadsheet':
            request = self.drive.files().export_media(fileId=file_id, mimeType='text/csv')
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        
        # Plain text files
        if 'text' in mime_type or mime_type in ['application/json', 'application/xml']:
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        
        # CSV files
        if 'csv' in mime_type or file_name.lower().endswith('.csv'):
            request = self.drive.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            fh.seek(0)
            return fh.read().decode('utf-8')
        
        # PDF files - use PyMuPDF to extract text
        if 'pdf' in mime_type or file_name.lower().endswith('.pdf'):
            try:
                import fitz  # PyMuPDF
                
                # Download to temp file
                request = self.drive.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
                
                # Extract text from PDF
                fh.seek(0)
                doc = fitz.open(stream=fh.read(), filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                
                return text if text.strip() else "PDF appears to be image-based (scanned). Cannot extract text."
            except Exception as e:
                return f"Error reading PDF: {str(e)}"
        
        return f"Cannot read content of file type: {mime_type}"
    
    # ============ GOOGLE SHEETS METHODS ============
    
    def read_sheet(self, spreadsheet_id: str, range_name: str = 'Sheet1') -> List[List]:
        """Read data from a Google Sheet."""
        result = self.sheets.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name
        ).execute()
        
        return result.get('values', [])
    
    def write_sheet(self, spreadsheet_id: str, range_name: str, values: List[List]) -> Dict:
        """Write data to a Google Sheet."""
        body = {'values': values}
        
        result = self.sheets.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            body=body
        ).execute()
        
        return result
    
    def append_sheet(self, spreadsheet_id: str, range_name: str, values: List[List]) -> Dict:
        """Append rows to a Google Sheet."""
        body = {'values': values}
        
        result = self.sheets.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        return result
    
    # ============ GOOGLE CALENDAR METHODS ============
    
    def get_upcoming_events(self, max_results: int = 10) -> List[Dict]:
        """Get upcoming calendar events."""
        now = datetime.utcnow().isoformat() + 'Z'
        
        events_result = self.calendar.events().list(
            calendarId='primary',
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        return [{
            'id': e['id'],
            'summary': e.get('summary', 'No title'),
            'start': e.get('start', {}).get('dateTime', e.get('start', {}).get('date', '')),
            'end': e.get('end', {}).get('dateTime', e.get('end', {}).get('date', '')),
            'location': e.get('location', ''),
            'description': e.get('description', '')
        } for e in events]
    
    def create_event(self, summary: str, start_time: str, end_time: str, 
                     description: str = '', location: str = '') -> Dict:
        """Create a calendar event."""
        event = {
            'summary': summary,
            'location': location,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'America/New_York'},
            'end': {'dateTime': end_time, 'timeZone': 'America/New_York'},
        }
        
        event = self.calendar.events().insert(calendarId='primary', body=event).execute()
        return event


# Convenience functions
def get_google_services() -> GoogleServices:
    """Get the Google services instance."""
    return GoogleServices.get_instance()


def is_authenticated() -> bool:
    """Check if Google services are authenticated."""
    return os.path.exists(TOKEN_FILE)


if __name__ == "__main__":
    # Test the services
    try:
        gs = get_google_services()
        
        print("\n=== Testing Gmail ===")
        emails = gs.get_recent_emails(5)
        for e in emails:
            print(f"  - {e['subject'][:50]}... from {e['from'][:30]}")
        
        print("\n=== Testing Drive ===")
        files = gs.list_files(5)
        for f in files:
            print(f"  - {f['name']}")
        
        print("\n=== Testing Calendar ===")
        events = gs.get_upcoming_events(5)
        for e in events:
            print(f"  - {e['summary']} at {e['start']}")
        
        print("\n✅ All Google services working!")
        
    except Exception as e:
        print(f"Error: {e}")
