/**
 * feedback — audio + haptic primitives for the bottle scanner UI.
 *
 * Sundance-safety property: when Federico the Manager scans a bottle at
 * 11:47pm in a noisy bar with gloves on, he should KNOW the scan landed
 * without having to look at the screen. Three signals fire in parallel
 * for each event:
 *
 *   ┌────────────┬──────────────────────────┬─────────────────────────┐
 *   │ Event      │ Audio (Web Audio API)    │ Haptic (Vibration API)  │
 *   ├────────────┼──────────────────────────┼─────────────────────────┤
 *   │ success    │ 200Hz chirp, 80ms        │ single 60ms pulse       │
 *   │ failure    │ 90Hz buzz, 200ms         │ pattern 60-100-60       │
 *   │ undo       │ 150Hz blip, 120ms        │ pattern 40-50-40        │
 *   └────────────┴──────────────────────────┴─────────────────────────┘
 *
 * The visual flash on the scanner card is the THIRD signal — handled by
 * BottleScanCard since it owns the viewport. Sound + haptic alone work
 * with eyes elsewhere; sound + visual work even when phone is silent;
 * haptic + visual work even in a very loud bar. Two-of-three redundancy.
 *
 * iOS Safari quirk: AudioContext cannot be created without a prior user
 * gesture. `primeAudio()` MUST be called inside a click/tap event handler
 * (the first scan attempt or the "Allow camera" tap is a good moment).
 * After priming, subsequent calls to playSuccessFeedback / etc work
 * unattended for the rest of the session.
 *
 * Graceful degradation:
 *   - No AudioContext support (very old browsers) → silent, no exception
 *   - No vibration API (most desktops) → no-op, no exception
 *   - Page tab not visible → audio still plays (intentional — operator
 *     might be glancing at a bottle, not the screen)
 *
 * NOT in scope:
 *   - Configurable volume / mute toggle (Phase 7 if requested)
 *   - Different sound packs (Phase 7 if requested)
 *   - Speech synthesis ("Bacardi Rum 1L confirmed") — too long for fast scans
 */

// ─── Audio context — singleton, lazily created ──────────────────────────────

let audioCtx: AudioContext | null = null
let audioPrimed = false

/**
 * Initialise the AudioContext. Call from inside a user-gesture handler
 * (camera-permission button click, first scan, etc.) to satisfy iOS
 * Safari's audio policy. Safe to call multiple times — second+ calls
 * are no-ops.
 */
export function primeAudio(): void {
  if (audioPrimed) return
  try {
    // Standard + webkit fallback for older Safari
    const Ctor =
      (window as unknown as { AudioContext?: typeof AudioContext })
        .AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext
    if (!Ctor) return
    audioCtx = new Ctor()
    // Some browsers create the context in "suspended" state; resume here
    // so the first playback isn't delayed by a few hundred ms
    if (audioCtx.state === 'suspended') {
      void audioCtx.resume()
    }
    audioPrimed = true
  } catch {
    // Silent — audio simply unavailable. Visual + haptic still fire.
  }
}

/**
 * Play a short tone with the given frequency, duration, and waveform.
 * No-op if audio isn't primed or AudioContext init failed.
 */
function playTone(
  frequencyHz: number,
  durationMs: number,
  waveform: OscillatorType = 'sine',
): void {
  if (!audioCtx) return
  try {
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    osc.type = waveform
    osc.frequency.value = frequencyHz

    // Envelope: ramp up over 8ms, hold, ramp down over 12ms.
    // Prevents the "click" artefact a pure rectangular envelope would
    // produce on start/stop. 0.4 peak amplitude — clearly audible
    // without being startling.
    const now = audioCtx.currentTime
    const durSec = durationMs / 1000
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(0.4, now + 0.008)
    gain.gain.setValueAtTime(0.4, now + durSec - 0.012)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + durSec)

    osc.connect(gain).connect(audioCtx.destination)
    osc.start(now)
    osc.stop(now + durSec)
  } catch {
    // Silent — playback failure should never crash the scanner
  }
}

/**
 * Trigger haptic feedback. No-op when Vibration API is unavailable
 * (most desktops) or when the page isn't focused (some mobile browsers).
 */
function vibrate(pattern: number | number[]): void {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      navigator.vibrate(pattern)
    }
  } catch {
    // Silent
  }
}

// ─── Public API ─────────────────────────────────────────────────────────────

/** Scan succeeded — clear ascending chirp + single pulse. */
export function playSuccessFeedback(): void {
  playTone(200, 80, 'sine')
  vibrate(60)
}

/** Scan failed — lower-pitched, slightly longer, distinct from success. */
export function playFailureFeedback(): void {
  playTone(90, 200, 'sawtooth')
  vibrate([60, 100, 60])
}

/** Undo confirmed — middle pitch, double-pulse pattern. */
export function playUndoFeedback(): void {
  playTone(150, 120, 'triangle')
  vibrate([40, 50, 40])
}

/** Hint for test/debug code — true once primeAudio() has succeeded. */
export function isAudioPrimed(): boolean {
  return audioPrimed
}
