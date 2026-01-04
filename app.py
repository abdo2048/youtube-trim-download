import json
import os
import redis
import time
import yt_dlp
from flask import Flask
from flask import abort
from flask import jsonify
from flask import render_template
from flask import request
from flask import send_from_directory
from flask_cors import CORS
from celery import Celery
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__, static_url_path="/templates/static/")

CORS(app)

UPLOAD_FOLDER = "videos"
ON_HEROKU = "ON_HEROKU" in os.environ
ON_RENDER = os.environ.get("RENDER_EXTERNAL_URL") is not None  # Render sets this environment variable
ON_RAILWAY = os.environ.get("RAILWAY") is not None  # Railway sets this environment variable
TRIM_TASK_NAME = "worker.tasks.trim" if (ON_HEROKU or ON_RENDER or ON_RAILWAY) else "tasks.trim"
REDIS_LOCAL_URL = "redis://localhost:6379"
REDIS_URL = os.environ.get("REDIS_URL", REDIS_LOCAL_URL)
UPLOAD_SECRET_KEY = os.environ.get("UPLOAD_SECRET_KEY")
TRIMMED_FILE_SIZE_LIMIT_MB = os.environ.get("TRIMMED_FILE_SIZE_LIMIT_MB", 100)
VIDEO_FILE_SIZE_LIMIT_MB = os.environ.get("VIDEO_FILE_SIZE_LIMIT_MB", 400)
ALLOWED_VIDEO_SIZES = ("360", "480", "720")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# Initialize Celery
celery = Celery(
    "tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

redis_instance = None

def get_redis_instance():
    max_retries = 10
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            redis_conn = redis.from_url(REDIS_URL)
            # Test the connection
            redis_conn.ping()
            print("Successfully connected to Redis")
            return redis_conn
        except Exception as e:
            print(f"Failed to connect to Redis (attempt {retry_count + 1}/{max_retries}): {e}")
            retry_count += 1
            if retry_count >= max_retries:
                print("Max retries reached. Application may not function properly without Redis.")
                # Return a mock Redis instance to prevent crashes
                class MockRedis:
                    def ping(self):
                        return True
                    def scan_iter(self, match):
                        return []
                    def get(self, key):
                        return None
                    def set(self, key, value):
                        pass
                    def decode(self, value):
                        return value
                    def __getattr__(self, name):
                        # Handle any other redis methods that might be called
                        def dummy_method(*args, **kwargs):
                            print(f"Warning: Called unimplemented Redis method {name}")
                            return None
                        return dummy_method
                return MockRedis()
            else:
                print(f"Retrying in 5 seconds...")
                time.sleep(5)

redis_instance = get_redis_instance()

ydl_opts = {}
ydlr = yt_dlp.YoutubeDL(ydl_opts)


def create_videos_folder():
    try:
        if not os.path.exists("videos"):
            os.mkdir("videos")
    except Exception as e:
        print(e)


create_videos_folder()


def process_video_request(data):
    videos = []
    selected = {}
    for x in data["formats"]:
        if x["ext"] == "m4a":
            x["format_note"] = "m4a"
            videos.append(x)
        res = x["format"].split("-")[1].strip().split(" ")[0]
        if (
            any(s in x["format_note"] for s in ALLOWED_VIDEO_SIZES)
            and "throttled" not in x["format"].lower()
            and x["filesize"] is not None
        ):
            videos.append(x)
    for v in videos:
        try:
            res = v["format"].split("-")[1].strip().split(" ")[0]
            if res in selected:
                if (
                    v["filesize"] < selected[res]["filesize"]
                    or v["fps"] > selected[res]["fps"]
                ):
                    selected[res] = v
            if res == "m4a":
                selected[res] = v
            else:
                selected[res] = v
        except:
            pass
    return selected


def json_response(success, data, message, status_code):
    return (
        jsonify({"success": success, "data": data, "message": message}),
        status_code,
    )


def has_requester_active_task(ip):
    has_active_task = False
    if redis_instance:
        for task in redis_instance.scan_iter(match="celery-trim-task*"):
            task_id = task.decode("utf-8")
            task_details = json.loads(redis_instance.get(task_id).decode("utf-8"))
            if task_details["ip"] == ip:
                if (
                    celery.AsyncResult(task_details["task_id"], app=celery).status
                    == "PENDING"
                ):
                    has_active_task = True
    return has_active_task

def calculate_trimmed_file_size(video_info, quality, start, end):
    final_size_is_below_limit = False
    try:
        total_length = video_info["duration"]
        for format in video_info['formats']:
            if format['format_id'] == quality:
                video_file_size = format['filesize']/1024/1024
                video_size_per_sec = video_file_size/total_length
                trimmed_video_size = int((end - start) * video_size_per_sec)
                if trimmed_video_size > int(TRIMMED_FILE_SIZE_LIMIT_MB):
                    final_size_is_below_limit = False
                else:
                    final_size_is_below_limit = True
    except Exception as e:
        print(e)
        final_size_is_below_limit = False
    return final_size_is_below_limit

def video_size_below_limit(video_info, quality):
    video_size_below_limit = False
    try:
        for format in video_info['formats']:
            if format['format_id'] == quality:
                video_file_size = format['filesize']/1024/1024
                if video_file_size > int(VIDEO_FILE_SIZE_LIMIT_MB):
                    video_size_below_limit = False
                else:
                    video_size_below_limit = True
    except Exception as e:
        print(e)
        video_size_below_limit = False
    return video_size_below_limit


@app.route("/")
def home():
    return render_template("trimpage.html")


@app.route("/static/<path:path>")
def send_static(path):
    return send_from_directory("templates/static/", path)


@app.route("/getvideodetails", methods=["POST"])
def get_video_details():
    if request.json is not None:
        url = request.json["url"]
        if url is not None:
            try:
                # Use extract_info with a timeout
                request_video_result = ydlr.extract_info(url, download=False, process=False)
                # If the video info wasn't extracted, try with yt-dlp's normal processing
                if not request_video_result or "id" not in request_video_result:
                    request_video_result = ydlr.extract_info(url, download=False)
                # Ensure we have the formats data
                if not request_video_result.get('formats'):
                    request_video_result = ydlr.extract_info(url, download=False, force_process=True)
                response = process_video_request(request_video_result)
                return json_response(
                    True,
                    {"formats": response, "videoID": request_video_result["id"]},
                    None,
                    200,
                )
            except yt_dlp.utils.DownloadError as e:
                print(f"Download error: {e}")
                return json_response(False, None, f"{url} is not downloadable", 400)                
            except Exception as e:
                print(f"Error extracting video info: {e}")
                return json_response(False, None, f"{url} is not a valid URL or video", 400)
        return json_response(False, None, "Please provide a valid URL", 400)
    else:
        return json_response(False, None, "Please provide a valid URL", 400)


@app.route("/trim", methods=["POST"])
def trim():
    requester_ip = request.remote_addr
    if has_requester_active_task(requester_ip):
        return json_response(
            False,
            None,
            "You have an active task in the queue, please wait for it to complete!",
            400,
        )
    else:
        url = request.args.get("url")
        quality = request.args.get("quality")
        start = request.args.get("start")
        end = request.args.get("end")
        if url and quality and start and end is not None:
            try:
                video_info = ydlr.extract_info(url, download=False)
                is_video_below_limit = video_size_below_limit(video_info, quality)
                if not is_video_below_limit:
                    return json_response(
                        False,
                        None,
                        f"The file size of the video is above the limit of {VIDEO_FILE_SIZE_LIMIT_MB}MB. Please try again with a lower quality or a shorter video.",
                        400,
                    )
                is_trimmed_below_limit = calculate_trimmed_file_size(video_info, quality, int(start), int(end))
                if not is_trimmed_below_limit:
                    return json_response(
                        False,
                        None,
                        f"The file size of the trimmed video is going to be above the limit of {TRIMMED_FILE_SIZE_LIMIT_MB}MB. Please try again with a smaller range or lower quality.",
                        400,
                    )
                elif is_trimmed_below_limit:
                    task = celery.send_task(
                        TRIM_TASK_NAME,
                        kwargs={
                            "url": url,
                            "quality": quality,
                            "start": start,
                            "end": end,
                            "ip": requester_ip,
                        },
                    )
                    if redis_instance:
                        redis_instance.set(
                            "celery-trim-task-" + task.id,
                            json.dumps({"ip": requester_ip, "task_id": task.id}),
                        )
                    return json_response(True, task.id, "Task successfully added!", 200)
            except Exception as e:
                print(e)
                return json_response(
                    False,
                    None,
                    f"Something went wrong, please try again later!",
                    400,
                )
        return json_response(
            False, None, "Please provide 'url, quality, start and end' data!", 400
        )


@app.route("/uploadfromworker", methods=["POST"])
def upload_file():
    if request.method == "POST":
        secret_key = request.headers.get("secret_key")
        if secret_key == UPLOAD_SECRET_KEY:
            if "file" not in request.files:
                return json_response(False, None, "No file part", 400)
            file = request.files["file"]
            if file:
                file_name = secure_filename(file.filename)
                save_path = os.path.join(app.config["UPLOAD_FOLDER"], file_name)
                if os.path.isfile(save_path):
                    os.remove(save_path)
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], file_name))
                return json_response(True, file_name, "File uploaded successfully", 200)
        else:
            return json_response(False, None, "Invalid secret key", 400)


@app.route("/dlvideo/<task_id>")
def get_video(task_id):
    try:
        status = celery.AsyncResult(task_id, app=celery)
        if status.state.lower() == "success":
            return send_from_directory(
                "videos/", path=status.result["data"], as_attachment=True
            )
        else:
            abort(404)
    except FileNotFoundError:
        abort(404)


@app.route("/status/<task_id>")
def get_status(task_id):
    status = celery.AsyncResult(task_id, app=celery)
    return json_response(True, status.state, None, 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
