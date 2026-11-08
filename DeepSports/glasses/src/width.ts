// Approximate pixel widths for the G2 firmware font (proportional, one size).
// Advance widths for ASCII 32..126 in 1/16 px, taken from @evenrealities/pretext 0.1.4
// (which mirrors the firmware LVGL font). Kerning is ignored, so estimates run slightly wide.
const ASCII_ADV = [
  80, 64, 96, 240, 208, 224, 256, 64, 112, 112, 128, 160, 80, 160, 80, 128, 192, 128, 192, 192, 208,
  192, 192, 208, 192, 192, 64, 80, 160, 160, 160, 192, 272, 224, 192, 192, 192, 176, 176, 192, 192,
  96, 144, 192, 160, 256, 192, 192, 192, 192, 192, 192, 192, 192, 224, 256, 224, 224, 208, 112, 128,
  112, 160, 144, 0, 192, 176, 176, 176, 176, 160, 176, 176, 64, 112, 160, 64, 256, 176, 176, 176,
  176, 128, 176, 128, 192, 192, 256, 192, 192, 160, 144, 64, 144, 256,
]

/** Non-ASCII glyphs we use. All are in the firmware font (research doc's "reliable" list). */
export const GLYPHS: Record<string, number> = {
  '●': 20, // live
  '○': 20,
  '·': 5,
  '▲': 20,
  '▼': 20,
  '━': 20,
  '─': 20,
}

/** Text budget per line: the 576 px canvas minus padding (4 px each side) and some slack. */
export const BODY_WIDTH_PX = 560
/** Hard cap on characters per line, independent of pixels. */
export const MAX_LINE_CHARS = 34

export function charWidth(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0
  if (cp >= 32 && cp < 127) return ASCII_ADV[cp - 32] / 16
  return GLYPHS[ch] ?? 20 // unknown: assume wide (and the firmware may drop it)
}

export function textWidth(s: string): number {
  let w = 0
  for (const ch of s) w += charWidth(ch)
  return w
}

/** Cut a line so it fits both the pixel budget and the character cap. */
export function fit(s: string, maxPx = BODY_WIDTH_PX, maxChars = MAX_LINE_CHARS): string {
  const chars = [...s]
  if (chars.length <= maxChars && textWidth(s) <= maxPx) return s
  let out = ''
  for (const ch of chars) {
    const next = out + ch
    if ([...next].length > maxChars - 2 || textWidth(next + '..') > maxPx) break
    out = next
  }
  return out.trimEnd() + '..'
}

/** Pad with spaces on the right until `s` is at least `px` wide. */
export function padRightPx(s: string, px: number): string {
  let out = s
  while (textWidth(out) + charWidth(' ') <= px) out += ' '
  return out
}

/** Pad with spaces on the left so `s` ends at roughly `px` (right-aligned column). */
export function padLeftPx(s: string, px: number): string {
  let out = s
  while (textWidth(out) + charWidth(' ') <= px) out = ' ' + out
  return out
}
