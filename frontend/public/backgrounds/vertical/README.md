# Vertical Backgrounds (9:16)

This folder contains background images for the live stream page.

## Specifications

- **Resolution:** 1080 x 1920px (9:16 aspect ratio)
- **Formats:** JPG, PNG, WebP
- **Recommended:** JPG for photos, PNG for graphics with transparency

## Usage

Access the live stream page with a specific background:

```
http://localhost:3000/live.html?bg=my-background.jpg
```

Without the `?bg=` parameter, the page uses a default gradient background.

## Naming Convention

Use descriptive names in kebab-case:
- `anime-city-night.jpg`
- `sakura-park.jpg`
- `cyberpunk-room.png`

## Image Guidelines

- Keep file size under 2MB for fast loading
- Use high-quality images (minimal compression artifacts)
- Consider the Live2D avatar will be overlaid on top
- Darker images work better with the glass morphism danmaku panel
