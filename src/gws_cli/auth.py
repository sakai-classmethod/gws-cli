from google.auth import default
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials():
    credentials, _ = default(scopes=SCOPES)
    return credentials


def build_calendar_service():
    return build("calendar", "v3", credentials=get_credentials())


def build_drive_service():
    return build("drive", "v3", credentials=get_credentials())
