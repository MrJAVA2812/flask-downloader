import os
import json
import yt_dlp
import subprocess
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

COOKIE_FILES = {
    "youtube.com": "cookies.txt",
    "www.youtube.com": "cookies.txt",
    "facebook.com": "cookies_facebook.txt",
    "www.facebook.com": "cookies_facebook.txt"
}

def get_cookie_file(url):
    hostname = urlparse(url).hostname
    return COOKIE_FILES.get(hostname)

@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "URL manquante"}), 400

    cookie_file = get_cookie_file(url)
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "forcejson": True,
        "extract_flat": False
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

    except Exception:
        video_id = None
        if "youtube.com" in url and "v=" in url:
            video_id = url.split("v=")[-1].split("&")[0]
        elif "youtu.be" in url:
            video_id = url.split("/")[-1].split("?")[0]

        thumbnail_url = f"http://img.youtube.com/vi/{video_id}/0.jpg" if video_id else None
        return jsonify({
            "error": "Impossible d'extraire la vidéo. Affichage de la miniature uniquement.",
            "thumbnail_only": True,
            "thumbnail": thumbnail_url
        })


@app.route("/combine", methods=["POST"])
def combine():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    only_audio = data.get("only_audio", False)

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    cookie_file = get_cookie_file(url)
    filename_base = f"video_{str(hash(url))}"
    output_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}.mp4")
    audio_path = os.path.join(DOWNLOAD_FOLDER, f"{filename_base}.mp3")

    try:
        # Étape 1 : vérifier que le format existe réellement
        ydl_probe_opts = {"quiet": True, "skip_download": True, "forcejson": True}
        if cookie_file and os.path.exists(cookie_file):
            ydl_probe_opts["cookiefile"] = cookie_file

        with yt_dlp.YoutubeDL(ydl_probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            available_format_ids = [f["format_id"] for f in info.get("formats", [])]

        if format_id and format_id not in available_format_ids:
            return jsonify({"error": "Le format demandé n'est pas disponible."}), 400

        # Étape 2 : config du téléchargement
        ydl_opts = {
            "outtmpl": os.path.join(DOWNLOAD_FOLDER, filename_base + ".%(ext)s"),
            "merge_output_format": "mp4",
            "quiet": True,
        }

        if cookie_file and os.path.exists(cookie_file):
            ydl_opts["cookiefile"] = cookie_file

        if only_audio:
            ydl_opts["format"] = "bestaudio"
            ydl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
            output_file = audio_path
        elif format_id:
            ydl_opts["format"] = format_id + "+bestaudio/best"
            output_file = output_path
        else:
            return jsonify({"error": "Format vidéo manquant"}), 400

        # Étape 3 : téléchargement
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        return send_file(output_file, as_attachment=True)

    except Exception as e:
        return jsonify({"error": f"Erreur de téléchargement : {str(e)}"}), 500

    finally:
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except:
            pass


@app.route("/check_cookies")
def check_cookies():
    test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    cookie_file = "cookies.txt"
    cmd = [
        "yt-dlp", "--cookies", cookie_file, "--dump-json", test_url
    ]

    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        if result.returncode == 0:
            return jsonify({"status": "success", "message": "✅ Les cookies sont valides."})
        else:
            return jsonify({"status": "error", "message": f"❌ Erreur : {result.stderr.strip()}"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"⚠️ Exception : {str(e)}"})


@app.route("/downloads/<path:filename>")
def serve_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
