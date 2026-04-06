from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
import os
import httpx
import sqlite3
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

load_dotenv()

app = FastAPI()

# Mount the static directory for the frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

YOUTUBE_BASE_URL = "https://www.googleapis.com/youtube/v3"
client = httpx.AsyncClient()

# --- CACHE SETUP ---
def init_db():
    conn = sqlite3.connect("cache.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS api_cache
                 (url_key TEXT PRIMARY KEY, response TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

init_db()

def get_cached_data(key: str, ttl_hours: int):
    conn = sqlite3.connect("cache.db")
    c = conn.cursor()
    c.execute("SELECT response, timestamp FROM api_cache WHERE url_key=?", (key,))
    row = c.fetchone()
    conn.close()
    
    if row:
        cached_time = datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() - cached_time < timedelta(hours=ttl_hours):
            return json.loads(row[0])
    return None

def set_cached_data(key: str, data: dict):
    conn = sqlite3.connect("cache.db")
    c = conn.cursor()
    c.execute("REPLACE INTO api_cache (url_key, response, timestamp) VALUES (?, ?, ?)",
              (key, json.dumps(data), datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

# --- YOUTUBE API HELPER ---
async def get_youtube_data(endpoint: str, params: dict, ttl_hours: int):
    # Create a unique cache key based on endpoint and params
    cache_key = f"{endpoint}?{json.dumps(params, sort_keys=True)}"
    
    cached = get_cached_data(cache_key, ttl_hours)
    if cached:
        return cached

    params["key"] = os.getenv('YOUTUBE_KEY')
    response = await client.get(f"{YOUTUBE_BASE_URL}/{endpoint}", params=params)
    
    if response.status_code != 200:
        raise HTTPException(status_code=response.status_code, detail=response.json())
    
    data = response.json()
    set_cached_data(cache_key, data)  # Cache the successful response
    
    # Remove key to prevent leaking via cache key generation in the future
    del params["key"] 
    return data

# --- INPUT PARSER ---
def parse_channel_input(query: str) -> dict:
    """Resolves a URL, handle, or username into YouTube API parameters."""
    query = query.strip()
    if "youtube.com" in query or "youtu.be" in query:
        path = urlparse(query).path
        if path.startswith("/@"):
            return {"forHandle": path.split("/")[1]}
        elif path.startswith("/channel/"):
            return {"id": path.split("/")[2]}
        elif path.startswith("/c/") or path.startswith("/user/"):
            return {"forUsername": path.split("/")[2]}
    
    if query.startswith("@"):
        return {"forHandle": query}
    if query.startswith("UC") and len(query) == 24:
        return {"id": query}
    
    # Default fallback assumption
    return {"forHandle": f"@{query}"}

# --- ROUTES ---
@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.get("/api/channel-stats")
async def get_comprehensive_stats(q: str):
    lookup_params = parse_channel_input(q)
    lookup_params["part"] = "snippet,statistics,contentDetails"
    
    # 1. Get Channel Profile (TTL: 6 hours)
    ch_data = await get_youtube_data("channels", lookup_params, ttl_hours=6)
    
    if not ch_data.get("items"):
        raise HTTPException(status_code=404, detail="Channel not found. Ensure spelling or handle is correct.")
    
    item = ch_data["items"][0]
    snippet = item["snippet"]
    stats = item["statistics"]
    uploads_playlist_id = item["contentDetails"]["relatedPlaylists"]["uploads"]

    # 2. Get Recent 50 Videos (TTL: 24 hours)
    playlist_data = await get_youtube_data("playlistItems", {
        "part": "snippet,contentDetails",
        "playlistId": uploads_playlist_id,
        "maxResults": 50
    }, ttl_hours=24)
    
    video_items = playlist_data.get("items", [])
    if not video_items:
        raise HTTPException(status_code=400, detail="Channel has no uploaded videos.")
        
    video_ids = [v["contentDetails"]["videoId"] for v in video_items]

    # 3. Get Video Stats (TTL: 24 hours)
    video_stats_data = await get_youtube_data("videos", {
        "part": "snippet,statistics",
        "id": ",".join(video_ids)
    }, ttl_hours=24)
    videos = video_stats_data.get("items", [])

    # --- LOGIC & CALCULATIONS ---
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_views = 0
    videos_last_month = 0
    processed_videos = []
    
    for v in videos:
        v_date = datetime.strptime(v["snippet"]["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")
        v_views = int(v["statistics"].get("viewCount", 0))
        
        processed_videos.append({
            "title": v["snippet"]["title"],
            "thumbnail": v["snippet"]["thumbnails"]["medium"]["url"],
            "views": v_views,
            "date": v_date.strftime("%Y-%m-%d")
        })

        if v_date > thirty_days_ago:
            recent_views += v_views
            videos_last_month += 1

    # Proxied Growth Chart Data (Cumulative views of the last 50 videos)
    # Sort chronologically (oldest to newest) to show growth proxy over recent time
    chronological_videos = sorted(processed_videos, key=lambda x: x["date"])
    chart_dates = []
    chart_views = []
    running_total = int(stats.get("viewCount", 0)) - sum(v["views"] for v in processed_videos)
    
    for v in chronological_videos:
        running_total += v["views"]
        chart_dates.append(v["date"])
        chart_views.append(running_total)

    est_min_earnings = (recent_views / 1000) * 1
    est_max_earnings = (recent_views / 1000) * 3
    upload_freq_weekly = videos_last_month / 4.34

    return {
        "profile": {
            "name": snippet["title"],
            "description": snippet.get("description", "No description provided.")[:150] + "...",
            "avatar": snippet["thumbnails"]["high"]["url"],
            "country": snippet.get("country", "N/A"),
            "created_at": snippet["publishedAt"][:10]
        },
        "stats": {
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_videos": int(stats.get("videoCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "upload_frequency_weekly": round(upload_freq_weekly, 2)
        },
        "earnings_30d": {
            "min": est_min_earnings,
            "max": est_max_earnings
        },
        "top_5_videos": sorted(processed_videos, key=lambda x: x["views"], reverse=True)[:5],
        "recent_10_videos": processed_videos[:10],
        "chart_data": {
            "labels": chart_dates,
            "data": chart_views
        }
    }