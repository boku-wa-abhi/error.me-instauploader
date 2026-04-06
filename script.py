import os
import pandas as pd
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from instagrapi import Client

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
DEFAULT_POST_TIMEZONE = 'America/New_York'
DEFAULT_POST_HOUR = 19
SESSION_FILE_PATH = 'insta_session.json'


def load_local_env_file(env_file_path):
    if not env_file_path.exists():
        return

    for raw_line in env_file_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue

        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

def login_with_session(client, username, password, session_file_path):
    """
    Login to Instagram using session caching. If a session file exists, it will be loaded;
    otherwise, a new login will be performed, and the session will be saved.
    
    Parameters:
    client (Client): The instagrapi Client instance.
    username (str): Instagram username.
    password (str): Instagram password.
    session_file_path (str): Path for saving the session file.
    """
    client.username = username
    client.password = password
    if os.path.exists(session_file_path):
        # Load session if available
        client.load_settings(session_file_path)
        try:
            client.relogin()
            print("Session loaded successfully")
            return
        except Exception as e:
            print(f"Relogin failed: {e}, performing a fresh login")
    
    # If relogin fails or session file doesn't exist, perform a fresh login
    client.login(username, password)
    client.dump_settings(session_file_path)
    print("Logged in and session saved")


def resolve_media_path(file_path):
    media_path = Path(str(file_path)).expanduser()
    if not media_path.is_absolute():
        media_path = Path(__file__).resolve().parent / media_path
    return media_path.resolve()


def get_post_timezone():
    timezone_name = os.getenv('POST_TIMEZONE', DEFAULT_POST_TIMEZONE)
    return ZoneInfo(timezone_name)


def should_post_now():
    post_timezone = get_post_timezone()
    post_hour = int(os.getenv('POST_HOUR', DEFAULT_POST_HOUR))
    current_time = datetime.now(post_timezone)

    if current_time.hour != post_hour:
        print(
            f"Skipping run. Current time in {post_timezone.key}: "
            f"{current_time.strftime('%Y-%m-%d %H:%M:%S')}. "
            f"Scheduled hour is {post_hour:02d}:00."
        )
        return False

    return True


def upload_media_and_story(client, media_path, caption, username, password):
    """
    Uploads an image or video to Instagram as both a post and a story.

    Parameters:
    client (Client): The instagrapi Client instance.
    media_path (str): The file path of the media to upload.
    caption (str): The caption to include with the post.
    username (str): Instagram username.
    password (str): Instagram password.
    """
    login_with_session(client, username, password, session_file_path=SESSION_FILE_PATH)

    media_suffix = Path(media_path).suffix.lower()

    if media_suffix in IMAGE_EXTENSIONS:
        client.photo_upload(media_path, caption)
        print(f"Image uploaded as a post with caption: {caption}")
        client.photo_upload_to_story(media_path)
        print("Image uploaded as a story")
        return

    if media_suffix in VIDEO_EXTENSIONS:
        client.video_upload(media_path, caption)
        print(f"Video uploaded as a post with caption: {caption}")
        client.video_upload_to_story(media_path)
        print("Video uploaded as a story")
        return

    raise ValueError(f"Unsupported media type for '{media_path}'")


def get_scheduled_media_row(schedule_csv_path):
    # Load the media schedule
    schedule_df = pd.read_csv(schedule_csv_path)
    if schedule_df.empty:
        return pd.Series(dtype=object)

    post_timezone = get_post_timezone()
    current_date = datetime.now(post_timezone).date()

    schedule_df['Scheduled Date'] = pd.to_datetime(
        schedule_df['Date & Time'],
        errors='coerce'
    ).dt.date
    schedule_df = schedule_df.dropna(subset=['Scheduled Date'])

    todays_media = schedule_df.loc[schedule_df['Scheduled Date'] == current_date]
    if todays_media.empty:
        return pd.Series(dtype=object)

    return todays_media.iloc[0]


# Load Instagram credentials from environment variables
load_local_env_file(Path(__file__).resolve().parent / '.env')
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
    raise RuntimeError('INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set.')

# Main execution flow
if should_post_now():
    media_row = get_scheduled_media_row('media_schedule.csv')

    if not media_row.empty:
        media_path = resolve_media_path(media_row['File Path'])
        caption = media_row['Caption']

        if not media_path.exists():
            raise FileNotFoundError(f"Scheduled media file does not exist: {media_path}")

        instagram_client = Client()
        upload_media_and_story(
            instagram_client,
            str(media_path),
            caption,
            INSTAGRAM_USERNAME,
            INSTAGRAM_PASSWORD,
        )
    else:
        print("No media scheduled for today.")
