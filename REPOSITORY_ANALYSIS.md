# Repository Analysis

## 1. What This Repository Does

This repository is a small Instagram publishing automation project built around one Python script and one GitHub Actions workflow.

High-level purpose:

1. GitHub Actions runs the uploader every 3 hours.
2. The Python script reads a scheduled media entry from `media_schedule.csv`.
3. It connects to Google Drive using a service-account credential from a GitHub secret.
4. It downloads the selected video from a fixed Drive folder.
5. It logs into Instagram using `instagrapi`.
6. It uploads the same video both as a feed post and as a story.
7. It deletes the downloaded temporary files from the runner.

This is not a layered application. It is a single-script automation job with the workflow logic, business logic, external API calls, and cleanup all living in [`script.py`](./script.py).

## 2. Repository Structure

### Core files

- [`script.py`](./script.py): Main application logic. Everything important happens here.
- [`.github/workflows/instagram_upload.yml`](./.github/workflows/instagram_upload.yml): Scheduled runner that executes `script.py`.
- [`media_schedule.csv`](./media_schedule.csv): Schedule input. Each row provides a UTC datetime, a Google Drive filename, and the Instagram caption.
- [`requirements.txt`](./requirements.txt): Python dependencies.
- [`README.md`](./README.md): Project description, but parts of it no longer match the actual implementation.

### Supporting files

- [`insta_session.json`](./insta_session.json): Cached Instagram session settings used by `instagrapi`.
- [`.gitignore`](./.gitignore): Minimal ignore rules.

## 3. End-to-End Runtime Flow

### Trigger layer

The workflow in [`.github/workflows/instagram_upload.yml`](./.github/workflows/instagram_upload.yml) runs:

- on a cron schedule: every 3 hours
- on manual trigger: `workflow_dispatch`

Workflow steps:

1. Check out the repo.
2. Install Python 3.9.
3. Install dependencies from `requirements.txt`.
4. Inject secrets as environment variables.
5. Run `python script.py`.

### Application layer

When [`script.py`](./script.py) starts, it executes top-level code immediately. There is no `main()` wrapper.

Runtime order:

1. Read environment variables:
   - `GOOGLE_CREDENTIAL`
   - `INSTAGRAM_USERNAME`
   - `INSTAGRAM_PASSWORD`
2. Build Google service-account credentials from `GOOGLE_CREDENTIAL`.
3. Create a Google Drive API client.
4. Load `media_schedule.csv`.
5. Find the row whose `Date & Time` is closest to the current UTC time.
6. Extract:
   - `File Path`
   - `Caption`
7. Search Google Drive for folder `finding__good__songs__`.
8. Search inside that folder for the scheduled file name.
9. Download the file into the current working directory.
10. Create an `instagrapi.Client()`.
11. Log into Instagram using cached session settings if possible.
12. Upload the file as a video post.
13. Upload the same file as a story.
14. Delete the downloaded video.
15. Delete the generated thumbnail JPG if present.

## 4. Detailed Flow Inside `script.py`

### A. Session login

Function: `login_with_session(...)`

Purpose:

- Reuse Instagram session state from `insta_session.json` if it exists.
- Fall back to fresh username/password login if relogin fails.
- Save session settings back to the same JSON file after fresh login.

Control path:

1. Set client username and password.
2. If `insta_session.json` exists:
   - load settings
   - call `client.relogin()`
   - if successful, stop here
3. Otherwise:
   - call `client.login(...)`
   - persist settings with `client.dump_settings(...)`

### B. Google Drive download

Function: `download_file_from_drive(...)`

Purpose:

- Locate a Google Drive folder by exact name.
- Locate a file by exact name within that folder.
- Download the file to local disk.

Control path:

1. Query Drive for a folder named `finding__good__songs__`.
2. Take the first matching folder.
3. Query files inside that folder for the scheduled filename.
4. Take the first matching file.
5. Stream the file to disk using `MediaIoBaseDownload`.

### C. Media selection

Function: `get_closest_media_row(...)`

Purpose:

- Read the schedule CSV and pick one row.

Selection logic:

1. Parse `Date & Time`.
2. Localize those timestamps to UTC.
3. Compute the absolute difference from current UTC time.
4. Return the row with the minimum delta.

This means the script chooses the nearest scheduled row, not necessarily:

- the next future row
- the latest overdue row
- a row scheduled exactly for the current run
- a row that has never been posted before

### D. Upload stage

Function: `upload_video_and_story(...)`

Purpose:

- Authenticate to Instagram.
- Upload one file twice:
  - once as a normal video post
  - once as a story

## 5. Data and Dependency Flow

### Inputs

- GitHub secrets:
  - Instagram username
  - Instagram password
  - Google service-account JSON
- Repo data:
  - `media_schedule.csv`
  - `insta_session.json`

### External services

- Google Drive API
- Instagram via `instagrapi`

### Outputs

- Instagram feed post
- Instagram story
- console logs in the GitHub Actions job

### Temporary local artifacts

- downloaded video file
- possible generated `*.jpg` sidecar file

## 6. Operational Behavior

### Scheduling model

The workflow runs every 3 hours, and the schedule file appears to be organized around 3-hour intervals as well. That is the intended alignment.

However, the script does not track posting history. It only computes "closest row right now".

Practical result:

- a retried workflow can post the same item again
- a manually triggered workflow can post the same item again
- once the schedule is fully in the past, the last scheduled row becomes the permanent "closest" row

Given the current repository date and the schedule contents visible in the CSV, the schedule appears to end in late 2024. In its current form, a run today would select the last available 2024 row because it is the closest timestamp left in the file.

### Session persistence model

`insta_session.json` is tracked in the repository. On GitHub Actions, the runner gets a fresh checkout on every run.

That means:

- the checked-in session file is available at start
- any updated session written during the run is not preserved for the next run unless committed back, cached, or otherwise persisted

So the session cache helps only as long as the repository copy remains valid.

## 7. Current Gaps and Risks

### 1. Schedule selection can cause duplicate or stale uploads

This is the biggest logic issue in the repository.

Reason:

- `get_closest_media_row()` uses absolute time delta
- there is no "already posted" state
- there is no requirement that selected time be within the current execution window

Impact:

- duplicate uploads are possible
- old content can be reposted indefinitely after the schedule ends

### 2. `README.md` does not match the current code

The README says captions are read from `caption.txt`, but the real implementation reads captions from the `Caption` column in `media_schedule.csv`.

Impact:

- setup instructions are misleading
- `caption.txt` is documented, but not used by the script

### 3. `GOOGLE_CREDENTIAL` is parsed with `eval(...)`

The script uses `eval(SERVICE_ACCOUNT_INFO)` to build the service-account object.

Why this is a problem:

- `eval` executes arbitrary Python
- it is unnecessary here
- a JSON parser would be safer and more predictable

### 4. Top-level execution makes the script less testable and less reusable

Most of the program runs as soon as `script.py` is imported or executed.

Impact:

- hard to unit test
- hard to reuse pieces cleanly
- failures in env setup happen before any guarded entrypoint

### 5. Folder and file resolution are name-based and pick the first match

Google Drive lookup uses exact-name searches and then selects the first result.

Impact:

- duplicate folder names can resolve unpredictably
- duplicate filenames in the same folder can resolve unpredictably

### 6. `if not media_row.empty` is not a meaningful guard here

`get_closest_media_row()` returns a single pandas row. In normal execution, that row is not empty.

Impact:

- the `else: print("No media scheduled for today")` branch is effectively not the real no-data path
- if the CSV were empty, the failure would happen earlier

### 7. Sensitive session data is stored in the repository

`insta_session.json` is present in the repo and is not ignored by `.gitignore`.

Impact:

- session data is easier to leak accidentally
- repo hygiene and credential handling are weaker than they should be

## 8. Architecture Summary

This repository follows a very direct pipeline:

`GitHub Actions schedule -> Python script -> CSV selection -> Google Drive download -> Instagram login -> feed upload + story upload -> local cleanup`

It is simple and easy to follow because everything is concentrated in one place. The tradeoff is that correctness, security, and maintainability concerns are also concentrated in one file.

## 9. If You Want to Improve It Next

The highest-value changes would be:

1. Replace "closest row" logic with "next due item" or "current window item".
2. Add a posted-state mechanism so the same row cannot be uploaded twice.
3. Replace `eval(...)` with JSON parsing.
4. Move top-level runtime into a `main()` function.
5. Stop tracking `insta_session.json` in git.
6. Update `README.md` so it matches the real flow.

## 10. One-Screen Mental Model

If you want the shortest explanation of how the flow works:

1. GitHub Actions wakes up every 3 hours.
2. It runs `script.py` with Instagram and Google credentials from secrets.
3. `script.py` picks the schedule row nearest to the current UTC time.
4. It downloads that video from a fixed Google Drive folder.
5. It logs into Instagram.
6. It posts the video to the feed.
7. It posts the same video to the story.
8. It deletes the downloaded file from the runner.
