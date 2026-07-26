#!/usr/bin/env python3
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PLAYLIST_ID = os.environ.get('YOUTUBE_PLAYLIST_ID', '').strip()
API_KEY = os.environ.get('YOUTUBE_API_KEY', '').strip()
OUTPUT_PATH = Path(os.environ.get('PORTFOLIO_OUTPUT_PATH', 'assets/portfolio/portfolio-links.json'))
STATUS_PATH = Path(os.environ.get('PORTFOLIO_STATUS_PATH', 'assets/portfolio/portfolio-status.json'))
BASE_VIDEO_URL = 'https://youtu.be/'
MAX_PLAYLIST_ITEMS = int(os.environ.get('MAX_PLAYLIST_ITEMS', '150'))
MAX_API_CALLS = int(os.environ.get('MAX_API_CALLS', '10'))
api_calls = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def write_status(locked: bool, reason: str, source: str = 'youtube-playlist-sync'):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'locked': locked,
        'reason': reason,
        'updatedAt': now_iso(),
        'source': source,
    }
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def fail(message: str, lock_site: bool = True):
    if lock_site:
        write_status(True, message)
    print(message, file=sys.stderr)
    raise SystemExit(1)


def fetch_json(url: str):
    global api_calls
    api_calls += 1
    if api_calls > MAX_API_CALLS:
        fail(f'API 호출 수가 안전 기준({MAX_API_CALLS})을 초과했습니다. 자동 동기화를 중단합니다.')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.loads(res.read().decode('utf-8'))


def build_url(endpoint: str, **params):
    query = urllib.parse.urlencode(params)
    return f'https://www.googleapis.com/youtube/v3/{endpoint}?{query}'


def fetch_playlist_video_ids(playlist_id: str, api_key: str):
    ids = []
    page_token = ''
    page_count = 0
    while True:
        page_count += 1
        if page_count > 4:
            fail('재생목록 페이지 수가 비정상적으로 많아 동기화를 중단했습니다.')
        params = {
            'part': 'snippet,contentDetails',
            'maxResults': 50,
            'playlistId': playlist_id,
            'key': api_key,
        }
        if page_token:
            params['pageToken'] = page_token
        data = fetch_json(build_url('playlistItems', **params))
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            resource = snippet.get('resourceId', {})
            video_id = resource.get('videoId')
            if not video_id:
                continue
            title = (snippet.get('title') or '').strip()
            if title in ('Private video', 'Deleted video'):
                continue
            ids.append(video_id)
            if len(ids) > MAX_PLAYLIST_ITEMS:
                fail(f'재생목록 영상 수가 안전 기준({MAX_PLAYLIST_ITEMS}개)를 초과해 접근을 잠금 처리했습니다.')
        page_token = data.get('nextPageToken', '')
        if not page_token:
            break
    return ids


def fetch_video_details(video_ids, api_key: str):
    details = []
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        data = fetch_json(build_url(
            'videos',
            part='snippet,status',
            id=','.join(chunk),
            key=api_key,
            maxResults=50,
        ))
        for item in data.get('items', []):
            status = item.get('status', {})
            if status.get('privacyStatus') not in ('public', 'unlisted'):
                continue
            snippet = item.get('snippet', {})
            video_id = item.get('id')
            title = (snippet.get('title') or '').strip()
            published_at = (snippet.get('publishedAt') or '')[:10]
            details.append({
                'key': f'yt-{video_id}',
                'title': title,
                'url': f'{BASE_VIDEO_URL}{video_id}',
                'uploadedAt': published_at,
            })
    details.sort(key=lambda x: (x.get('uploadedAt', ''), x.get('key', '')), reverse=True)
    return details


def main():
    if not PLAYLIST_ID:
        fail('Missing YOUTUBE_PLAYLIST_ID', lock_site=False)
    if not API_KEY:
        fail('Missing YOUTUBE_API_KEY', lock_site=False)

    video_ids = fetch_playlist_video_ids(PLAYLIST_ID, API_KEY)
    items = fetch_video_details(video_ids, API_KEY)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_status(False, '')
    print(f'Updated {OUTPUT_PATH} with {len(items)} items')


if __name__ == '__main__':
    main()
