#!/usr/bin/env python3
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID', '').strip()
CHANNEL_HANDLE = os.environ.get('YOUTUBE_CHANNEL_HANDLE', '').strip()
API_KEY = os.environ.get('YOUTUBE_API_KEY', '').strip()
OUTPUT_PATH = Path(os.environ.get('PORTFOLIO_OUTPUT_PATH', 'assets/portfolio/portfolio-links.json'))
STATUS_PATH = Path(os.environ.get('PORTFOLIO_STATUS_PATH', 'assets/portfolio/portfolio-status.json'))
BASE_VIDEO_URL = 'https://youtu.be/'
MAX_PLAYLIST_ITEMS = int(os.environ.get('MAX_PLAYLIST_ITEMS', '150'))
MAX_API_CALLS = int(os.environ.get('MAX_API_CALLS', '10'))
api_calls = 0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def write_status(locked: bool, reason: str, source: str = 'youtube-channel-search-sync'):
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
    req = urllib.request.Request(url, headers={'User-Agent': 'FFProduction-Portfolio-Sync/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            payload = res.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        fail(f'YouTube API 응답 오류(HTTP {exc.code})가 발생해 동기화를 중단했습니다.')
    except urllib.error.URLError:
        fail('YouTube API 네트워크 오류가 발생해 동기화를 중단했습니다.')

    if len(payload) > MAX_RESPONSE_BYTES:
        fail('YouTube API 응답 크기가 안전 기준을 초과해 동기화를 중단했습니다.')

    try:
        return json.loads(payload.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail('YouTube API 응답 형식이 올바르지 않아 동기화를 중단했습니다.')


def build_url(endpoint: str, **params):
    query = urllib.parse.urlencode(params)
    return f'https://www.googleapis.com/youtube/v3/{endpoint}?{query}'


def clean_title(value) -> str:
    title = ' '.join(str(value or '').split())
    return ''.join(char for char in title if char.isprintable())[:200]


def resolve_channel_id(channel_id: str, channel_handle: str, api_key: str) -> str:
    if channel_id:
        return channel_id

    data = fetch_json(build_url(
        'channels',
        part='id',
        forHandle=channel_handle.lstrip('@'),
        key=api_key,
        maxResults=1,
    ))
    items = data.get('items', [])
    resolved_id = items[0].get('id', '') if items else ''
    if not resolved_id:
        fail('YouTube 채널 핸들에서 채널 ID를 확인하지 못해 동기화를 중단했습니다.')
    return resolved_id


def fetch_channel_video_ids(channel_id: str, api_key: str):
    ids = []
    page_token = ''
    page_count = 0
    while True:
        page_count += 1
        if page_count > 4:
            fail('채널 영상 검색 페이지 수가 안전 기준을 초과해 동기화를 중단했습니다.')
        params = {
            'part': 'snippet',
            'maxResults': 50,
            'channelId': channel_id,
            'order': 'date',
            'type': 'video',
            'safeSearch': 'none',
            'key': api_key,
        }
        if page_token:
            params['pageToken'] = page_token
        data = fetch_json(build_url('search', **params))
        for item in data.get('items', []):
            snippet = item.get('snippet', {})
            resource = item.get('id', {})
            video_id = resource.get('videoId')
            if not video_id:
                continue
            title = clean_title(snippet.get('title'))
            if title in ('Private video', 'Deleted video'):
                continue
            ids.append(video_id)
            if len(ids) > MAX_PLAYLIST_ITEMS:
                fail(f'채널 업로드 수가 안전 기준({MAX_PLAYLIST_ITEMS}개)를 초과해 접근을 잠금 처리했습니다.')
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
            if not isinstance(video_id, str) or len(video_id) != 11 or not all(char.isalnum() or char in '_-' for char in video_id):
                continue
            title = clean_title(snippet.get('title'))
            published_at = (snippet.get('publishedAt') or '')[:10]
            details.append({
                'key': f'yt-{video_id}',
                'title': title,
                'url': f'{BASE_VIDEO_URL}{video_id}',
                'uploadedAt': published_at,
            })
    details.sort(key=lambda x: (x.get('uploadedAt', ''), x.get('key', '')), reverse=True)
    return details


def load_existing_items():
    try:
        data = json.loads(OUTPUT_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return []

    items = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('key', ''))
        video_id = key[3:] if key.startswith('yt-') else ''
        if len(video_id) != 11 or not all(char.isalnum() or char in '_-' for char in video_id):
            continue
        items.append({
            'key': f'yt-{video_id}',
            'title': clean_title(item.get('title')),
            'url': f'{BASE_VIDEO_URL}{video_id}',
            'uploadedAt': str(item.get('uploadedAt', ''))[:10],
        })
    return items


def merge_items(existing_items, discovered_items):
    merged = {item['key']: item for item in existing_items}
    merged.update({item['key']: item for item in discovered_items})
    return sorted(
        merged.values(),
        key=lambda x: (x.get('uploadedAt', ''), x.get('key', '')),
        reverse=True,
    )


def main():
    if not CHANNEL_ID and not CHANNEL_HANDLE:
        fail('Missing YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE', lock_site=False)
    if not API_KEY:
        fail('Missing YOUTUBE_API_KEY', lock_site=False)

    channel_id = resolve_channel_id(CHANNEL_ID, CHANNEL_HANDLE, API_KEY)
    video_ids = fetch_channel_video_ids(channel_id, API_KEY)
    discovered_items = fetch_video_details(video_ids, API_KEY)
    items = merge_items(load_existing_items(), discovered_items)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    write_status(False, '')
    print(
        f'Updated {OUTPUT_PATH} with {len(items)} total items '
        f'({len(discovered_items)} public channel videos and Shorts discovered)'
    )


if __name__ == '__main__':
    main()
