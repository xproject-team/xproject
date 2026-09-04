/**
 * The landing page's numbers — governed, sourced, verified.
 *
 * RULES (enforced by landingFacts.test.ts):
 *  - Real figures only. Nothing invented, nothing rounded up.
 *  - Every figure carries its source and the way to re-verify it.
 *  - NO revenue figures: the euros are the client's numbers and are not
 *    cleared for publication. The proof-strip grid accommodates an
 *    additional tile without restructuring — clearing a euro figure
 *    later means adding ONE entry here, nothing else.
 *
 * BEFORE ANY PROMOTION TO PRODUCTION: re-run each figure's verification
 * against the production database and update values that moved. These
 * were sourced 2026-09-04.
 */

export interface LandingFact {
  label: string
  value: number
  /** Where the number came from + how to re-verify. Not rendered. */
  source: string
}

export const LANDING_FACTS: LandingFact[] = [
  {
    label: 'Events run in production',
    value: 4,
    source:
      'Production events table, status=completed, verified repeatedly ' +
      'during the Aug 2026 reconciliation work. Verify: SELECT count(*) ' +
      "FROM events WHERE upper(status::text)='COMPLETED'.",
  },
  {
    label: 'Orders processed',
    value: 15_387,
    source:
      'Production event_orders; the 22 Aug 2026 fiscal-identity audit held ' +
      'on 15,387/15,387 rows. Verify: SELECT count(*) FROM event_orders ' +
      'WHERE confirmed_line_count > 0.',
  },
  {
    label: 'Post-event reports generated',
    value: 29,
    source:
      '21 report rows verified on production 22 Aug 2026, plus 8 (IT+EN ×4 ' +
      'events) written by the 29 Aug v4 regenerations, each with VERIFY ' +
      'PASS. Re-verify before promotion: SELECT count(*) FROM reports.',
  },
  {
    label: 'Automated tests',
    value: 726,
    source:
      'Backend pytest suite 690 + frontend vitest 36 as of 2026-09-04 ' +
      '(this commit). Verify: pytest -q and npm test locally.',
  },
  {
    label: 'Database migrations applied',
    value: 62,
    source:
      'alembic/versions file count, 2026-09-04. Verify: ls ' +
      'alembic/versions/*.py | wc -l (and alembic history for the chain).',
  },
  // ── Reserved slots — NOT rendered until their numbers are real ──────
  // Stock movements: the category is cleared but no verified count
  // exists yet. Fill from production before adding:
  //   SELECT count(*) FROM stock_transactions;
  // Season revenue: the CLIENT'S figure, not cleared for publication.
  // When (and only when) cleared, add here with its verification query;
  // the grid takes the extra tile without restructuring.
]
