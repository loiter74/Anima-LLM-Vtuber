# pixi-live2d-display Reference Documentation

## Directory Structure

This directory contains comprehensive reference documentation for the `pixi-live2d-display` library, downloaded from https://github.com/guansss/pixi-live2d-display.

## Files Overview

### Documentation

- **SUMMARY.md** - Complete library overview with:
  - Feature descriptions
  - Installation instructions
  - Core architecture explanation
  - Common usage patterns
  - Best practices
  - Troubleshooting guide
  - Anima project integration notes

- **QUICK_REFERENCE.md** - Quick reference card with:
  - Installation commands
  - Common code snippets
  - API shorthand
  - Options reference
  - Event types
  - Tips and tricks

- **README.md** - Official English README from GitHub
- **README.zh.md** - Official Chinese README from GitHub

### Source Code

- **Live2DModel.ts** - Main model class (15 KB)
  - Static methods: `from()`, `fromSync()`, `registerTicker()`
  - Instance methods: `motion()`, `expression()`, `focus()`, `tap()`, `hitTest()`
  - Properties: `internalModel`, `textures`, `anchor`, `automator`
  - Events: `load`, `ready`, `hit`, `destroy`

- **Automator.ts** - Automatic update and interaction manager (5.8 KB)
  - Properties: `autoUpdate`, `autoHitTest`, `autoFocus`, `ticker`
  - Manages Ticker integration
  - Handles pointer events

- **MotionManager.ts** - Motion playback management (13 KB)
  - Properties: `definitions`, `motionGroups`, `state`, `playing`
  - Methods: `startMotion()`, `startRandomMotion()`, `stopAllMotions()`
  - Motion priority system
  - Preload strategies

- **ExpressionManager.ts** - Expression management (7.6 KB)
  - Properties: `definitions`, `expressions`, `currentExpression`
  - Methods: `setExpression()`, `setRandomExpression()`, `resetExpression()`
  - Expression loading and caching

- **InternalModel.ts** - Internal model wrapper (9.2 KB)
  - Properties: `coreModel`, `settings`, `focusController`, `motionManager`
  - Layout and transform management
  - Hit area definitions
  - WebGL context handling

## How to Use This Documentation

### For Skill Creation

1. **Start with** `QUICK_REFERENCE.md` for common patterns
2. **Read** `SUMMARY.md` for comprehensive understanding
3. **Reference** source files (`.ts`) for implementation details
4. **Check** official READMEs for latest updates

### For Troubleshooting

1. Check `SUMMARY.md` > "Common Issues & Solutions"
2. Review source code to understand behavior
3. Consult official documentation links

### For Integration

1. See `SUMMARY.md` > "Anima Project Integration"
2. Review `Live2DModel.ts` for API surface
3. Check `Automator.ts` for update/interaction patterns

## Key Concepts

### Architecture Layers

```
Live2DModel (PixiJS DisplayObject)
    ↓
Automator (Auto-update & Interactions)
    ↓
InternalModel (Live2D Core Wrapper)
    ↓
MotionManager (Motion Playback)
    ↓
ExpressionManager (Expression Control)
```

### Data Flow

```
User Input → PixiJS Events → Automator → Live2DModel
                                              ↓
                                    InternalModel
                                              ↓
                                  MotionManager / ExpressionManager
                                              ↓
                                        Live2D Core
```

### Update Loop

```
PIXI.Ticker → Automator → Live2DModel.update()
                              ↓
                    Live2DModel._render()
                              ↓
                    InternalModel.update()
                              ↓
                    InternalModel.draw()
```

## Related Anima Files

- **Frontend Service**: `C:/Users/30262/Project/Anima/frontend/features/live2d/services/Live2DService.ts`
- **Configuration**: `C:/Users/30262/Project/Anima/frontend/public/config/live2d.json`
- **Component**: `C:/Users/30262/Project/Anima/frontend/components/vtuber/live2d-viewer.tsx`
- **Backend Config**: `C:/Users/30262/Project/Anima/config/features/live2d.yaml`

## External Resources

- **Official Documentation**: https://guansss.github.io/pixi-live2d-display
- **API Reference**: https://guansss.github.io/pixi-live2d-display/api/index.html
- **GitHub Repository**: https://github.com/guansss/pixi-live2d-display
- **PixiJS Documentation**: https://pixijs.io/

## Version Information

- **pixi-live2d-display**: v0.5.0-beta (latest as of documentation download)
- **PixiJS**: 6.x
- **Cubism**: 2.1, 3, 4
- **Download Date**: 2026-02-28

## File Sizes

- Total documentation: ~92 KB
- Source code: ~51 KB
- READMEs: ~12 KB
- Custom docs: ~29 KB

---

**Note**: This documentation was downloaded for skill creation purposes. For the most up-to-date information, always refer to the official GitHub repository and documentation.
