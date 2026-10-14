from google.auth import default
from googleapiclient.discovery import build

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
]

DRIVE_READ_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
]

DRIVE_WRITE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

SCOPES = sorted({*CALENDAR_SCOPES, *DRIVE_READ_SCOPES, *DRIVE_WRITE_SCOPES})


def get_credentials(scopes: list[str] | None = None):
    credentials, _ = default(scopes=scopes if scopes is not None else SCOPES)
    return credentials


def build_calendar_service():
    return build("calendar", "v3", credentials=get_credentials(CALENDAR_SCOPES))


def build_drive_service():
    return build("drive", "v3", credentials=get_credentials(DRIVE_READ_SCOPES))


def build_drive_write_service():
    return build("drive", "v3", credentials=get_credentials(DRIVE_WRITE_SCOPES))
