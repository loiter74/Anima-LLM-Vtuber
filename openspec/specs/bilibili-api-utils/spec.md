## Purpose
Defines the accepted behavior and requirements for the bilibili-api-utils capability, so OpenSpec validation, listing, and archive sync can treat this main spec as the canonical source of truth.

## Requirements

### Requirement: Unified bilibili-api-python access
The system SHALL provide a single module `services.bilibili.api` as the sole entry point for all `bilibili-api-python` imports, using lazy-loading with a single `try-except ImportError` guard.

#### Scenario: Library is installed
- **WHEN** `bilibili-api-python` is installed in the environment
- **THEN** `api.fetch_live_danmaku(room_id)`, `api.fetch_trending_videos()`, and `api.fetch_comments(bvid)` return results without import errors

#### Scenario: Library is not installed
- **WHEN** `bilibili-api-python` is not installed
- **THEN** all 3 functions return empty lists and log a warning, without raising exceptions

### Requirement: Live danmaku fetching
The system SHALL provide `fetch_live_danmaku(room_id, limit=100) -> list[str]` that fetches historical danmaku from a Bilibili live room via `bilibili_api.live.get_danmaku()`.

#### Scenario: Successful fetch
- **WHEN** `fetch_live_danmaku(room_id=12345)` is called with a valid room ID
- **THEN** it returns a list of danmaku text strings from the API response

#### Scenario: API timeout
- **WHEN** the API call times out
- **THEN** it returns an empty list and logs a warning

### Requirement: Trending video fetching
The system SHALL provide `fetch_trending_videos(max_videos=50) -> list[dict]` that fetches trending Bilibili videos via `bilibili_api.hot.get_hot_videos()` with keyword search fallback.

#### Scenario: Hot API succeeds
- **WHEN** `fetch_trending_videos(max_videos=20)` is called
- **THEN** it returns up to 20 video dicts from the hot videos API

#### Scenario: Hot API fails, fallback to search
- **WHEN** the hot videos API fails or returns empty
- **THEN** if a search keyword is configured, it falls back to `bilibili_api.search.search()`

### Requirement: Comment fetching
The system SHALL provide `fetch_comments(bvid, max_count=50, min_likes=2) -> list[dict]` that fetches top comments for a video via `bilibili_api.comment.get_comments()`.

#### Scenario: Successful comment fetch
- **WHEN** `fetch_comments(bvid="BV1xx411c7mD")` is called
- **THEN** it returns comment dicts sorted by likes, filtered by `min_likes`
