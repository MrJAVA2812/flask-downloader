import os
import json
import yt_dlp
import subprocess
import logging
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from urllib.parse import urlparse
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
CORS(app)

# Download folder
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Cookie files
COOKIE_FILES = {
    "youtube.com": "www.youtube.com_cookies.txt",
    "www.youtube.com": "www.youtube.com_cookies.txt",
    "facebook.com": "cookies.txt",
    "www.facebook.com": "cookies.txt",
    "instagram.com": "cookies.txt",
    "www.instagram.com": "cookies.txt",
    "tiktok.com": "cookies.txt",
    "www.tiktok.com": "cookies.txt"
}

def check_youtube_cookies():
    try:
        ydl_opts = {
            'cookiefile': 'www.youtube.com_cookies.txt',
            'quiet': True,
            'skip_download': True,
            'forcejson': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info("https://www.youtube.com/feed/library", download=False)
        return True
    except Exception as e:
        logging.error(f"Cookie error: {e}")
        return False

@app.route("/check_cookies")
def check_cookies():
    if check_youtube_cookies():
        return jsonify({"status": "valid", "message": "Cookies valid: YouTube connection successful."})
    else:
        return jsonify({"status": "invalid", "message": "Invalid or expired cookies. Please replace them."}), 401

# Helper function to get cookie file
def get_cookie_file(url):
    hostname = urlparse(url).hostname
    return COOKIE_FILES.get(hostname)

def sanitize_filename(filename):
    """Sanitize a filename to remove invalid characters."""
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)  # Replace reserved characters with underscores
    filename = filename.replace('#', '_')  # Replace '#' with underscore
    filename = filename.strip()  # Remove leading/trailing whitespace
    return filename

# Route to fetch video formats
@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    cookie_file = get_cookie_file(url)
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "forcejson": True,
        "extract_flat": False,
        "nocheckcertificate": True,  # Handle certificate issues
    }

    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get("formats", [])
            filtered_formats = []
            seen = set()

            for f in formats:
                ext = f.get("ext")
                resolution = f.get("height")
                format_id = f.get("format_id")
                if ext == "mp4" and resolution and 100 <= resolution <= 3500:
                    key = (resolution, ext)
                    if key not in seen:
                        seen.add(key)
                        filtered_formats.append({
                            "format_id": format_id,
                            "ext": ext,
                            "resolution": f"{resolution}p",
                            "filesize": f.get("filesize", 0)
                        })

            return jsonify({
                "title": info.get("title"),
                "thumbnail": info.get("thumbnail"),
                "formats": filtered_formats,
                "has_audio": any(f.get("acodec") != "none" for f in formats)
            })

    except Exception as e:
        logging.exception("Error extracting video info")
        video_id = None
        if "youtube.com" in url and "v=" in url:
            video_id = url.split("v=")[-1].split("&")[0]
        elif "youtu.be" in url:
            video_id = url.split("/")[-1].split("?")[0]

        thumbnail_url = f"http://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
        return jsonify({
            "error": f"Unable to extract video. Displaying thumbnail only. Error: {str(e)}",
            "thumbnail_only": True,
            "thumbnail": thumbnail_url
        })

# Route to combine video and audio
@app.route("/combine", methods=["POST"])
def combine():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    only_audio = data.get("only_audio", False)

    if not url:
        return jsonify({"error": "Missing URL"}), 400

    cookie_file = get_cookie_file(url)
    temp_video_path = None
    temp_audio_path = None

    try:
        # Step 1: Extract video info to get the title
        ydl_opts_info = {
            "quiet": True,
            "skip_download": True,
            "forcejson": True,
            "extract_flat": False,
            "nocheckcertificate": True,
        }
        if cookie_file and os.path.exists(cookie_file):
            ydl_opts_info["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
            info = ydl.extract_info(url, download=False)
            video_title = info.get("title", "default_filename")
            sanitized_title = sanitize_filename(video_title)

        # Step 2: Configure download
        ydl_opts = {
            "quiet": True,
            "nocheckcertificate": True,
        }

        if cookie_file and os.path.exists(cookie_file):
            ydl_opts["cookiefile"] = cookie_file

        if only_audio:
            filename_base = f"{sanitized_title}"
            output_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}.mp3")
            ydl_opts["outtmpl"] = output_path
            ydl_opts["format"] = "bestaudio/best"  # Try bestaudio, fallback to best

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                logging.error(f"Audio download error: {e}")
                return jsonify({"error": f"Audio download error: {str(e)}. Try downloading the video with combined audio and video."}), 500

        elif format_id:
            filename_base = f"{sanitized_title}"
            output_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}.mp4")
            temp_video_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}_video.mp4")
            temp_audio_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}_audio.mp3")

            # Download video
            ydl_opts_video = {
                "quiet": True,
                "outtmpl": temp_video_path,
                "format": format_id,
                "cookiefile": cookie_file if cookie_file and os.path.exists(cookie_file) else None,
                "nocheckcertificate": True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                logging.error(f"Video download error: {e}")
                return jsonify({"error": f"Video download error: {str(e)}"}), 500

            # Download audio
            ydl_opts_audio = {
                "quiet": True,
                "outtmpl": temp_audio_path,
                "format": "bestaudio/best",  # Try bestaudio, fallback to best
                "cookiefile": cookie_file if cookie_file and os.path.exists(cookie_file) else None,
                "nocheckcertificate": True,
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
                    ydl.download([url])
            except yt_dlp.utils.DownloadError as e:
                logging.error(f"Audio download error: {e}")
                return jsonify({"error": f"Audio download error: {str(e)}. Try downloading the video with combined audio and video."}), 500

            # Combine audio and video using ffmpeg
            cmd = [
                "ffmpeg",
                "-i", temp_video_path,
                "-i", temp_audio_path,
                "-c", "copy",
                output_path,
                "-y"  # Overwrite output file if it exists
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                logging.error(f"FFmpeg command failed: {e.stderr}")
                return jsonify({"error": f"FFmpeg command failed: {e.stderr}"}), 500
        else:
            return jsonify({"error": "Missing video format"}), 400

        return send_file(output_path, as_attachment=True, download_name=f"{sanitized_title}{os.path.splitext(output_path)[1]}")

    except Exception as e:
        logging.exception("Download or combine error")
        return jsonify({"error": f"Download error: {str(e)}"}), 500

    finally:
        # Clean up temporary files
        try:
            if temp_video_path and os.path.exists(temp_video_path):
                os.remove(temp_video_path)
            if temp_audio_path and os.path.exists(temp_audio_path):
                os.remove(temp_audio_path)
        except Exception as e:
            logging.error(f"Error removing temporary files: {e}")

# Route to serve files
@app.route("/downloads/<path:filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
