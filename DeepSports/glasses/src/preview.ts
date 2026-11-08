// Phone-side page: mirrors the glasses text, and (with ?preview) acts as a stand-in display
// in a normal browser so the app can be checked without the Even app or the simulator.
import type { Display, DisplayInput, Slot } from './display.ts'

function el(slot: Slot): HTMLElement | null {
  return document.getElementById(`g2-${slot}`)
}

export function mirror(slot: Slot, text: string): void {
  const node = el(slot)
  if (node) node.textContent = text
}

/** Wrap a display so everything it shows is also mirrored on the phone page. */
export function withMirror(d: Display): Display {
  return {
    async start(header, body) {
      mirror('header', header)
      mirror('body', body)
      await d.start(header, body)
    },
    async setText(slot, text) {
      mirror(slot, text)
      await d.setText(slot, text)
    },
    onInput: (cb) => d.onInput(cb),
    exit: () => d.exit(),
  }
}

const KEYS: Record<string, DisplayInput> = {
  Enter: 'tap',
  ' ': 'tap',
  ArrowUp: 'up',
  ArrowDown: 'down',
  Escape: 'double',
  d: 'double',
}

/** Browser-only display: keys (Enter/Space tap, arrows swipe, Esc/d double-tap) or the buttons. */
export function createPreviewDisplay(): Display {
  document.body.classList.add('preview')
  return {
    async start(header, body) {
      mirror('header', header)
      mirror('body', body)
    },
    async setText(slot, text) {
      mirror(slot, text)
    },
    onInput(cb) {
      const onKey = (e: KeyboardEvent) => {
        const input = KEYS[e.key]
        if (input) {
          e.preventDefault()
          cb(input)
        }
      }
      const onClick = (e: MouseEvent) => {
        const input = (e.target as HTMLElement).closest('[data-input]')?.getAttribute('data-input')
        if (input) cb(input as DisplayInput)
      }
      window.addEventListener('keydown', onKey)
      document.addEventListener('click', onClick)
      return () => {
        window.removeEventListener('keydown', onKey)
        document.removeEventListener('click', onClick)
      }
    },
    exit() {
      mirror('header', '')
      mirror('body', '(exited)')
    },
  }
}
