import yt_dlp

COOKIES_FILE = "cookies.txt"

def test_yt_info(url):
    ydl_opts = {
        "quiet": False,
        "skip_download": True,
        "no_warnings": True,
        "cookiefile": COOKIES_FILE,
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            print("Titre :", info.get("title"))
            print("Formats disponibles :")
            for f in info.get("formats", [])[:5]:
                print(f"  format_id: {f.get('format_id')}, ext: {f.get('ext')}, resolution: {f.get('height')}p")
    except Exception as e:
        print("Erreur:", e)

if __name__ == "__main__":
    # Mets ici un lien YouTube à tester (public ou privé selon cookies)
    video_url = "https://www.youtube.com/watch?v=OG3YQ-UL1W4"
    test_yt_info(video_url)
