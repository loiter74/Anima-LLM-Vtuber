---
name: live2d
description: Comprehensive Live2D knowledge for Anima project integration using pixi-live2d-display library. Use when working with Live2D models, expressions, lip sync, or debugging Live2D-related issues. Covers model loading, motion/expression control, parameter manipulation, lip sync implementation, and troubleshooting known issues like expression clearing and Idle Motion looping.
---

# Live2D Development for Anima

This skill provides comprehensive knowledge about the pixi-live2d-display library and Live2D integration in the Anima project.

## Quick Reference

### Installation

```bash
npm install pixi-live2d-display
```

### Basic Usage

```javascript
import { Live2DModel } from 'pixi-live2d-display';
import * as PIXI from 'pixi.js';

// Expose PIXI to window
window.PIXI = PIXI;

// Load model
const model = await Live2DModel.from('shizuku.model.json');
app.stage.addChild(model);
```

### Common API Methods

#### Motion Control
```javascript
// Start a motion
await model.motion('Idle');  // Random Idle motion
await model.motion('TapBody', 0);  // Specific motion

// Expression
await model.expression(3);  // Expression by index
await model.expression();  // Random expression
```

#### Transform
```javascript
model.x = 100;
model.y = 100;
model.scale.set(2, 2);
model.rotation = Math.PI;
model.anchor.set(0.5, 0.5);
```

## Anima Project Integration

### Files Location
- **Frontend Service**: `frontend/features/live2d/services/Live2DService.ts`
- **Config**: `config/features/live2d.yaml`
- **Hook**: `frontend/features/live2d/hooks/useLive2D.ts`
- **Component**: `frontend/components/vtuber/live2d-viewer.tsx`

### Current Implementation

1. **Live2DService** (`frontend/features/live2d/services/Live2DService.ts`)
   - Wraps Live2DModel with additional features
   - Manages position, scale, expressions
   - Handles lip sync via setMouthOpen()

2. **Expression System**
   - ExpressionTimeline: Time-based expression playback
   - Emotion analyzers: Extract emotions from text
   - Timeline strategies: Calculate emotion segments

3. **Lip Sync**
   - AudioAnalyzer: Computes volume envelope at 50Hz
   - LipSyncEngine: Updates mouth parameters at ~30fps
   - Parameters: ParamMouthOpenY (index 19), ParamMouthForm (index 18)

### Known Issues

1. **Expression cannot be "cleared"**
   - Live2D API doesn't provide a way to clear expressions
   - Setting expression(-1) doesn't exist
   - Expressions persist until overridden

2. **Idle Motion auto-plays**
   - MotionManager automatically starts Idle motions when no other motion is playing
   - This causes the "looping expressions" effect
   - Cannot be disabled without stopping automator

3. **Lip sync parameters update but may not be visible**
   - ParamMouthOpenY updates correctly (values to 1.000)
   - Visual effect may not be obvious due to model design
   - May need to control additional parameters

## API Reference

### Live2DModel Class

**Methods:**
- `from(source, options)` - Load model from settings file
- `motion(group, index?, priority?)` - Start motion
- `expression(id?)` - Set expression
- `focus(x, y, instant?)` - Set focus position
- `tap(x, y)` - Tap on model (hit testing)
- `hitTest(x, y)` - Get hit areas
- `update(dt)` - Update model (called by automator)
- `destroy()` - Clean up resources

**Properties:**
- `internalModel` - Core Live2D model
- `textures` - PIXI textures
- `automator` - Auto-update manager
- `anchor` - Anchor point (0,0 = top-left, 1,1 = bottom-right)

### Automator Class

**Options:**
- `autoUpdate` - Auto-update model (default: true)
- `autoHitTest` - Auto hit-test on tap (default: true)
- `autoFocus` - Auto focus on pointer move (default: true)
- `ticker` - PIXI ticker for updates

**Key Methods:**
- `autoUpdate` - Get/set auto update state
- `autoHitTest` - Get/set hit testing
- `autoFocus` - Get/set focus tracking

### MotionManager Class

**Key Behavior:**
- Auto-starts Idle motions when no motion is playing
- `shouldRequestIdleMotion()` - Checks if idle motion needed
- `startRandomMotion(group, priority)` - Start random motion from group
- `stopAllMotions()` - Stop all playing motions

**Priority Levels:**
- `MotionPriority.IDLE` - Lowest priority, can be overridden
- `MotionPriority.NORMAL` - Normal priority
- `MotionPriority.FORCE` - Highest priority, cannot be overridden

### ExpressionManager Class

**Methods:**
- `setExpression(id)` - Set expression by index or name
- `setRandomExpression()` - Set random expression
- `resetExpression()` - Reset to default (may be called by motion)
- `restoreExpression()` - Restore expression after motion

## Troubleshooting

### Problem: Expressions keep changing
**Cause**: Idle Motion is auto-playing (designed behavior)
**Solution**: This is normal. To reduce changes:
- Use models with fewer Idle motions
- Or accept the behavior as "lively" character

### Problem: Can't clear expression
**Cause**: Live2D API doesn't provide clearExpression method
**Workaround**: Set a neutral expression or override with another expression

### Problem: Lip sync not visible
**Possible causes**:
1. Model design (mouth animation not obvious)
2. Need to control more parameters
3. Parameter values too small

**Debug steps**:
1. Check parameter values in logs: Look for "嘴部参数更新"
2. Verify ParamMouthOpenY index is correct
3. Try controlling ParamMouthForm as well
4. Check if Expression is overriding parameters

### Problem: Model doesn't center
**Solutions**:
- Use `model.anchor.set(0.5, 0.5)` to center anchor
- Calculate position as `containerWidth/2 + xOffset`
- See `Live2DService.autoScaleModel()` for implementation

## Configuration

### Model Settings
```yaml
# config/features/live2d.yaml
enabled: true
model:
  path: "/live2d/hiyori/Hiyori.model3.json"
  scale: 0.5
  position:
    x: 0
    y: 0

emotion_map:
  happy: 3
  sad: 1
  angry: 2
  surprised: 4
  neutral: 0
  thinking: 5

lip_sync:
  enabled: true
  sensitivity: 2.0
  smoothing: 0.15
  min_threshold: 0.01
  max_value: 1.0
  use_mouth_form: true
```

## Development Workflow

### Adding New Expression
1. Add to `emotion_map` in config/features/live2d.yaml
2. Add to `valid_emotions` list
3. Rebuild backend

### Testing Lip Sync
1. Check console for "嘴部参数更新" logs
2. Look for high values (0.5+)
3. If values are high but no visual effect, check model design

### Debugging Model State
```javascript
// In browser console
const service = window.__live2dService;
const model = service.model;

// Check model state
console.log("Current expression:", service.currentExpression);
console.log("Model position:", { x: model.x, y: model.y });
console.log("Model scale:", model.scale.x);

// Check internal model
console.log("MotionManager:", model.internalModel.motionManager);
console.log("ExpressionManager:", model.internalModel.motionManager.expressionManager);

// Test expression
await model.expression(3);  // Happy
```

## Common Patterns

### Loading Model
```typescript
const model = await Live2DModel.from(modelPath);
app.stage.addChild(model);
model.anchor.set(0.5, 0.5);
```

### Positioning Model
```typescript
const centerX = canvasWidth / 2;
const centerY = canvasHeight / 2;
const yOffset = canvasHeight * (yOffsetPercent / 100);
model.x = centerX + xOffset;
model.y = centerY + yOffset;
```

### Setting Expression
```typescript
// By index
await model.expression(3);

// Random
await model.expression();
```

### Lip Sync
```typescript
// Update mouth parameter
const coreModel = model.internalModel.coreModel;
const mouthIndex = coreModel.getParameterIndex('ParamMouthOpenY');
coreModel.setParameterValueByIndex(mouthIndex, value);
```

### Stopping/Destroying
```typescript
// Stop all motions
model.internalModel.motionManager.stopAllMotions();

// Destroy model
model.destroy({ texture: true });
```

## Reference Documentation

For complete API documentation, see the reference files:

- **[SUMMARY.md](references/SUMMARY.md)** - Complete guide (16KB)
- **[QUICK_REFERENCE.md](references/QUICK_REFERENCE.md)** - Quick reference card (3.6KB)
- **[Live2DModel.ts](references/Live2DModel.ts)** - Main API
- **[MotionManager.ts](references/MotionManager.ts)** - Motion system
- **[ExpressionManager.ts](references/ExpressionManager.ts)** - Expression system
- **[Automator.ts](references/Automator.ts)** - Auto-update system
- **[InternalModel.ts](references/InternalModel.ts)** - Internal model structure

## Key Notes

- Always expose `window.PIXI = PIXI` before using Live2DModel
- Expressions and Motions are separate systems
- Idle motions auto-play by design
- Cannot "clear" expressions, only override with new ones
- Automator controls auto-update behavior
- Hit testing requires event mode to be 'static'
