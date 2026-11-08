// Platform-neutral display interface. The app only talks to this; even.ts (real SDK) and
// preview.ts (plain browser) implement it.

export type DisplayInput = 'tap' | 'up' | 'down' | 'double' | 'foreground' | 'background' | 'exit'

export type Slot = 'header' | 'body'

export interface Display {
  /** Create the page with initial text. Must be called once before setText. */
  start(header: string, body: string): Promise<void>
  /** Replace one container's text (flicker-free update). */
  setText(slot: Slot, text: string): Promise<void>
  onInput(cb: (input: DisplayInput) => void): () => void
  /** Ask the system to exit (shows its confirm dialog on the glasses). */
  exit(): void
}
