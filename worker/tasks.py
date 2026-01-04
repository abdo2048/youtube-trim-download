import os
import requests
import subprocess
import yt_dlp
from celery import Celery
from dotenv import load_dotenv
from glob import glob
import time
import redis

load_dotenv()

REDIS_LOCAL_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
UPLOAD_LOCAL_URL = "http://localhost:8000/uploadfromworker"
UPLOAD_SECRET_KEY = os.environ.get("UPLOAD_SECRET_KEY")
UPLOAD_URL = os.environ.get("UPLOAD_URL", UPLOAD_LOCAL_URL)
VIDEOS_PATH = "videos/"


def make_celery(app):
    celery = Celery(
        app.import_name,
        backend=REDIS_LOCAL_URL,
        broker=REDIS_LOCAL_URL
    )
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
    return celery


def create_videos_folder():
    try:
        if not os.path.exists("videos"):
            os.mkdir("videos")
    except Exception as e:
        print(e)


create_videos_folder()


def get_adjusted_start(val):
    if val > 4:
        return val - 4
    else:
        return val


def get_path(id, quality):
    files = glob(f"{VIDEOS_PATH}*{id}*")
    for v in files:
        if f"qi{str(quality)}" in v:
            path = v
    print(path)
    return path

@celery.task
def trim(url, quality, start, end, ip):
    start = int(start)
    end = int(end) + 1
    ydl_opts = {}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
            id = result["id"]

            download_video_command = [
                "yt-dlp",
                "-f",
                f"{quality}+ba",
                url,
                "-o",
                VIDEOS_PATH + "%(title)s-%(id)s-qi%(format_id)s.%(ext)s",
            ]

            p1 = subprocess.Popen(download_video_command, stdin=subprocess.PIPE)
            p1.wait()

            original_video_path = get_path(id, quality)
            original_video_name = original_video_path.split(".")[0]
            original_video_ext = original_video_path.split(".")[-1]

            if original_video_ext == "m4a":
                final_ext = "mp3"
            else:
                final_ext = original_video_ext

            final_file_name = (
                f"{original_video_name}-s{start}-e{end}-trimmed.{final_ext}"
            )

            # Calculate actual duration for the trim command
            duration = end - start - 4  # subtract the 4 seconds we added earlier
            if duration <= 0:
                duration = 1  # minimum duration of 1 second

            audio_command = [
                "ffmpeg",
                "-ss",
                str(get_adjusted_start(start)),  # Use the helper function to adjust start time
                "-i",
                original_video_path,
                "-t",
                str(duration),  # Use calculated duration instead of absolute end time
                "-c:v",
                "copy",
                "-c:a",
                "libmp3lame",
                "-q:a",
                "4",
                final_file_name,
                "-y",
            ]

            video_command = [
                "ffmpeg",
                "-ss",
                str(get_adjusted_start(start)),  # Use the helper function to adjust start time
                "-i",
                original_video_path,
                "-t",
                str(duration),  # Use calculated duration instead of absolute end time
                "-avoid_negative_ts",
                "make_zero",
                "-c",
                "copy",
                final_file_name,
                "-y",
            ]

            if original_video_ext == "m4a":
                p2 = subprocess.Popen(audio_command, stdin=subprocess.PIPE)
                p2.wait()
            else:
                p2 = subprocess.Popen(video_command, stdin=subprocess.PIPE)
                p2.wait()

            file_to_upload = {"file": open(final_file_name, "rb")}
            headers = {"secret_key": UPLOAD_SECRET_KEY}
            upload_result = requests.post(
                UPLOAD_URL, files=file_to_upload, headers=headers
            )
            file_to_upload["file"].close()  # Close the file after upload
            return upload_result.json()
    except Exception as e:
        print(e, "was handled")
        return {"success": False, "data": None, "message": "Something went wrong"}