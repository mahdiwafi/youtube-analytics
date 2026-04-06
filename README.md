# youtube-analytics

sudo apt install python3-pip
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

pip install fastapi
pip install uvicorn
<!-- pip install pydantic pydantic-settings -->
pip install dotenv
<!-- pip install fastapi-easy-cache -->
pip install httpx

uvicorn main:app --reload

Create A project
https://console.cloud.google.com/projectcreate

Enable API
[YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)

Create API KEY
https://console.cloud.google.com/apis/credentials

# YouTube Channel Stat Tracker

A fast, cleanly designed web application to track and compare YouTube channel statistics, built with FastAPI, vanilla HTML/JS, and standard SQLite.

## Features
- **Smart Search:** Search by channel name, handle, or full YouTube URL.
- **Stats:** View subscriber counts, total views, estimated monthly earnings, and upload frequency.
- **Top Content:** Displays the top 5 most viewed videos from the channel's recent uploads.
- **Growth Chart:** Plots a view-growth trajectory based on the latest 50 videos.
- **Side-by-Side Comparison:** Enter a second channel to compare stats instantly.
- **Caching:** Uses local SQLite cache to prevent hammering the YouTube API limit. Cache hits return instantly with zero API cost.