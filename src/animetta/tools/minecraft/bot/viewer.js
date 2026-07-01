// viewer.js — optional first-person Mineflayer web viewer.
// The wrapper keeps prismarine-viewer lazy and non-fatal for headless runs.

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 3007;

export function webViewerConfigFromEnv(env = process.env) {
  const enabled = String(env.MC_WEB_VIEWER_ENABLED || '').toLowerCase() === 'true';
  const host = env.MC_WEB_VIEWER_HOST || DEFAULT_HOST;
  const rawPort = Number.parseInt(env.MC_WEB_VIEWER_PORT || `${DEFAULT_PORT}`, 10);
  const port = Number.isFinite(rawPort) ? rawPort : DEFAULT_PORT;
  const rawHudPort = Number.parseInt(env.MC_WEB_VIEWER_HUD_PORT || `${port + 1}`, 10);
  const hudPort = Number.isFinite(rawHudPort) ? rawHudPort : port + 1;
  return { enabled, host, port, hudPort };
}

function serializeItem(item) {
  if (!item) return null;
  return {
    name: item.name || 'unknown',
    count: item.count || 1,
    slot: item.slot,
  };
}

function botVersion(bot) {
  return bot?.version || bot?.registry?.version?.minecraftVersion || '1.20.1';
}

async function createTextureResolver({ bot, importAssets = async () => import('minecraft-assets') }) {
  try {
    const assetsModule = await importAssets();
    const loadAssets = assetsModule.default || assetsModule;
    const assets = loadAssets(botVersion(bot));

    return (name) => {
      if (!name) return null;
      try {
        return assets.getImageContent(name) || null;
      } catch (_err) {
        return null;
      }
    };
  } catch (_err) {
    return () => null;
  }
}

export function createHudSnapshot(bot) {
  const slots = bot?.inventory?.slots || [];
  const inventoryItems = typeof bot?.inventory?.items === 'function'
    ? bot.inventory.items().map(serializeItem).filter(Boolean)
    : [];
  const selectedSlot = Number.isInteger(bot?.quickBarSlot) ? bot.quickBarSlot : 0;
  const selectedItem = serializeItem(bot?.heldItem || slots[36 + selectedSlot]);
  const hotbar = Array.from({ length: 9 }, (_, idx) => serializeItem(slots[36 + idx]));

  return {
    health: Math.round((bot?.health ?? 0) * 10) / 10,
    food: Math.round((bot?.food ?? 0) * 10) / 10,
    selectedSlot,
    selectedItem,
    hotbar,
    inventory: inventoryItems,
  };
}

export function renderHudPage({ viewerUrl }) {
  const escapedViewerUrl = JSON.stringify(viewerUrl);
  return `<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Animetta MC First-Person HUD</title>
  <style>
    html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: #000; image-rendering: pixelated; font-family: system-ui, sans-serif; }
    #viewer { position: fixed; inset: 0; width: 100%; height: 100%; border: 0; }
    #hud { position: fixed; inset: 0; pointer-events: none; color: white; text-shadow: 0 2px 4px #000; }
    #crosshair { position: absolute; left: 50%; top: 50%; width: 18px; height: 18px; margin: -9px 0 0 -9px; opacity: .85; }
    #crosshair:before, #crosshair:after { content: ""; position: absolute; background: rgba(255,255,255,.85); box-shadow: 0 0 2px #000; }
    #crosshair:before { left: 8px; top: 2px; width: 2px; height: 14px; }
    #crosshair:after { left: 2px; top: 8px; width: 14px; height: 2px; }
    #status { position: absolute; left: 50%; bottom: 86px; transform: translateX(-50%); display: grid; grid-template-columns: repeat(10, 18px); grid-auto-rows: 18px; gap: 2px; }
    .pip { width: 18px; height: 18px; font-size: 16px; line-height: 18px; text-align: center; filter: drop-shadow(0 2px 1px #000); }
    #hotbar { position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); display: grid; grid-template-columns: repeat(9, 48px); gap: 0; padding: 3px; background: rgba(12,12,12,.72); border: 3px solid #2a2a2a; box-shadow: inset 0 0 0 2px rgba(255,255,255,.14), 0 3px 12px rgba(0,0,0,.6); }
    .slot { width: 48px; height: 48px; box-sizing: border-box; border-top: 3px solid rgba(255,255,255,.38); border-left: 3px solid rgba(255,255,255,.3); border-right: 3px solid rgba(0,0,0,.58); border-bottom: 3px solid rgba(0,0,0,.62); background: rgba(68,68,68,.72); display: grid; place-items: center; position: relative; overflow: hidden; }
    .slot.selected { z-index: 1; outline: 3px solid #f5f5f5; outline-offset: -1px; background: rgba(104,104,104,.86); box-shadow: 0 0 0 2px #111, 0 0 14px rgba(255,255,255,.55); }
    .itemIcon { width: 34px; height: 34px; object-fit: contain; image-rendering: pixelated; filter: drop-shadow(2px 2px 0 rgba(0,0,0,.65)); }
    .fallbackIcon { width: 30px; height: 30px; border: 2px solid rgba(255,255,255,.35); background: linear-gradient(135deg, #8b6f47, #c5aa6a); box-shadow: inset -4px -4px rgba(0,0,0,.22); transform: rotate(-18deg); }
    .count { position: absolute; right: 4px; bottom: 0; font-size: 17px; font-weight: 900; color: #fff; text-shadow: 2px 2px #000; }
    #hand { position: absolute; right: 12%; bottom: 4px; width: 260px; height: 230px; transform: rotate(-12deg); transform-origin: 70% 100%; }
    #arm { position: absolute; right: 48px; bottom: -34px; width: 78px; height: 210px; background: linear-gradient(90deg, #7f5536 0 18%, #c48a59 18% 72%, #8a6044 72%); border: 5px solid rgba(50,32,22,.9); box-shadow: inset -12px 0 rgba(0,0,0,.18), 0 8px 20px rgba(0,0,0,.45); }
    #heldItemIcon { position: absolute; right: 100px; bottom: 104px; width: 96px; height: 96px; object-fit: contain; image-rendering: pixelated; transform: rotate(24deg); filter: drop-shadow(6px 6px 0 rgba(0,0,0,.55)); }
    #inventory { position: absolute; right: 18px; top: 18px; width: 188px; padding: 8px; box-sizing: border-box; border: 3px solid #2a2a2a; background: rgba(12,12,12,.55); box-shadow: inset 0 0 0 2px rgba(255,255,255,.12); }
    #inventoryGrid { display: grid; grid-template-columns: repeat(4, 40px); gap: 3px; }
    .miniSlot { width: 40px; height: 40px; box-sizing: border-box; border-top: 2px solid rgba(255,255,255,.28); border-left: 2px solid rgba(255,255,255,.22); border-right: 2px solid rgba(0,0,0,.58); border-bottom: 2px solid rgba(0,0,0,.62); background: rgba(60,60,60,.62); position: relative; display: grid; place-items: center; }
    .miniSlot .itemIcon { width: 27px; height: 27px; }
    .miniSlot .count { font-size: 12px; right: 2px; bottom: 0; }
  </style>
</head>
<body>
  <iframe id="viewer" src=${escapedViewerUrl}></iframe>
  <div id="hud">
    <div id="crosshair"></div>
    <div id="status"></div>
    <div id="hotbar"></div>
    <div id="hand"><div id="arm"></div><img id="heldItemIcon" alt=""></div>
    <div id="inventory"><div id="inventoryGrid"></div></div>
  </div>
  <script>
    const hotbar = document.getElementById('hotbar');
    const status = document.getElementById('status');
    const inventoryGrid = document.getElementById('inventoryGrid');
    const heldItemIcon = document.getElementById('heldItemIcon');
    function label(item) { return item ? item.name.replaceAll('_', ' ') : ''; }
    function textureUrl(item) { return item ? '/assets/item/' + encodeURIComponent(item.name) + '.png' : ''; }
    function addItemIcon(parent, item, className = 'itemIcon') {
      if (!item) return;
      const img = document.createElement('img');
      img.className = className;
      img.src = textureUrl(item);
      img.alt = '';
      img.title = label(item);
      img.onerror = () => {
        img.remove();
        const fallback = document.createElement('div');
        fallback.className = 'fallbackIcon';
        parent.appendChild(fallback);
      };
      parent.appendChild(img);
    }
    function addCount(parent, item) {
      if (item && item.count > 1) {
        const count = document.createElement('span');
        count.className = 'count';
        count.textContent = item.count;
        parent.appendChild(count);
      }
    }
    function renderPips(value, full, glyph, emptyGlyph) {
      return Array.from({ length: full }, (_, idx) => {
        const el = document.createElement('span');
        el.className = 'pip';
        el.textContent = idx < Math.ceil(value / 2) ? glyph : emptyGlyph;
        return el;
      });
    }
    function render(data) {
      status.replaceChildren(...renderPips(data.health, 10, '♥', '♡'), ...renderPips(data.food, 10, '●', '○'));
      hotbar.innerHTML = '';
      data.hotbar.forEach((item, idx) => {
        const el = document.createElement('div');
        el.className = 'slot' + (idx === data.selectedSlot ? ' selected' : '');
        addItemIcon(el, item);
        addCount(el, item);
        hotbar.appendChild(el);
      });
      heldItemIcon.src = textureUrl(data.selectedItem);
      heldItemIcon.style.display = data.selectedItem ? 'block' : 'none';
      inventoryGrid.innerHTML = '';
      data.inventory.slice(0, 16).forEach((item) => {
        const el = document.createElement('div');
        el.className = 'miniSlot';
        addItemIcon(el, item);
        addCount(el, item);
        inventoryGrid.appendChild(el);
      });
    }
    async function refresh() {
      try {
        const res = await fetch('/api/hud', { cache: 'no-store' });
        render(await res.json());
      } catch (err) {}
    }
    refresh();
    setInterval(refresh, 500);
  </script>
</body>
</html>`;
}

export async function startHudOverlay({
  bot,
  host,
  port,
  viewerUrl,
  importExpress = async () => import('express'),
  importAssets = async () => import('minecraft-assets'),
}) {
  const expressModule = await importExpress();
  const express = expressModule.default || expressModule;
  const app = express();
  const resolveTexture = await createTextureResolver({ bot, importAssets });

  app.get('/', (_req, res) => {
    res.type('html').send(renderHudPage({ viewerUrl }));
  });
  app.get('/api/hud', (_req, res) => {
    res.json(createHudSnapshot(bot));
  });
  app.get('/assets/item/:name.png', (req, res) => {
    const name = String(req.params.name || '').replace(/\.png$/i, '');
    const dataUrl = resolveTexture(name);
    if (!dataUrl) {
      res.status(404).end();
      return;
    }
    const base64 = dataUrl.replace(/^data:image\/png;base64,/, '');
    res.type('png').send(Buffer.from(base64, 'base64'));
  });

  const server = await new Promise((resolve, reject) => {
    const instance = app.listen(port, host, () => resolve(instance));
    instance.on('error', reject);
  });

  return {
    url: `http://${host}:${port}`,
    port,
    close: () => server.close(),
  };
}

export async function maybeStartFirstPersonViewer({
  bot,
  config,
  importViewer = async () => import('prismarine-viewer'),
  startHudOverlay: startHud = startHudOverlay,
  sendEvent = () => {},
  logger = console,
}) {
  const cfg = {
    enabled: false,
    host: DEFAULT_HOST,
    port: DEFAULT_PORT,
    hudPort: undefined,
    ...(config || {}),
  };
  if (!cfg.hudPort) cfg.hudPort = cfg.port + 1;

  if (!cfg.enabled) {
    return { started: false, reason: 'disabled' };
  }

  try {
    const viewer = await importViewer();
    const mineflayerViewer = viewer.mineflayer || viewer.default?.mineflayer;
    if (typeof mineflayerViewer !== 'function') {
      throw new Error('prismarine-viewer does not export mineflayer()');
    }

    mineflayerViewer(bot, {
      host: cfg.host,
      port: cfg.port,
      firstPerson: true,
    });

    const url = `http://${cfg.host}:${cfg.port}`;
    logger.log?.(`[viewer] first-person viewer started at ${url}`);
    sendEvent('first_person_viewer_started', { url, host: cfg.host, port: cfg.port });

    const hud = await startHud({
      bot,
      host: cfg.host,
      port: cfg.hudPort,
      viewerUrl: url,
    });
    logger.log?.(`[viewer] first-person HUD started at ${hud.url}`);
    sendEvent('first_person_hud_started', { url: hud.url, host: cfg.host, port: cfg.hudPort });
    return { started: true, url: hud.url, viewerUrl: url, hudUrl: hud.url };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    logger.warn?.(`[viewer] first-person viewer failed: ${message}`);
    sendEvent('first_person_viewer_error', { message, host: cfg.host, port: cfg.port });
    return { started: false, error: message };
  }
}
