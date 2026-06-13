const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  setAlwaysOnTop: (flag) => ipcRenderer.send('set-always-on-top', flag),
  setTransparent: (flag) => ipcRenderer.send('set-transparent', flag),
  setAspectRatio: (ratio) => ipcRenderer.send('set-aspect-ratio', ratio),
  setSize: (width, height) => ipcRenderer.send('set-size', { width, height }),
})
