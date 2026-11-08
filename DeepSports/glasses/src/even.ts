// Thin adapter over @evenrealities/even_hub_sdk (pre-1.0, so every SDK call lives here).
import {
  CreateStartUpPageContainer,
  RebuildPageContainer,
  OsEventTypeList,
  TextContainerProperty,
  TextContainerUpgrade,
  waitForEvenAppBridge,
  type EvenAppBridge,
} from '@evenrealities/even_hub_sdk'
import type { Display, DisplayInput, Slot } from './display.ts'

// Canvas is 576 x 288; the font's line height is 27 px.
const CONTAINERS: Record<Slot, { id: number; name: string; y: number; height: number; capture: 0 | 1 }> = {
  header: { id: 1, name: 'header', y: 0, height: 36, capture: 0 },
  body: { id: 2, name: 'body', y: 36, height: 252, capture: 1 },
}
// 4 px padding: body inner area 568 x 244 = 9 lines; width.ts budgets 560 px per line for slack.
const PADDING = 4

// A single tap arrives with no eventType (protobuf drops the zero value), so default to CLICK
// only *inside* an envelope that exists. Otherwise every other event would look like a tap.
function typeOf(envelope?: { eventType?: OsEventTypeList }): OsEventTypeList | null {
  if (!envelope) return null
  return envelope.eventType ?? OsEventTypeList.CLICK_EVENT
}

export async function createEvenDisplay(): Promise<Display> {
  const bridge: EvenAppBridge = await waitForEvenAppBridge()

  return {
    async start(header, body) {
      const text = (slot: Slot, content: string) => {
        const c = CONTAINERS[slot]
        return new TextContainerProperty({
          xPosition: 0,
          yPosition: c.y,
          width: 576,
          height: c.height,
          borderWidth: 0,
          borderColor: 0,
          paddingLength: PADDING,
          containerID: c.id,
          containerName: c.name,
          content: content.slice(0, 1000), // create/rebuild limit
          isEventCapture: c.capture,
          textColor: slot === 'header' ? 2 : 4, // header dimmer than scores
        })
      }
      const page = { containerTotalNum: 2, textObject: [text('header', header), text('body', body)] }
      const result = await bridge.createStartUpPageContainer(new CreateStartUpPageContainer(page))
      if (result !== 0) {
        // Startup page already exists (e.g. the WebView reloaded): rebuild it instead.
        const ok = await bridge.rebuildPageContainer(new RebuildPageContainer(page))
        if (!ok) console.error('page setup failed: create =', result, 'rebuild =', ok)
      }
    },

    async setText(slot, content) {
      const c = CONTAINERS[slot]
      await bridge.textContainerUpgrade(
        new TextContainerUpgrade({ containerID: c.id, containerName: c.name, content: content.slice(0, 2000) }),
      )
    },

    onInput(cb) {
      return bridge.onEvenHubEvent((event) => {
        const sys = typeOf(event.sysEvent)
        const txt = typeOf(event.textEvent)
        const is = (t: OsEventTypeList) => sys === t || txt === t
        let input: DisplayInput | null = null
        if (is(OsEventTypeList.DOUBLE_CLICK_EVENT)) input = 'double'
        else if (is(OsEventTypeList.CLICK_EVENT)) input = 'tap'
        else if (txt === OsEventTypeList.SCROLL_TOP_EVENT) input = 'up'
        else if (txt === OsEventTypeList.SCROLL_BOTTOM_EVENT) input = 'down'
        else if (sys === OsEventTypeList.FOREGROUND_ENTER_EVENT) input = 'foreground'
        else if (sys === OsEventTypeList.FOREGROUND_EXIT_EVENT) input = 'background'
        else if (sys === OsEventTypeList.SYSTEM_EXIT_EVENT || sys === OsEventTypeList.ABNORMAL_EXIT_EVENT)
          input = 'exit'
        if (input) cb(input)
      })
    },

    exit() {
      void bridge.shutDownPageContainer(1)
    },
  }
}
