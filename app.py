from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import uuid
import subprocess
import json
import re
import io
import time

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

FILE_LIFETIME = 600  # 10 minutes


def get_file_size_in_mb(path):
    return os.path.getsize(path) / (1024 * 1024)


def sanitize_filename(name):
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_\-\.]+", "_", name)
    return name[:100].rstrip("_.")


def cleanup_old_files():
    now = time.time()
    for filename in os.listdir(DOWNLOAD_FOLDER):
        path = os.path.join(DOWNLOAD_FOLDER, filename)
        if os.path.isfile(path) and now - os.path.getmtime(path) > FILE_LIFETIME:
            os.remove(path)


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    content_type = data.get("type", "video")

    if not url:
        return jsonify({"error": "Aucun lien fourni"}), 400

    cleanup_old_files()

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        if info.get("_type") == "url" or info.get("is_live") or not info.get("formats"):
            return jsonify({
                "error": "Vidéo non disponible",
                "thumbnail": info.get("thumbnail")
            }), 400

        formats = info["formats"]
        filtered = []
        seen = set()

        if content_type == "video":
            for fmt in formats:
                height = fmt.get("height")
                ext = fmt.get("ext")
                vcodec = fmt.get("vcodec")

                if ext in ["webm", "mp4"] and height and height >= 720 and vcodec != "none":
                    key = (height, ext)
                    if key not in seen:
                        filtered.append({
                            "format_id": fmt["format_id"],
                            "ext": ext,
                            "resolution": f"{height}p",
                            "height": height
                        })
                        seen.add(key)

            if not filtered:
                return jsonify({
                    "error": "Aucun format HD (720p ou plus) disponible.",
                    "thumbnail": info.get("thumbnail")
                }), 400

        elif content_type == "audio":
            best_audio = max(
                (f for f in formats if f.get("vcodec") == "none" and f.get("abr") and f.get("ext") in ["mp3", "m4a", "webm"]),
                key=lambda f: f["abr"],
                default=None
            )
            if not best_audio:
                return jsonify({
                    "error": "Aucun format audio disponible.",
                    "thumbnail": info.get("thumbnail")
                }), 400

            filtered.append({
                "format_id": best_audio["format_id"],
                "ext": "mp3",
                "abr": best_audio.get("abr")
            })

        return jsonify({
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "formats": filtered
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/combine", methods=["POST"])
def combine():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    content_type = data.get("type", "video")
    compress_to = int(data.get("compress_to", 1080))

    if not url or not format_id:
        return jsonify({"error": "Paramètres manquants"}), 400

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)

        title = info.get("title", "video")
        safe_title = sanitize_filename(title)
        ext = "mp4" if content_type == "video" else "mp3"
        original = os.path.join(DOWNLOAD_FOLDER, f"{uuid.uuid4()}_original.{ext}")
        final = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}.{ext}")

        ydl_opts = {
            "quiet": True,
            "outtmpl": original,
            "format": f"{format_id}+bestaudio/best" if content_type == "video" else format_id,
            "merge_output_format": ext,
            "nocheckcertificate": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if content_type == "video":
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=height",
                "-of", "json",
                original
            ]
            result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            height = json.loads(result.stdout)["streams"][0]["height"]
            size = get_file_size_in_mb(original)

            if height > compress_to and size >= 100:
                compress_cmd = [
                    "ffmpeg", "-i", original,
                    "-vf", f"scale=-2:'min({compress_to},ih)'",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "192k",
                    final
                ]
                subprocess.run(compress_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                os.remove(original)
            else:
                os.rename(original, final)
        else:
            os.rename(original, final)

        return jsonify({"url": f"/file/{os.path.basename(final)}"})

    except Exception as e:
        return jsonify({"error": f"Téléchargement échoué : {str(e)}"}), 500


@app.route("/file/<path:filename>")
def serve_file(filename):
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Fichier introuvable"}), 404

    try:
        with open(file_path, 'rb') as f:
            data = f.read()
        os.remove(file_path)
        return Response(
            io.BytesIO(data),
            mimetype='application/octet-stream',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return jsonify({"error": f"Erreur lors de l'envoi : {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
