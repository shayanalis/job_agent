"""Google Drive API integration service."""

import os
import logging
import re
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.errors import HttpError
import io

from config.settings import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_TOKEN_PATH,
    GOOGLE_DRIVE_POINTERS_FOLDER_ID,
    GOOGLE_DRIVE_OUTPUT_FOLDER_ID,
)

logger = logging.getLogger(__name__)


class DriveService:
    """Handle all Google Drive operations."""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        """Initialize Google Drive service with OAuth authentication."""
        self.creds = self._authenticate()
        self.service = build('drive', 'v3', credentials=self.creds, cache_discovery=False)
        logger.info("Google Drive service initialized successfully")

    def _authenticate(self) -> Credentials:
        """Authenticate with Google Drive API using OAuth 2.0.

        Returns:
            Credentials: Authenticated credentials object

        Raises:
            FileNotFoundError: If credentials.json is missing
        """
        creds = None

        # Load existing token if available
        if os.path.exists(GOOGLE_TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, self.SCOPES)
            logger.info("Loaded existing token from token.json")

        # Refresh or create new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    logger.info("Refreshing expired credentials")
                    creds.refresh(Request())
                except Exception as refresh_error:
                    logger.warning(f"Failed to refresh credentials: {refresh_error}")
                    logger.info("Refresh token is invalid or expired. Deleting token.json and re-authenticating...")

                    # Delete the invalid token file
                    if os.path.exists(GOOGLE_TOKEN_PATH):
                        os.remove(GOOGLE_TOKEN_PATH)

                    # Force re-authentication
                    creds = None

            # If creds is None, we need to authenticate from scratch
            if not creds or not creds.valid:
                if not os.path.exists(GOOGLE_CREDENTIALS_PATH):
                    raise FileNotFoundError(
                        f"credentials.json not found at {GOOGLE_CREDENTIALS_PATH}. "
                        "Please download it from Google Cloud Console."
                    )

                logger.info("Starting OAuth flow for new credentials")
                flow = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_PATH, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open(GOOGLE_TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())
                logger.info("Saved new credentials to token.json")

        return creds

    def list_pointer_documents(self, folder_id: Optional[str] = None) -> List[Dict[str, str]]:
        """List all pointer documents in the resume pointers folder.
        
        Supports multiple file types:
        - Google Docs
        - Text files (.txt)
        - Markdown files (.md)

        Args:
            folder_id: Google Drive folder ID. Defaults to GOOGLE_DRIVE_POINTERS_FOLDER_ID

        Returns:
            List of dicts with 'id', 'name', and 'mimeType' keys

        Raises:
            HttpError: If API call fails
        """
        if folder_id is None:
            folder_id = GOOGLE_DRIVE_POINTERS_FOLDER_ID

        try:
            # First, check if we can access the folder
            logger.info(f"Accessing folder with ID: {folder_id}")
            
            # List ALL files in the folder for debugging
            all_query = f"'{folder_id}' in parents and trashed=false"
            all_results = self.service.files().list(
                q=all_query,
                fields="files(id, name, mimeType, createdTime)",
                orderBy="name"
            ).execute()
            
            all_files = all_results.get('files', [])
            logger.info(f"Total files in folder: {len(all_files)}")
            
            if not all_files:
                logger.warning("Folder appears to be empty or inaccessible")
                logger.warning("Please ensure:")
                logger.warning("1. The folder ID is correct")
                logger.warning("2. The folder is shared with the service account")
                logger.warning("3. The folder contains resume pointer files")
            else:
                for file in all_files:
                    logger.info(f"  - {file['name']} (Type: {file['mimeType']}, ID: {file['id']})")
            
            # Search for supported document types
            supported_types = [
                "application/vnd.google-apps.document",  # Google Docs
                "text/plain",  # .txt files
                "text/markdown",  # .md files
            ]
            
            # Build query for multiple MIME types
            mime_queries = [f"mimeType='{mime}'" for mime in supported_types]
            query = f"'{folder_id}' in parents and ({' or '.join(mime_queries)}) and trashed=false"
            
            # Also search by name pattern for markdown files (sometimes MIME type isn't set correctly)
            name_query = f"'{folder_id}' in parents and (name contains '.md' or name contains '.txt') and trashed=false"
            
            # Get files by MIME type
            mime_results = self.service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                orderBy="name"
            ).execute()
            
            # Get files by name pattern
            name_results = self.service.files().list(
                q=name_query,
                fields="files(id, name, mimeType)",
                orderBy="name"
            ).execute()
            
            # Combine and deduplicate results
            files_dict = {}
            for file in mime_results.get('files', []) + name_results.get('files', []):
                files_dict[file['id']] = file
            
            files = list(files_dict.values())
            
            logger.info(f"Found {len(files)} pointer documents:")
            for file in files:
                logger.info(f"  - {file['name']} ({file['mimeType']})")
            
            return files

        except HttpError as error:
            logger.error(f"Error accessing Google Drive folder: {error}")
            if "404" in str(error):
                logger.error("Folder not found. Please check the folder ID in your .env file")
            elif "403" in str(error):
                logger.error("Access denied. Please ensure the folder is shared with your service account")
            raise

    def download_file_content(self, file_id: str) -> str:
        """Download text content from a Google Drive file.

        Args:
            file_id: Google Drive file ID

        Returns:
            File content as string

        Raises:
            HttpError: If API call fails
        """
        try:
            # Check file metadata to determine type
            file_metadata = self.get_file_metadata(file_id)
            mime_type = file_metadata.get('mimeType', '')
            
            if mime_type == 'application/vnd.google-apps.document':
                # Export Google Docs as plain text
                request = self.service.files().export_media(
                    fileId=file_id,
                    mimeType='text/plain'
                )
            else:
                # Download regular files
                request = self.service.files().get_media(fileId=file_id)
            
            file_handle = io.BytesIO()
            downloader = MediaIoBaseDownload(file_handle, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            content = file_handle.getvalue().decode('utf-8')
            logger.info(f"Downloaded file {file_id} ({len(content)} bytes)")
            return content

        except HttpError as error:
            logger.error(f"Error downloading file {file_id}: {error}")
            raise

    def download_file_binary(self, file_id: str, output_path: str) -> str:
        """Download a binary file from Google Drive to local path.

        Args:
            file_id: Google Drive file ID
            output_path: Local path where file will be saved

        Returns:
            Local file path

        Raises:
            HttpError: If API call fails
        """
        try:
            request = self.service.files().get_media(fileId=file_id)
            file_handle = io.BytesIO()
            downloader = MediaIoBaseDownload(file_handle, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            # Ensure directory exists
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)

            # Write binary content to file
            with open(output_path, 'wb') as f:
                f.write(file_handle.getvalue())

            logger.info(f"Downloaded binary file {file_id} to {output_path} ({Path(output_path).stat().st_size} bytes)")
            return output_path

        except HttpError as error:
            logger.error(f"Error downloading binary file {file_id}: {error}")
            raise

    def upload_file(
        self,
        file_path: str,
        folder_id: Optional[str] = None,
        file_name: Optional[str] = None,
        mime_type: Optional[str] = None
    ) -> str:
        """Upload a file to Google Drive and return shareable link.

        Args:
            file_path: Local path to file
            folder_id: Target folder ID. Defaults to GOOGLE_DRIVE_OUTPUT_FOLDER_ID
            file_name: Name for uploaded file. Defaults to original filename
            mime_type: MIME type of file. Auto-detected if not provided

        Returns:
            Shareable Google Drive link

        Raises:
            FileNotFoundError: If local file doesn't exist
            HttpError: If API call fails
        """
        if folder_id is None:
            folder_id = GOOGLE_DRIVE_OUTPUT_FOLDER_ID

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if file_name is None:
            file_name = Path(file_path).name

        try:
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }

            # Auto-detect MIME type if not provided
            if mime_type is None:
                ext = Path(file_path).suffix.lower()
                mime_type_map = {
                    '.pdf': 'application/pdf',
                    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                    '.doc': 'application/msword',
                    '.txt': 'text/plain'
                }
                mime_type = mime_type_map.get(ext, 'application/octet-stream')
            
            media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, webViewLink'
            ).execute()

            file_id = file.get('id')
            web_link = file.get('webViewLink')

            # Make file shareable (anyone with link can view)
            self.service.permissions().create(
                fileId=file_id,
                body={'type': 'anyone', 'role': 'reader'}
            ).execute()

            logger.info(f"Uploaded file to Google Drive: {web_link}")
            return web_link

        except HttpError as error:
            logger.error(f"Error uploading file: {error}")
            raise

    def get_file_metadata(self, file_id: str) -> Dict:
        """Get metadata for a specific file.

        Args:
            file_id: Google Drive file ID

        Returns:
            File metadata dictionary

        Raises:
            HttpError: If API call fails
        """
        try:
            file = self.service.files().get(
                fileId=file_id,
                fields='id, name, mimeType, createdTime, modifiedTime'
            ).execute()
            return file

        except HttpError as error:
            logger.error(f"Error getting file metadata: {error}")
            raise

    @staticmethod
    def extract_file_id_from_url(url: str) -> Optional[str]:
        """Extract Google Drive file ID from various URL formats.

        Supports:
        - https://drive.google.com/file/d/FILE_ID/view
        - https://drive.google.com/open?id=FILE_ID
        - https://drive.google.com/file/d/FILE_ID/
        - https://docs.google.com/document/d/FILE_ID/edit
        - FILE_ID (if already just the ID)

        Args:
            url: Google Drive URL or file ID

        Returns:
            File ID if found, None otherwise
        """
        if not url:
            return None

        # If it's already just an ID (no special characters except alphanumeric and hyphens)
        if re.match(r'^[a-zA-Z0-9_-]+$', url):
            return url

        # Pattern 1: /file/d/FILE_ID or /document/d/FILE_ID
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)

        match = re.search(r'/document/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)

        # Pattern 2: ?id=FILE_ID
        match = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)

        logger.warning(f"Could not extract file ID from URL: {url}")
        return None

    def download_file_binary_content(self, file_id: str, export_as_pdf: bool = False) -> Tuple[bytes, str, str]:
        """Download a binary file from Google Drive and return content in memory.

        Args:
            file_id: Google Drive file ID
            export_as_pdf: If True, export Google Docs/Word files as PDF

        Returns:
            Tuple of (binary_content, mime_type, filename)

        Raises:
            HttpError: If API call fails
        """
        try:
            # Get file metadata first to get name and MIME type
            file_metadata = self.get_file_metadata(file_id)
            mime_type = file_metadata.get('mimeType', 'application/octet-stream')
            file_name = file_metadata.get('name', 'download')

            # If PDF export is requested, export the file as PDF
            if export_as_pdf:
                google_docs_mime = 'application/vnd.google-apps.document'
                office_mime_types = [
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  # .docx
                    'application/msword',  # .doc
                ]
                
                # If it's already a PDF, just download it
                if mime_type == 'application/pdf':
                    request = self.service.files().get_media(fileId=file_id)
                    logger.info(f"File {file_id} is already PDF format")
                # Google Docs can be exported directly as PDF
                elif mime_type == google_docs_mime:
                    request = self.service.files().export_media(
                        fileId=file_id,
                        mimeType='application/pdf'
                    )
                    mime_type = 'application/pdf'
                    base_name = Path(file_name).stem
                    file_name = f"{base_name}.pdf"
                    logger.info(f"Exporting Google Doc {file_id} as PDF")
                # For Office files, try to export as PDF
                # Note: export_media only works for Google Docs format, not regular Office files
                elif mime_type in office_mime_types:
                    try:
                        # Try exporting as PDF (may work if file was converted to Google Docs format)
                        request = self.service.files().export_media(
                            fileId=file_id,
                            mimeType='application/pdf'
                        )
                        mime_type = 'application/pdf'
                        base_name = Path(file_name).stem
                        file_name = f"{base_name}.pdf"
                        logger.info(f"Exporting Office file {file_id} as PDF via Google Drive")
                    except HttpError as export_error:
                        # export_media doesn't work for regular Office files - need local conversion
                        error_msg = str(export_error)
                        if 'exportNotSupported' in error_msg or '400' in error_msg:
                            logger.error(
                                f"Cannot export Office file {file_id} as PDF directly. "
                                f"Regular .docx files stored in Google Drive cannot be exported as PDF via API. "
                                f"File would need to be downloaded and converted locally."
                            )
                            raise ValueError(
                                "Office files (.docx) stored in Google Drive cannot be exported as PDF directly. "
                                "The file needs to be a Google Doc format or already in PDF format."
                            )
                        else:
                            raise
                else:
                    logger.warning(f"File {file_id} (MIME type: {mime_type}) cannot be exported as PDF")
                    request = self.service.files().get_media(fileId=file_id)
            else:
                # Download file content as-is
                request = self.service.files().get_media(fileId=file_id)

            file_handle = io.BytesIO()
            downloader = MediaIoBaseDownload(file_handle, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            content = file_handle.getvalue()
            logger.info(f"Downloaded file {file_id} ({len(content)} bytes, MIME: {mime_type})")
            return content, mime_type, file_name

        except HttpError as error:
            logger.error(f"Error downloading binary file {file_id}: {error}")
            raise

