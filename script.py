import json
import os
import pandas as pd
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from instagrapi import Client
from instagrapi.exceptions import ClipNotUpload, PhotoNotUpload, VideoNotUpload

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv'}
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


def load_session_settings(session_file_path):
    session_path = Path(session_file_path)
    if not session_path.exists():
        return None

    try:
        with session_path.open('r', encoding='utf-8') as session_file:
            return json.load(session_file)
    except (JSONDecodeError, OSError) as exc:
        invalid_path = session_path.with_suffix(f'{session_path.suffix}.invalid')
        try:
            session_path.replace(invalid_path)
            print(
                f"Existing session file was invalid and was moved to "
                f"'{invalid_path.name}': {exc}"
            )
        except OSError:
            print(f"Existing session file was invalid and will be ignored: {exc}")
        return None


def save_session_settings(client, session_file_path):
    session_path = Path(session_file_path)
    temp_path = session_path.with_suffix(f'{session_path.suffix}.tmp')

    with temp_path.open('w', encoding='utf-8') as session_file:
        json.dump(client.get_settings(), session_file, indent=4)

    temp_path.replace(session_path)
    print(f"Session saved to '{session_path.name}'")


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

    session_settings = load_session_settings(session_file_path)
    if session_settings:
        client.set_settings(session_settings)
        try:
            client.relogin()
            save_session_settings(client, session_file_path)
            print("Session loaded successfully")
            return
        except Exception as e:
            print(f"Relogin failed: {e}, performing a fresh login")

    client.login(username, password)
    save_session_settings(client, session_file_path)
    print("Logged in successfully")


def resolve_media_path(file_path):
    media_path = Path(str(file_path)).expanduser()
    if not media_path.is_absolute():
        media_path = Path(__file__).resolve().parent / media_path
    return media_path.resolve()


def resolve_challenge_if_needed(client, session_file_path):
    last_json = client.last_json or {}
    if last_json.get('message') != 'challenge_required':
        return False

    print('Instagram requested a challenge. Enter the verification code when prompted.')
    client.challenge_resolve(last_json)
    save_session_settings(client, session_file_path)
    print('Challenge resolved successfully')
    return True


def upload_feed_media(client, media_path, caption):
    media_suffix = Path(media_path).suffix.lower()

    if media_suffix in IMAGE_EXTENSIONS:
        client.photo_upload(media_path, caption)
        print(f"Image uploaded as a post with caption: {caption}")
        return

    if media_suffix in VIDEO_EXTENSIONS:
        client.video_upload(media_path, caption)
        print(f"Video uploaded as a post with caption: {caption}")
        return

    raise ValueError(f"Unsupported media type for '{media_path}'")


def upload_story_media(client, media_path):
    media_suffix = Path(media_path).suffix.lower()

    if media_suffix in IMAGE_EXTENSIONS:
        client.photo_upload_to_story(media_path)
        print("Image uploaded as a story")
        return

    if media_suffix in VIDEO_EXTENSIONS:
        client.video_upload_to_story(media_path)
        print("Video uploaded as a story")
        return

    raise ValueError(f"Unsupported media type for '{media_path}'")


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
    upload_errors = (PhotoNotUpload, VideoNotUpload, ClipNotUpload)

    def run_with_challenge_retry(action, action_name):
        for attempt in range(2):
            try:
                action()
                save_session_settings(client, SESSION_FILE_PATH)
                return
            except upload_errors as exc:
                if attempt == 0 and resolve_challenge_if_needed(client, SESSION_FILE_PATH):
                    print(f"Retrying {action_name} after challenge resolution")
                    continue
                raise RuntimeError(
                    f"Instagram rejected the {action_name}. If the account is still "
                    "under verification, complete the challenge in the Instagram app "
                    "and retry."
                ) from exc

    run_with_challenge_retry(
        lambda: upload_feed_media(client, media_path, caption),
        'feed upload',
    )
    run_with_challenge_retry(
        lambda: upload_story_media(client, media_path),
        'story upload',
    )


def get_scheduled_media_row(schedule_csv_path):
    schedule_df = pd.read_csv(schedule_csv_path)
    if schedule_df.empty:
        return pd.Series(dtype=object)

    current_time = datetime.now()
    current_date = current_time.date()
    raw_schedule_values = schedule_df['Date & Time'].astype(str).str.strip()

    schedule_df['Scheduled At'] = pd.to_datetime(
        raw_schedule_values,
        errors='coerce'
    )
    schedule_df['Has Explicit Time'] = raw_schedule_values.str.contains(':')
    schedule_df = schedule_df.dropna(subset=['Scheduled At'])

    timed_rows = schedule_df.loc[
        schedule_df['Has Explicit Time']
        & (schedule_df['Scheduled At'].dt.date == current_date)
        & (schedule_df['Scheduled At'] <= current_time)
    ]
    if not timed_rows.empty:
        return timed_rows.sort_values('Scheduled At').iloc[-1]

    date_only_rows = schedule_df.loc[
        ~schedule_df['Has Explicit Time']
        & (schedule_df['Scheduled At'].dt.date == current_date)
    ]
    if not date_only_rows.empty:
        return date_only_rows.iloc[0]

    return pd.Series(dtype=object)


# Load Instagram credentials from environment variables
load_local_env_file(Path(__file__).resolve().parent / '.env')
INSTAGRAM_USERNAME = os.getenv('INSTAGRAM_USERNAME')
INSTAGRAM_PASSWORD = os.getenv('INSTAGRAM_PASSWORD')

if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
    raise RuntimeError('INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD must be set.')

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
    print("No media scheduled for the current date/time.")
