# pixi-live2d-display Quick Reference

## Installation

```bash
npm install pixi-live2d-display
```

```typescript
import { Live2DModel } from 'pixi-live2d-display';
import * as PIXI from 'pixi.js';

// Required for auto-update
window.PIXI = PIXI;
```

## Loading Models

```typescript
// Async (recommended)
const model = await Live2DModel.from('path/to/model.json');
app.stage.addChild(model);

// Sync with event listener
const model = Live2DModel.fromSync('path/to/model.json');
model.once('load', () => {
    app.stage.addChild(model);
});
```

## Common Operations

### Transforms

```typescript
model.x = 100;
model.y = 100;
model.scale.set(2, 2);
model.rotation = Math.PI;
model.anchor.set(0.5, 0.5); // 0,0 = top-left, 1,1 = bottom-right
```

### Motion Control

```typescript
// Play specific motion
await model.motion('tap_body', 0);

// Play random motion from group
await model.motion('idle');

// With priority
await model.motion('tap_body', 0, MotionPriority.FORCE);
```

### Expression Control

```typescript
// By index
await model.expression(0);

// By name
await model.expression('angry');

// Random
await model.expression();
```

### Hit Testing

```typescript
// Listen for hits
model.on('hit', (hitAreas) => {
    console.log('Hit:', hitAreas);
});

// Manual hit test
const hits = model.hitTest(x, y);
```

### Focus (Eye Tracking)

```typescript
// Manual focus
model.focus(mouseX, mouseY);

// Instant focus
model.focus(mouseX, mouseY, true);
```

## Options

```typescript
const model = await Live2DModel.from('model.json', {
    // Automator options
    autoUpdate: true,        // Auto-update via Ticker
    autoHitTest: true,       // Auto hit-test on tap
    autoFocus: true,         // Auto eye tracking
    ticker: customTicker,    // Custom Ticker

    // MotionManager options
    motionPreload: MotionPreloadStrategy.IDLE, // ALL | IDLE | NONE
    idleMotionGroup: 'Idle'  // Custom idle group name
});
```

## Events

```typescript
model.on('load', () => {});          // Resources loaded
model.on('ready', () => {});         // Model initialized
model.on('hit', (areas) => {});      // Hit areas tapped
model.on('destroy', () => {});       // Model destroyed
```

## Motion Priorities

```typescript
MotionPriority.NONE    // 0 - Lowest
MotionPriority.IDLE    // 1 - Idle animations
MotionPriority.NORMAL  // 2 - Interactions
MotionPriority.FORCE   // 3 - Interrupts all
```

## Destruction

```typescript
model.destroy({
    children: true,
    texture: true,
    baseTexture: true
});
```

## Important Constants

```typescript
// Default idle groups
Cubism 2: 'idle'
Cubism 4: 'Idle'

// Motion preload strategies
MotionPreloadStrategy.ALL    // Preload all motions
MotionPreloadStrategy.IDLE   // Preload only idle (default)
MotionPreloadStrategy.NONE   // No preload
```

## Common Motion Groups

- `Idle` / `idle` - Idle animations
- `TapBody` / `tap_body` - Body tap
- `TapHead` / `tap_head` - Head tap
- `PinchIn` / `pinch_in` - Pinch in
- `PinchOut` / `pinch_out` - Pinch out
- `Shake` / `shake` - Shake

## Tips

1. Always set `window.PIXI = PIXI` for auto-update
2. Use `motionPreload: IDLE` for better performance
3. Destroy models when done to free memory
4. Use appropriate motion priorities
5. Check `hitTest()` return before processing

## Resources

- Full docs: https://guansss.github.io/pixi-live2d-display
- GitHub: https://github.com/guansss/pixi-live2d-display
- API Reference: https://guansss.github.io/pixi-live2d-display/api/index.html
