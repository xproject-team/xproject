/**
 * scanQueue — localStorage-backed offline queue for scan submissions.
 *
 * Sundance-safety property: a scan is never lost just because the network
 * blips for 5 seconds. If the POST fails with a network-class error, we
 * stash the request body in localStorage; when connectivity returns, we
 * drain the queue and submit each one (idempotency on the server makes
 * retries safe).
 *
 * Design decisions:
 *   - Keyed per-tenant (`xproject:scanQueue:<tenantId>`) so two users on
 *     the same browser never cross-contaminate.
 *   - Each entry carries its own client_event_id, set at queue time. The
 *     UUID is the contract with the server: same UUID = same scan, no
 *     matter how many drain attempts happen.
 *   - Bounded at MAX_QUEUE_SIZE so a long offline period can't exhaust
 *     localStorage. Past the limit we drop the OLDEST entry (newer scans
 *     are more relevant for a live event).
 *   - Each entry tracks attempt_count + last_error. After MAX_ATTEMPTS
 *     we mark it `failed` (not removed) so the UI can show it to the
 *     operator for manual triage. Failed scans never auto-retry again.
 *
 * NOT in scope:
 *   - Cross-tab sync. Single-tab usage covers Sundance.
 *   - Background workers. Drains run on `online` event + on app mount.
 *   - Server-side mirror. localStorage IS the persistence.
 */

const KEY_PREFIX = 'xproject:scanQueue:'
const MAX_QUEUE_SIZE = 200
const MAX_ATTEMPTS = 5

export interface QueuedScan {
  /** Idempotency UUID — also sent in the body. Stable for the entry's lifetime. */
  client_event_id: string
  /** The full POST body to /warehouse/scans. */
  body: Record<string, unknown>
  /** Wall-clock when the user actually scanned (not when we drain). */
  queued_at: number
  /** Drain attempt count. Capped at MAX_ATTEMPTS. */
  attempt_count: number
  /** Last error message, for UI surfacing. */
  last_error: string | null
  /** Terminal failure — no more auto-drain attempts. */
  failed: boolean
}

function storageKey(tenantId: string): string {
  return KEY_PREFIX + tenantId
}

/** Read the entire queue for a tenant. Returns [] on missing or corrupt. */
export function readQueue(tenantId: string): QueuedScan[] {
  try {
    const raw = localStorage.getItem(storageKey(tenantId))
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? (parsed as QueuedScan[]) : []
  } catch {
    return []
  }
}

/** Persist the entire queue. */
function writeQueue(tenantId: string, queue: QueuedScan[]): void {
  try {
    localStorage.setItem(storageKey(tenantId), JSON.stringify(queue))
  } catch {
    // Silent — most likely quota exceeded. The next drain may succeed.
  }
}

/** Append a scan to the back of the queue. Drops oldest if full. */
export function enqueue(
  tenantId: string,
  body: Record<string, unknown>,
  client_event_id: string,
  initialError: string,
): QueuedScan {
  const queue = readQueue(tenantId)
  const entry: QueuedScan = {
    client_event_id,
    body,
    queued_at: Date.now(),
    attempt_count: 1,
    last_error: initialError,
    failed: false,
  }
  queue.push(entry)
  if (queue.length > MAX_QUEUE_SIZE) {
    // Drop oldest non-failed first; if we'd lose data we keep the failed
    // ones because they're already terminal and surface in UI.
    const idx = queue.findIndex((q) => !q.failed)
    if (idx >= 0) queue.splice(idx, 1)
    else queue.shift()
  }
  writeQueue(tenantId, queue)
  return entry
}

/** Remove an entry by UUID after a successful drain. */
export function ackSuccess(tenantId: string, client_event_id: string): void {
  const queue = readQueue(tenantId).filter(
    (q) => q.client_event_id !== client_event_id,
  )
  writeQueue(tenantId, queue)
}

/** Record a failed drain attempt. Marks `failed=true` once we hit MAX_ATTEMPTS. */
export function ackFailure(
  tenantId: string,
  client_event_id: string,
  error: string,
): void {
  const queue = readQueue(tenantId).map((q) => {
    if (q.client_event_id !== client_event_id) return q
    const next = q.attempt_count + 1
    return {
      ...q,
      attempt_count: next,
      last_error: error,
      failed: next >= MAX_ATTEMPTS,
    }
  })
  writeQueue(tenantId, queue)
}

/**
 * Drain the queue. For each non-failed entry, calls submitFn with its body.
 * Returns counts so the caller can show toast: "5 queued scans synced".
 *
 * Drain is sequential by design — Sundance bartender's WiFi is wobbly and
 * we don't want to thundering-herd the backend on reconnect. If any single
 * scan fails again, we keep going (the dedup on the server makes this safe).
 */
export async function drain(
  tenantId: string,
  submitFn: (body: Record<string, unknown>) => Promise<unknown>,
): Promise<{ attempted: number; succeeded: number; stillQueued: number }> {
  const queue = readQueue(tenantId)
  const drainable = queue.filter((q) => !q.failed)
  let succeeded = 0
  for (const entry of drainable) {
    try {
      await submitFn(entry.body)
      ackSuccess(tenantId, entry.client_event_id)
      succeeded++
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'drain failed'
      ackFailure(tenantId, entry.client_event_id, msg)
    }
  }
  const after = readQueue(tenantId)
  return {
    attempted: drainable.length,
    succeeded,
    stillQueued: after.filter((q) => !q.failed).length,
  }
}

/**
 * Heuristic: was this error caused by network unreachability rather than
 * a server-side reject? Network errors should queue; 4xx/403/422 should NOT
 * (those mean "the request will never succeed", queueing it is pointless).
 */
export function isNetworkError(err: unknown): boolean {
  if (typeof err !== 'object' || err === null) return false
  const e = err as Record<string, unknown>
  // axios sets `code` and `message` for network errors; status is undefined
  // when the request never reached the server.
  if ('response' in e && e.response) return false  // server reachable
  if (typeof e.code === 'string') {
    const c = e.code as string
    if (c === 'ERR_NETWORK' || c === 'ECONNABORTED' || c === 'ETIMEDOUT') return true
  }
  if (typeof e.message === 'string' && e.message.toLowerCase().includes('network')) {
    return true
  }
  return false
}

/** Generate a fresh UUID. Browser-native, no library needed. */
export function newClientEventId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  // Fallback for very old browsers — Sundance won't hit this but keeps tests safe.
  // Not crypto-secure but fine for an idempotency key.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}
