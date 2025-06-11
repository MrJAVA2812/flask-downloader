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
import logging
from urllib.parse import urlparse

# Configuration du logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

app = Flask(__name__)
CORS(app)

# Dossier temporaire pour stocker les fichiers téléchargés
DOWNLOAD_FOLDER = "downloads"
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Durée de vie max des fichiers (en secondes)
FILE_LIFETIME = 600  # 10 minutes

# Configuration des cookies
COOKIE_FILES = {
    "youtube.com": "cookies.txt",
    "www.youtube.com": "cookies.txt",
    "facebook.com": "cookies.txt",
    "www.facebook.com": "cookies.txt",
    "instagram.com": "cookies.txt",
    "www.instagram.com": "cookies.txt",
    "tiktok.com": "cookies.txt",
    "www.tiktok.com": "cookies.txt"
}


def get_cookie_file(url):
    hostname = urlparse(url).hostname
    return COOKIE_FILES.get(hostname)


# Configuration de yt-dlp
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "nocheckcertificate": True,
    "noplaylist": True,
}


def get_file_size_in_mb(path: str) -> float:
    try:
        size_bytes = os.path.getsize(path)
        return size_bytes / (1024 * 1024)
    except FileNotFoundError:
        logging.error(f"Fichier non trouvé : {path}")
        return 0.0
    except Exception as e:
        logging.error(f"Erreur lors de la récupération de la taille du fichier : {e}")
        return 0.0


def sanitize_filename(name: str) -> str:
    try:
        name = name.lower().strip()
        name = re.sub(r"[^a-z0-9_\-\.]+", "_", name)
        return name[:100].rstrip("_.")  # max 100 caractères
    except Exception as e:
        logging.error(f"Erreur lors de la désinfection du nom de fichier : {e}")
        return "default_filename"


def cleanup_old_files(folder: str, max_age_seconds: int):
    now = time.time()
    for filename in os.listdir(folder):
        path = os.path.join(folder, filename)
        try:
            if os.path.isfile(path) and now - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
                logging.info(f"Fichier supprimé : {path}")
        except Exception as e:
            logging.error(f"Erreur lors de la suppression du fichier : {path} - {e}")


@app.route("/download", methods=["POST"])
def download():
    data = request.get_json()
    url = data.get("url")
    content_type = data.get("type", "video")

    if not url:
        return jsonify({"error": "Aucun lien fourni"}), 400

    ydl_opts = YDL_OPTS.copy()
    ydl_opts["skip_download"] = True

    cookie_file = get_cookie_file(url)
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file
        logging.info(f"Utilisation du fichier de cookies : {cookie_file}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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

                if ext in ["webm", "mp4"] and height and height >= 200 and vcodec != "none":
                    key = (height, ext)
                    if key not in seen:
                        filtered.append({
                            "format_id": fmt["format_id"],
                            "ext": ext,
                            "resolution": f"{height}p",
                            "vcodec": vcodec,
                            "height": height
                        })
                        seen.add(key)

            if not filtered:
                return jsonify({
                    "error": "Aucun format (200p ou plus) disponible.",
                    "thumbnail": info.get("thumbnail")
                }), 400

        elif content_type == "audio":
            best_audio = None
            best_bitrate = 0

            for fmt in formats:
                ext = fmt.get("ext")
                abr = fmt.get("abr")
                vcodec = fmt.get("vcodec")

                if ext in ["mp3", "m4a", "webm"] and vcodec == "none":
                    if abr and abr > best_bitrate:
                        best_bitrate = abr
                        best_audio = {
                            "format_id": fmt["format_id"],
                            "ext": "MP3",
                            "abr": abr,
                            "vcodec": vcodec
                        }

            if not best_audio:
                return jsonify({
                    "error": "Aucun format audio disponible.",
                    "thumbnail": info.get("thumbnail")
                }), 400

            filtered.append(best_audio)

        return jsonify({
            "title": info.get("title"),
            "thumbnail": info.get("thumbnail"),
            "formats": filtered
        })

    except Exception as e:
        logging.error(f"Erreur lors de l'extraction des informations : {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/combine", methods=["POST"])
def combine():
    data = request.get_json()
    url = data.get("url")
    format_id = data.get("format_id")
    content_type = data.get("type", "video")
    compress_to = int(data.get("compress_to", 1500))

    if not url or not format_id:
        return jsonify({"error": "Paramètres manquants"}), 400

    # Validation du type de contenu
    if content_type not in ["video", "audio"]:
        return jsonify({"error": "Type de contenu non valide. Doit être 'video' ou 'audio'."}), 400

    cookie_file = get_cookie_file(url)

    try:
        ydl_opts = YDL_OPTS.copy()
        if cookie_file and os.path.exists(cookie_file):
            ydl_opts["cookiefile"] = cookie_file
            logging.info(f"Utilisation du fichier de cookies : {cookie_file}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        logging.error(f"Impossible d'extraire info vidéo: {str(e)}")
        return jsonify({"error": f"Impossible d'extraire info vidéo: {str(e)}"}), 500

    title = info.get("title") or "video"
    safe_title = sanitize_filename(title)

    original_ext = "mp4" if content_type == "video" else "mp3"
    original_filename = os.path.join(DOWNLOAD_FOLDER, f"{uuid.uuid4()}_original.{original_ext}")
    final_filename = os.path.join(DOWNLOAD_FOLDER, f"{safe_title}.{original_ext}")

    ydl_opts = YDL_OPTS.copy()
    ydl_opts["outtmpl"] = original_filename
    ydl_opts["format"] = f"{format_id}+bestaudio/best" if content_type == "video" else format_id
    ydl_opts["merge_output_format"] = original_ext
    if cookie_file and os.path.exists(cookie_file):
        ydl_opts["cookiefile"] = cookie_file
        logging.info(f"Utilisation du fichier de cookies : {cookie_file}")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if content_type == "video":
            try:
                probe_cmd = [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=height",
                    "-of", "json",
                    original_filename
                ]
                probe_result = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
                height_data = json.loads(probe_result.stdout)
                height = height_data["streams"][0]["height"]
            except (subprocess.CalledProcessError, KeyError, json.JSONDecodeError) as e:
                logging.error(f"Erreur lors de la récupération de la hauteur de la vidéo : {e}")
                height = compress_to + 1  # Force la compression

            file_size_mb = get_file_size_in_mb(original_filename)

            if height > compress_to and file_size_mb >= 100:
                try:
                    compress_cmd = [
                        "ffmpeg", "-i", original_filename,
                        "-vf", f"scale=-2:'min({compress_to},ih)'",
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        final_filename
                    ]
                    subprocess.run(compress_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    os.remove(original_filename)
                except subprocess.CalledProcessError as e:
                    logging.error(f"Erreur lors de la compression de la vidéo : {e}")
                    os.rename(original_filename, final_filename)  # Conserver l'original en cas d'échec
            else:
                os.rename(original_filename, final_filename)
        else:
            os.rename(original_filename, final_filename)

        return jsonify({"url": f"/file/{os.path.basename(final_filename)}"})

    except Exception as e:
        logging.error(f"Téléchargement échoué : {str(e)}")
        return jsonify({"error": f"Téléchargement échoué : {str(e)}"}), 500


@app.route("/file/<path:filename>")
def serve_file(filename):
    """
    Sert le fichier et le supprime après l'envoi.
    """
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        return jsonify({"error": "Fichier introuvable"}), 404

    try:
        with open(file_path, 'rb') as f:
            data = f.read()

        os.remove(file_path)  # Supprime après lecture
        logging.info(f"Fichier servi et supprimé : {filename}")

        return Response(
            io.BytesIO(data),
            mimetype='application/octet-stream',
            headers={
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

    except FileNotFoundError:
        logging.error(f"Fichier non trouvé lors de la tentative de service : {filename}")
        return jsonify({"error": "Fichier introuvable"}), 404
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi : {str(e)}")
        return jsonify({"error": f"Erreur lors de l'envoi : {str(e)}"}), 500

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



if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
