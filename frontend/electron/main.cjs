const { app, BrowserWindow, screen, ipcMain } = require('electron')
const path = require('path')

// Disable GPU acceleration for compatibility
app.disableHardwareAcceleration()

let mainWindow = null

function createWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize

  // Default window size (9:16 aspect ratio, half size for screen fit)
  const windowWidth = 540
  const windowHeight = 960

  mainWindow = new BrowserWindow({
    width: windowWidth,
    height: windowHeight,
    x: width - windowWidth - 50,
    y: 50,
    transparent: false,
    frame: true,
    alwaysOnTop: false,
    resizable: true,
    minimizable: true,
    maximizable: true,
    backgroundColor: '#0a0a0f',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
    title: 'Animetta Live Stream',
    icon: path.join(__dirname, '../public/favicon.svg'),
  })

  // Always load from Vite dev server in development
  // The concurrent script ensures Vite is running first
  mainWindow.loadURL('http://localhost:3000/live-stream')

  // Open DevTools for debugging
  mainWindow.webContents.openDevTools({ mode: 'detach' })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  // Log when page loads
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[Electron] Page loaded successfully')
  })

  // Log errors
  mainWindow.webContents.on('did-fail-load', (event, errorCode, errorDescription) => {
    console.error('[Electron] Failed to load:', errorCode, errorDescription)
  })
}

// IPC handlers for window control
ipcMain.on('set-always-on-top', (event, flag) => {
  if (mainWindow) {
    mainWindow.setAlwaysOnTop(flag)
  }
})

ipcMain.on('set-transparent', (event, flag) => {
  if (mainWindow) {
    mainWindow.setBackgroundColor(flag ? '#00000000' : '#0a0a0f')
  }
})

ipcMain.on('set-aspect-ratio', (event, ratio) => {
  if (mainWindow) {
    if (ratio === '9:16') {
      mainWindow.setAspectRatio(9 / 16)
    } else if (ratio === '3:4') {
      mainWindow.setAspectRatio(3 / 4)
    } else {
      mainWindow.setAspectRatio(0) // Free resize
    }
  }
})

ipcMain.on('set-size', (event, { width, height }) => {
  if (mainWindow) {
    mainWindow.setSize(width, height)
  }
})

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow()
  }
})
