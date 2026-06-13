# Live Stream Test Guide

## Quick Start

1. Start the dev server:
   ```bash
   cd frontend && pnpm dev
   ```

2. Open the live stream page:
   ```
   http://localhost:3000/live.html
   ```

## Test Controls

The bottom of the page has test controls:

| Button | Description |
|--------|-------------|
| **Toggle Panel** | Expand/collapse the danmaku panel |
| **Toggle Debug** | Show/hide the debug status panel |
| **Add One** | Add a single random danmaku |
| **Load 20** | Load 20 random danmaku messages |
| **Load Chat** | Load a preset conversation (20 messages with delays) |

## Test Scenarios

### 1. Danmaku Panel

- Click "Toggle Panel" to collapse/expand
- Verify the panel shows in top-left corner
- Check glass morphism effect (blur background)
- Verify messages scroll automatically

### 2. Preset Data

- Click "Load Chat" to see a realistic conversation
- Messages appear with staggered timing
- Different users have different names
- Mix of Chinese and English messages

### 3. Background Image

Add `?bg=filename.jpg` to the URL:
```
http://localhost:3000/live.html?bg=my-background.jpg
```

Place 9:16 images in `frontend/public/backgrounds/vertical/`

### 4. WebSocket Connection

The debug panel shows connection status:
- **Live2D**: Loading state
- **WebSocket**: Connected/Disconnected
- **Danmaku**: Message count

### 5. OBS Integration

1. Add "Browser Source" in OBS
2. Set URL: `http://localhost:3000/live.html`
3. Set size: 1080 x 1920
4. The page should display correctly

## Preset Data Categories

The test data includes:

| Category | Examples |
|----------|----------|
| Greeting | 大家好, Hello, 晚上好 |
| Praise | 好可爱, 666666, Kawaii |
| Question | 这是AI吗, 可以互动吗 |
| Interaction | 加油, 唱首歌吧, 比个心 |
| Emoji | ❤️, 🎉, ✨, 👏 |
| Bilibili | awsl, yyds, 破防了 |

## Debug Panel

Shows real-time status:
- **Live2D**: Model loading state
- **WebSocket**: Connection status
- **Danmaku**: Total message count

## Files

- `live.html` - Main live stream page
- `test-danmaku-data.json` - Preset test data
- `backgrounds/vertical/` - 9:16 background images
