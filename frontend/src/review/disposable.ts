export type Disposer = () => void

export class DisposerStack {
  private readonly disposers: Disposer[] = []
  private disposed = false

  add(disposer: Disposer): Disposer {
    if (this.disposed) {
      disposer()
      return disposer
    }
    this.disposers.push(disposer)
    return disposer
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    for (const disposer of this.disposers.reverse()) disposer()
    this.disposers.length = 0
  }
}
