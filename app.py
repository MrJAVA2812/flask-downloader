import os
from flask import Flask, request, jsonify, send_file
import yt_dlp
import uuid
import shutil

app = Flask(__name__)
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

@app.route("/")
def index():
    return "Bienvenue sur le téléchargeur vidéo Flask !"

@app.route("/download", methods=["POST"])
def download_video():
    data = request.get_json()
    video_url = data.get("url")

    if not video_url:
        return jsonify({"error": "Aucun lien fourni"}), 400

    video_id = str(uuid.uuid4())
    temp_dir = os.path.join(DOWNLOAD_DIR, video_id)
    os.makedirs(temp_dir, exist_ok=True)

    ydl_opts = {
        "outtmpl": os.path.join(temp_dir, "%(title)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            filename = ydl.prepare_filename(info).replace(".webm", ".mp4").replace(".mkv", ".mp4")

        return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Port fourni par Render
    app.run(host="0.0.0.0", port=port)        # Nécessaire pour Render
