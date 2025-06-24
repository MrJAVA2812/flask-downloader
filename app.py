from flask import Flask, request, jsonify, Response
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re
import requests  # <-- ajout pour requêtes HTTP HEAD
from pathlib import Path

app = Flask(__name__)
CORS(app)

DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

COOKIES_SRC = str(Path.home() / "Downloads/www.youtube.com_cookies")
COOKIES_DEST = os.path.join(DOWNLOAD_FOLDER, "cookies.txt")


def sanitize_filename(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9_\-\.]+", "_", name)
    return name[:100].rstrip("_.")


def get_remote_filesize(url):
    try:
        resp = requests.head(url, allow_redirects=True, timeout=5)
        size = resp.headers.get('Content-Length')
        if size and size.isdigit():
            return int(size)
    except Exception as e:
        print(f"Erreur HEAD pour {url} : {e}")
    return None


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    content_type = data.get("type", "video")

    if not url:
        return jsonify({"error": "Aucun lien fourni"}), 400

    # Mise à jour du cookies.txt si présent
    if os.path.exists(COOKIES_SRC):
        try:
            with open(COOKIES_SRC, 'rb') as src, open(COOKIES_DEST, 'wb') as dst:
                dst.write(src.read())
            os.remove(COOKIES_SRC)
            print("✅ cookies.txt mis à jour.")
        except Exception as e:
            print("❌ Erreur cookies:", e)

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "no_warnings": True,
        "cookiefile": COOKIES_DEST if os.path.exists(COOKIES_DEST) else None
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if info.get("is_live") or not info.get("formats"):
            return jsonify({"error": "Vidéo non disponible"}), 400

        formats = info["formats"]
        filtered = []
        seen = set()

        if content_type == "video":
            for fmt in formats:
                ext = fmt.get("ext")
                height = fmt.get("height")
                vcodec = fmt.get("vcodec")
                acodec = fmt.get("acodec")
                if ext in ["mp4", "webm"] and height and vcodec != "none":
                    key = (height, ext)
                    if key not in seen:
                        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
                        # Si filesize absent, essayer HEAD request
                        if not filesize and fmt.get("url"):
                            filesize = get_remote_filesize(fmt["url"])
                        filtered.append({
                            "format_id": fmt["format_id"],
                            "ext": ext,
                            "resolution": f"{height}p",
                            "filesize": filesize
                        })
                        seen.add(key)

        else:  # audio
            for fmt in formats:
                vcodec = fmt.get("vcodec")
                if vcodec == "none":
                    ext = fmt.get("ext")
                    abr = fmt.get("abr", 0)
                    key = (abr, ext)
                    if key not in seen:
                        filesize = fmt.get("filesize") or fmt.get("filesize_approx")
                        if not filesize and fmt.get("url"):
                            filesize = get_remote_filesize(fmt["url"])
                        filtered.append({
                            "format_id": fmt["format_id"],
                            "ext": ext,
                            "abr": f"{abr} kbps",
                            "filesize": filesize
                        })
                        seen.add(key)

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
    raw_title = data.get("title", "video")

    if not url or not format_id:
        return jsonify({"error": "Paramètres manquants"}), 400

    title = sanitize_filename(raw_title)
    ext = "mp4" if content_type == "video" else "mp3"
    output_path = os.path.join(DOWNLOAD_FOLDER, f"{uuid.uuid4()}_original.{ext}")

    ydl_opts = {
        "quiet": True,
        "outtmpl": output_path,
        "format": f"{format_id}+bestaudio/best" if content_type == "video" else format_id,
        "merge_output_format": ext,
        "nocheckcertificate": True,
        "no_warnings": True,
        "noplaylist": True,
        "cookiefile": COOKIES_DEST if os.path.exists(COOKIES_DEST) else None
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        def generate():
            total = os.path.getsize(output_path)
            sent = 0
            last_percent = -1
            chunk_size = 8192
            with open(output_path, "rb") as f:
                while chunk := f.read(chunk_size):
                    sent += len(chunk)
                    percent = int((sent / total) * 100)
                    if percent != last_percent:
                        print(f"⏳ Envoi : {percent}%", end="\r", flush=True)
                        last_percent = percent
                    yield chunk
            try:
                os.remove(output_path)
                print(f"\n✅ {output_path} supprimé après envoi.")
            except Exception as e:
                print(f"\n⚠️ Erreur suppression : {e}")

        return Response(
            generate(),
            mimetype="video/mp4" if content_type == "video" else "audio/mpeg",
            headers={
                "Content-Disposition": f"attachment; filename={title}.{ext}",
                "Content-Length": str(os.path.getsize(output_path))
            }
        )

    except Exception as e:
        return jsonify({"error": f"Téléchargement échoué : {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
