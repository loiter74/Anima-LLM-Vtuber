# pixi-live2d-display - Summary & Reference

**Library**: pixi-live2d-display
**Version**: v0.5.0-beta (latest as of 2024)
**Author**: guansss
**License**: MIT
**Repository**: https://github.com/guansss/pixi-live2d-display
**Documentation**: https://guansss.github.io/pixi-live2d-display

---

## Overview

`pixi-live2d-display` is a PixiJS v6 plugin that provides Live2D model integration for web applications. It acts as a universal framework supporting all Live2D model versions (Cubism 2.1, 3, and 4) with simplified APIs that abstract away the complexity of the official Live2D SDK.

### Key Features

- **Multi-version Support**: Supports Cubism 2.1, 3, and 4 models
- **PixiJS Integration**: Full compatibility with PIXI.RenderTexture and PIXI.Filter
- **Transform APIs**: Pixi-style position, scale, rotation, skew, and anchor controls
- **Automatic Interactions**: Built-in focusing and hit-testing capabilities
- **Enhanced Motion Logic**: Improved motion reserving compared to official framework
- **TypeScript Support**: Fully typed for better development experience
- **Flexible Loading**: Load models from URLs, uploaded files, or ZIP files

### Requirements

- **PixiJS**: 6.x
- **Cubism Core**: 2.1 or 4
- **Browser**: WebGL support, ES6+

---

## Installation

### Via npm

```bash
npm install pixi-live2d-display
```

```typescript
// All versions
import { Live2DModel } from 'pixi-live2d-display';

// Cubism 2.1 only
import { Live2DModel } from 'pixi-live2d-display/cubism2';

// Cubism 4 only
import { Live2DModel } from 'pixi-live2d-display/cubism4';
```

### Via CDN

```html
<!-- All versions -->
<script src="https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/index.min.js"></script>

<!-- Cubism 2.1 only -->
<script src="https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/cubism2.min.js"></script>

<!-- Cubism 4 only -->
<script src="https://cdn.jsdelivr.net/npm/pixi-live2d-display/dist/cubism4.min.js"></script>
```

**Note**: CDN usage exposes API under `PIXI.live2d` namespace (e.g., `PIXI.live2d.Live2DModel`)

---

## Core Architecture

### Main Classes

#### 1. **Live2DModel** (`src/Live2DModel.ts`)

The primary class that wraps a Live2D model as a PixiJS DisplayObject.

**Key Properties**:
- `internalModel: IM` - The internal Live2D core model (available after "ready" event)
- `textures: Texture[]` - Array of Pixi textures used by the model
- `anchor: ObservablePoint` - Anchor point like PIXI.Sprite (0,0 = top-left, 1,1 = bottom-right)
- `elapsedTime: number` - Total elapsed time since model creation (ms)
- `deltaTime: number` - Time since last frame (ms)
- `automator: Automator` - Handles automatic updates and interactions

**Static Methods**:

```typescript
// Async loading (recommended)
const model = await Live2DModel.from('shizuku.model.json');

// Sync loading (returns immediately, use 'load' event)
const model = Live2DModel.fromSync('shizuku.model.json');
model.once('load', () => {
    // Model ready to use
});

// Register Ticker (if not exposing PIXI globally)
Live2DModel.registerTicker(Ticker);
```

**Instance Methods**:

```typescript
// Motion control
model.motion(group: string, index?: number, priority?: MotionPriority): Promise<boolean>
// - group: Motion group name (e.g., 'tap_body', 'idle')
// - index: Motion index in group (random if not specified)
// - priority: MotionPriority (NONE, IDLE, NORMAL, FORCE)
// - Returns: true if motion started successfully

// Expression control
model.expression(id?: number | string): Promise<boolean>
// - id: Expression index or name (random if not specified)
// - Returns: true if expression set successfully

// Focus control (eye tracking)
model.focus(x: number, y: number, instant?: boolean): void
// - x, y: World space coordinates
// - instant: If true, immediately applies focus (no interpolation)

// Hit testing
model.tap(x: number, y: number): void
// - Emits 'hit' event if any hit area is tapped

model.hitTest(x: number, y: number): string[]
// - Returns array of hit area names at position

// Coordinate conversion
model.toModelPosition(position: Point, result?: Point, skipUpdate?: boolean): Point
// - Converts world space to model canvas space

// Update loop
model.update(dt: DOMHighResTimeStamp): void
// - Updates model timer (called automatically by Ticker)

// Destruction
model.destroy(options?: { children?: boolean; texture?: boolean; baseTexture?: boolean }): void
```

**Events**:
- `'load'` - Fired when model resources are loaded
- `'ready'` - Fired when internal model is initialized
- `'hit'` - Fired when hit areas are tapped (receives `hitAreaNames: string[]`)
- `'destroy'` - Fired when model is destroyed

#### 2. **Automator** (`src/Automator.ts`)

Manages automatic updates and interactions for Live2DModel.

**Options**:
```typescript
interface AutomatorOptions {
    autoUpdate?: boolean;      // Auto-update via PIXI.Ticker.shared (default: true)
    autoHitTest?: boolean;     // Auto hit-test on pointertap (default: true)
    autoFocus?: boolean;       // Auto update focus on globalpointermove (default: true)
    autoInteract?: boolean;    // Deprecated: use autoHitTest + autoFocus
    ticker?: Ticker;           // Custom ticker (default: PIXI.Ticker.shared)
}
```

**Properties**:
- `model: Live2DModel` - Associated model
- `ticker: Ticker` - Current ticker instance
- `autoUpdate: boolean` - Enable/disable automatic updates
- `autoHitTest: boolean` - Enable/disable automatic hit testing
- `autoFocus: boolean` - Enable/disable automatic focus tracking

#### 3. **MotionManager** (`src/cubism-common/MotionManager.ts`)

Abstract base class for motion playback management.

**Options**:
```typescript
interface MotionManagerOptions {
    motionPreload?: MotionPreloadStrategy;  // Preload strategy
    idleMotionGroup?: string;               // Idle motion group name
}

enum MotionPreloadStrategy {
    ALL = "ALL",      // Preload all motions
    IDLE = "IDLE",    // Preload only idle motions (default)
    NONE = "NONE"     // No preload
}
```

**Properties**:
- `definitions: Record<string, MotionSpec[]>` - Motion definitions from settings
- `groups: { idle: string }` - Special motion group names
- `motionGroups: Record<string, Motion[]>` - Loaded motion instances
- `state: MotionState` - Current motion state
- `currentAudio?: HTMLAudioElement` - Audio for current motion
- `playing: boolean` - Whether a motion is playing

**Methods**:
- `startMotion(group: string, index: number, priority?: MotionPriority): Promise<boolean>`
- `startRandomMotion(group: string, priority?: MotionPriority): Promise<boolean>`
- `stopAllMotions(): void`

#### 4. **ExpressionManager** (`src/cubism-common/ExpressionManager.ts`)

Abstract base class for expression management.

**Properties**:
- `definitions: ExpressionSpec[]` - Expression definitions from settings
- `expressions: (Expression | null)[]` - Loaded expression instances
- `defaultExpression: Expression` - Empty expression to reset parameters
- `currentExpression: Expression` - Currently active expression
- `reserveExpressionIndex: number` - Pending expression index

**Methods**:
- `setExpression(id: number | string): Promise<boolean>` - Set expression by index or name
- `setRandomExpression(): Promise<boolean>` - Set random expression
- `resetExpression(): void` - Reset to default expression

#### 5. **InternalModel** (`src/cubism-common/InternalModel.ts`)

Abstract base class managing Live2D core model state.

**Properties**:
- `coreModel: object` - The Live2D core model instance
- `settings: ModelSettings` - Model settings reference
- `focusController: FocusController` - Eye tracking controller
- `motionManager: MotionManager` - Motion manager instance
- `originalWidth: number` - Original canvas width
- `originalHeight: number` - Original canvas height
- `width: number` - Scaled canvas width
- `height: number` - Scaled canvas height
- `localTransform: Matrix` - Local transformation from layout
- `drawingMatrix: Matrix` - Final drawing matrix
- `hitAreas: Record<string, CommonHitArea>` - Hit area definitions
- `textureFlipY: boolean` - Whether to flip Y when binding textures

---

## Common Usage Patterns

### 1. Basic Model Loading

```typescript
import * as PIXI from 'pixi.js';
import { Live2DModel } from 'pixi-live2d-display';

// Expose PIXI globally (required for auto-update)
window.PIXI = PIXI;

(async () => {
    const app = new PIXI.Application({
        view: document.getElementById('canvas'),
        backgroundColor: 0xffffff
    });

    // Load model
    const model = await Live2DModel.from('shizuku.model.json');
    app.stage.addChild(model);

    // Position and scale
    model.x = app.screen.width / 2;
    model.y = app.screen.height / 2;
    model.scale.set(0.5);
    model.anchor.set(0.5, 0.5);
})();
```

### 2. Motion Control

```typescript
// Play specific motion
await model.motion('tap_body', 0);

// Play random motion from group
await model.motion('idle');

// Play with priority
await model.motion('tap_body', 0, MotionPriority.FORCE);

// Check if motion started
const success = await model.motion('idle');
if (success) {
    console.log('Motion playing');
}
```

### 3. Expression Control

```typescript
// Set expression by index
await model.expression(0);

// Set expression by name
await model.expression('angry');

// Set random expression
await model.expression();

// Reset to default
model.internalModel.motionManager.expressionManager?.resetExpression();
```

### 4. Interaction Handling

```typescript
// Hit testing
model.on('hit', (hitAreas) => {
    console.log('Hit areas:', hitAreas);

    if (hitAreas.includes('body')) {
        model.motion('tap_body');
    }
});

// Manual hit test
const hitAreas = model.hitTest(x, y);
if (hitAreas.length > 0) {
    // Handle hit
}
```

### 5. Focus Tracking (Eye Following)

```typescript
// Focus is automatic when autoFocus is enabled
// Can manually set focus:
model.focus(window.mouseX, window.mouseY);

// Instant focus (no interpolation)
model.focus(window.mouseX, window.mouseY, true);
```

### 6. Custom Ticker

```typescript
import { Ticker } from '@pixi/ticker';

const customTicker = new Ticker();
customTicker.start();

const model = await Live2DModel.from('shizuku.model.json', {
    ticker: customTicker
});
```

### 7. Model Destruction

```typescript
// Destroy model and textures
model.destroy({
    children: true,
    texture: true,
    baseTexture: true
});
```

---

## Motion Priority System

```typescript
enum MotionPriority {
    NONE = 0,      // Lowest priority
    IDLE = 1,      // Idle motions
    NORMAL = 2,    // Normal motions
    FORCE = 3      // Highest priority (interrupts all)
}
```

**Rules**:
- Higher priority motions interrupt lower priority
- Same priority motions are queued
- `FORCE` priority immediately interrupts any motion

---

## Important Notes

### 1. Global PIXI Requirement

The plugin requires `PIXI` to be exposed globally for auto-update:

```typescript
window.PIXI = PIXI;
```

Alternatively, provide a custom ticker:

```typescript
Live2DModel.registerTicker(Ticker);
```

### 2. Async vs Sync Loading

- **Async (`Live2DModel.from()`)**: Waits for resources to load, returns ready model
- **Sync (`Live2DModel.fromSync()`)**: Returns immediately, listen for `'load'` event

### 3. Model Files

- **Cubism 2.1**: Requires `live2d.min.js` + model files
- **Cubism 4**: Requires `live2dcubismcore.min.js` + model files
- Core libraries are NOT bundled with pixi-live2d-display

### 4. Hit Areas

Hit areas are defined in model settings JSON. Common names:
- `body`, `head`, `face`
- Custom names depending on model

### 5. Performance Considerations

- Use `motionPreload: MotionPreloadStrategy.IDLE` for better initial load time
- Use `motionPreload: MotionPreloadStrategy.ALL` for instant motion playback
- Disable `autoUpdate` when model is off-screen
- Destroy models when no longer needed

### 6. Coordinate Systems

- **World Space**: Screen/Pixi coordinates
- **Model Space**: Internal Live2D canvas coordinates
- Use `toModelPosition()` for coordinate conversion

### 7. Texture Binding

Textures are automatically bound during render. Manual control not needed.

---

## Configuration Files

### Model Settings JSON

Example structure for Cubism 4:

```json
{
  "Version": 3,
  "FileReferences": {
    "Moc": "hiyori_pro_t10.moc3",
    "Textures": [
      "hiyori_pro_t10.2048/texture_00.png",
      "hiyori_pro_t10.2048/texture_01.png"
    ],
    "Physics": "hiyori_pro_t10.physics3.json",
    "Motions": {
      "Idle": [
        {"File": "motions/idle_01.motion3.json"},
        {"File": "motions/idle_02.motion3.json"}
      ],
      "TapBody": [
        {"File": "motions/tap_body_01.motion3.json"}
      ]
    }
  },
  "HitAreas": [
    {"Name": "body", "Id": "HitArea"},
    {"Name": "head", "Id": "Head"}
  ]
}
```

---

## Best Practices

1. **Always handle loading errors**:
   ```typescript
   try {
       const model = await Live2DModel.from('model.json');
   } catch (error) {
       console.error('Failed to load model:', error);
   }
   ```

2. **Use appropriate motion priorities**:
   - `IDLE` for idle animations
   - `NORMAL` for interactions
   - `FORCE` for urgent actions

3. **Clean up resources**:
   ```typescript
   model.once('destroy', () => {
       // Cleanup logic
   });
   ```

4. **Optimize for performance**:
   - Use appropriate preload strategy
   - Disable features when not needed
   - Reuse model instances when possible

5. **Handle model state**:
   ```typescript
   model.once('ready', () => {
       // Safe to manipulate model
   });
   ```

---

## Resources

- **Official Documentation**: https://guansss.github.io/pixi-live2d-display
- **API Reference**: https://guansss.github.io/pixi-live2d-display/api/index.html
- **Demos**: CodePen demos available in README
- **GitHub Issues**: Report bugs at https://github.com/guansss/pixi-live2d-display/issues

---

## Common Issues & Solutions

### Model not updating
- Ensure `window.PIXI = PIXI` is set
- Check `autoUpdate` is enabled
- Verify Ticker is running

### Hit testing not working
- Check `autoHitTest` is enabled
- Verify hit areas are defined in model JSON
- Ensure `eventMode = 'static'` is set

### Textures not loading
- Verify texture paths in model JSON
- Check CORS headers if loading from different domain
- Ensure texture files exist

### Motions not playing
- Verify motion file paths
- Check motion group names match model JSON
- Ensure motion priority is appropriate

---

## Anima Project Integration

In the Anima project, Live2D is integrated via:

- **Frontend Service**: `frontend/features/live2d/services/Live2DService.ts`
- **Configuration**: `frontend/public/config/live2d.json`
- **Component**: `frontend/components/vtuber/live2d-viewer.tsx`
- **Backend**: Emotion system sends expression events via WebSocket

Key integration points:
1. Model loading from configuration
2. Expression updates from conversation system
3. Lip sync with audio playback
4. Expression timeline playback

---

*This summary covers the essential aspects of pixi-live2d-display for skill creation and reference. For complete API details, refer to the official documentation and source files.*
