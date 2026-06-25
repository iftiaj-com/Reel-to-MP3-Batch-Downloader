import os
import re
import time
import random
import shutil
import zipfile
import tempfile
import streamlit as st
import yt_dlp
import requests
from pathlib import Path

# ─────────────────────────── CONFIGURATION ────────────────────────────────────

# Delay between each download attempt (seconds)
MIN_DELAY       = 2    # seconds
MAX_DELAY       = 4    # seconds

# Retry settings
MAX_RETRIES     = 2
RETRY_BASE      = 5    # base seconds for exponential backoff

# Audio quality
AUDIO_QUALITY   = "192"   # kbps

# Free proxy API for rotation fallback
FREE_PROXY_API  = "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps&anonymityLevel=elite%2Canonymous"

# Regex for extracting Instagram Reels/Posts/TV URLs from unstructured text
_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[a-zA-Z0-9_-]+/?(?:\?[^\s]*)?"
)

# ─────────────────────────── SESSION STATE ────────────────────────────────────

if "step" not in st.session_state:
    st.session_state.step = "input"  # input -> processing -> done
if "urls" not in st.session_state:
    st.session_state.urls = []
if "downloaded_files" not in st.session_state:
    st.session_state.downloaded_files = [] # list of dicts: {"name": ..., "path": ...}
if "zip_path" not in st.session_state:
    st.session_state.zip_path = None
if "temp_dir" not in st.session_state:
    st.session_state.temp_dir = None

# ─────────────────────────── PROXY ROTATION ───────────────────────────────────

@st.cache_data(ttl=300, show_spinner=False)
def fetch_free_proxies() -> list[str]:
    """Download a list of free elite/anonymous HTTPS proxies."""
    proxies: list[str] = []
    try:
        resp = requests.get(FREE_PROXY_API, timeout=10)
        data = resp.json().get("data", [])
        for item in data:
            ip   = item.get("ip", "")
            port = item.get("port", "")
            prot = (item.get("protocols") or ["http"])[0]
            if ip and port:
                proxies.append(f"{prot}://{ip}:{port}")
    except Exception:
        pass
    random.shuffle(proxies)
    return proxies

class ProxyRotator:
    def __init__(self):
        self._proxies = fetch_free_proxies()
        self._index = 0

    def current(self) -> str | None:
        if self._proxies:
            return self._proxies[self._index % len(self._proxies)]
        return None

    def rotate(self):
        if self._proxies:
            self._index += 1

# ─────────────────────────── DOWNLOAD ENGINE ──────────────────────────────────

def clean_url(url: str) -> str:
    """Normalise to bare canonical form, stripping share tracking params."""
    m = re.search(r"/(reel|p|tv)/([a-zA-Z0-9_-]+)", url)
    if m:
        return f"https://www.instagram.com/{m.group(1)}/{m.group(2)}/"
    return url

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def download_one(url: str, output_folder: str, proxy: str | None, status_box) -> str | None:
    """
    Downloads one reel, converts it to MP3, and returns the path to the MP3 file.
    Returns None on failure.
    """
    cleaned = clean_url(url)
    ydl_opts: dict = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": AUDIO_QUALITY,
        }],
        "outtmpl": os.path.join(output_folder, "%(id)s - %(title).80s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "user_agent": random.choice(_USER_AGENTS),
        "socket_timeout": 20,
        "retries": 1,
        "fragment_retries": 1,
        "http_headers": {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "DNT": "1",
        },
    }

    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        # Before downloading, check folder contents to find out what file got created
        existing_before = set(Path(output_folder).glob("*.mp3"))
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(cleaned, download=True)
            uploader = info.get("uploader") or info.get("uploader_id") or "instagram_user"
            
        if uploader.startswith("by."): # handle usernames like by.nuriaa
            pass
            
        existing_after = set(Path(output_folder).glob("*.mp3"))
        new_files = existing_after - existing_before
        if new_files:
            downloaded_file = list(new_files)[0]
            random_num = random.randint(100000, 999999)
            new_name = f"iftiaj-com-{random_num}-audio by {uploader}.mp3"
            new_path = downloaded_file.parent / new_name
            os.rename(downloaded_file, new_path)
            return str(new_path)
        return None
    except Exception as exc:
        status_box.warning(f"Error during download: {exc}")
        return None

def reset_state():
    if st.session_state.temp_dir and os.path.exists(st.session_state.temp_dir):
        try:
            shutil.rmtree(st.session_state.temp_dir)
        except Exception:
            pass
    st.session_state.step = "input"
    st.session_state.urls = []
    st.session_state.downloaded_files = []
    st.session_state.zip_path = None
    st.session_state.temp_dir = None

# ─────────────────────────── STREAMLIT UI ─────────────────────────────────────

# Custom page config for clean, responsive, modern aesthetics
st.set_page_config(
    page_title="Reel to MP3 Batch Downloader",
    page_icon="🎵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Custom Styling (sleek modern fonts, padding, glassmorphism hints)
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: 600px;
    }
    div.stButton, div.stDownloadButton {
        width: 100% !important;
    }
    button[data-testid="baseButton-primary"] {
        background-color: #ff4b4b;
        color: white !important;
        border-radius: 8px !important;
        border: none !important;
        padding: 0.6rem 1.5rem !important;
        font-weight: 600 !important;
        width: fit-content !important;
        margin: 0.5rem auto !important;
        display: block !important;
        transition: all 0.3s ease !important;
    }
    button[data-testid="baseButton-primary"]:hover {
        background-color: #ff3333;
        box-shadow: 0 4px 12px rgba(255, 75, 75, 0.3) !important;
        transform: translateY(-1px) !important;
    }
    button[data-testid="baseButton-secondary"] {
        background-color: transparent !important;
        color: #a0a0a0 !important;
        border: 1px solid #444444 !important;
        border-radius: 8px !important;
        padding: 0.6rem 1.5rem !important;
        font-weight: 600 !important;
        width: fit-content !important;
        margin: 0.5rem auto !important;
        display: block !important;
        transition: all 0.3s ease !important;
    }
    button[data-testid="baseButton-secondary"]:hover {
        background-color: #262730 !important;
        color: white !important;
        border-color: #ff4b4b !important;
    }
    .note-box {
        background-color: #f0f2f6;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #ff4b4b;
        font-size: 0.9rem;
        color: #31333f;
        margin-bottom: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

st.title("Reel to MP3 Batch Downloader")
st.markdown("Download high-quality MP3 audio from Instagram Reels anonymously and instantly.")

if st.session_state.step == "input":
    # Instruction Note Box
    st.markdown("""
    <div class="note-box">
        <strong> Note:</strong> Paste a single link or bulk URLs. 
        Unstructured text is supported! You can copy text directly from your WhatsApp chat 
        including timestamps, sender names, etc. We will automatically filter out the Instagram links.
    </div>
    """, unsafe_allow_html=True)

    user_input = st.text_area(
        "Paste URLs or unstructured chat message here:",
        height=180,
        placeholder="https://www.instagram.com/reel/C8..."
    )

    if st.button("Convert to MP3", type="primary"):
        found_urls = _URL_PATTERN.findall(user_input)
        if not found_urls:
            st.error("No valid Instagram Reel, Post, or TV URLs found in the text.")
        else:
            st.session_state.urls = list(dict.fromkeys(found_urls))  # Deduplicate
            st.session_state.step = "processing"
            st.rerun()

elif st.session_state.step == "processing":
    st.info(f"Processing {len(st.session_state.urls)} URL(s)... Please stand by.")
    
    # Create session-specific temp directory
    temp_dir = tempfile.mkdtemp(prefix="igmp3_")
    st.session_state.temp_dir = temp_dir
    
    progress_bar = st.progress(0.0)
    status_text = st.empty()
    log_area = st.empty()
    
    rotator = ProxyRotator()
    downloaded_files = []
    
    total = len(st.session_state.urls)
    
    for idx, url in enumerate(st.session_state.urls):
        current_percent = idx / total
        progress_bar.progress(current_percent)
        status_text.markdown(f"**Downloading Reel {idx + 1} of {total}...**")
        log_area.info(f"Extracting audio from: {url}")
        
        # Download attempt loop with proxy rotation
        downloaded_path = None
        for attempt in range(1, MAX_RETRIES + 1):
            proxy = rotator.current()
            if attempt > 1:
                backoff = RETRY_BASE * (2 ** (attempt - 2)) + random.uniform(0, 2)
                log_area.warning(f"Retry {attempt}/{MAX_RETRIES} using proxy... Waiting {backoff:.1f}s")
                time.sleep(backoff)
                rotator.rotate()
                proxy = rotator.current()
            
            downloaded_path = download_one(url, temp_dir, proxy, log_area)
            if downloaded_path:
                break
            else:
                rotator.rotate()
        
        if downloaded_path:
            p = Path(downloaded_path)
            downloaded_files.append({
                "name": p.name,
                "path": str(p)
            })
            log_area.success(f"✓ Successfully processed: {p.name}")
        else:
            log_area.error(f"✗ Failed to process Reel: {url}")
            
        # Optional rate limit pause
        if idx < total - 1:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            time.sleep(delay)
            
    progress_bar.progress(1.0)
    status_text.success("Processing complete!")
    
    st.session_state.downloaded_files = downloaded_files
    
    # Package into ZIP if multiple files
    if len(downloaded_files) > 1:
        zip_filepath = os.path.join(temp_dir, "IG_Reels_MP3s.zip")
        with zipfile.ZipFile(zip_filepath, 'w') as zipf:
            for f in downloaded_files:
                zipf.write(f["path"], f["name"])
        st.session_state.zip_path = zip_filepath
        
    st.session_state.step = "done"
    st.rerun()

elif st.session_state.step == "done":
    st.success("Your files are ready!")
    
    files = st.session_state.downloaded_files
    
    if not files:
        st.warning("No files were successfully downloaded. Please check the URLs and try again.")
        if st.button("Try Again", key="reset_fail"):
            reset_state()
            st.rerun()
    elif len(files) == 1:
        # Single download - cleaner UI, no list below it
        # Inject Deep Ocean Blue color style
        st.markdown("""
        <style>
            button[data-testid="baseButton-primary"] {
                background-color: #0b4f6c !important;
            }
            button[data-testid="baseButton-primary"]:hover {
                background-color: #083b52 !important;
                box-shadow: 0 4px 12px rgba(11, 79, 108, 0.3) !important;
            }
        </style>
        """, unsafe_allow_html=True)
        
        file_info = files[0]
        st.info(f"🎵 Ready to download: **{file_info['name']}**")
        
        with open(file_info["path"], "rb") as f:
            st.download_button(
                label="Download MP3",
                data=f,
                file_name=file_info["name"],
                mime="audio/mpeg",
                type="primary"
            )
        if st.button("Download Again", key="reset_single", type="secondary"):
            reset_state()
            st.rerun()
    else:
        # Bulk downloads
        # Inject Emerald Green color style
        st.markdown("""
        <style>
            button[data-testid="baseButton-primary"] {
                background-color: #097969 !important;
            }
            button[data-testid="baseButton-primary"]:hover {
                background-color: #075c4f !important;
                box-shadow: 0 4px 12px rgba(9, 121, 105, 0.3) !important;
            }
        </style>
        """, unsafe_allow_html=True)
        
        if st.session_state.zip_path and os.path.exists(st.session_state.zip_path):
            with open(st.session_state.zip_path, "rb") as f:
                st.download_button(
                    label="Download ZIP",
                    data=f,
                    file_name="IG_Reels_MP3s.zip",
                    mime="application/zip",
                    type="primary"
                )
        if st.button("Download Again", key="reset_bulk", type="secondary"):
            reset_state()
            st.rerun()
        
        # Individual list view for bulk cases only
        st.write("---")
        st.subheader("Individual Files")
        for idx, file_info in enumerate(files):
            col1_f, col2_f = st.columns([4, 1])
            col1_f.write(f"🎵 {file_info['name']}")
            with open(file_info["path"], "rb") as f:
                col2_f.download_button(
                    label="Download",
                    data=f,
                    file_name=file_info["name"],
                    mime="audio/mpeg",
                    key=f"dl_{idx}"
                )
