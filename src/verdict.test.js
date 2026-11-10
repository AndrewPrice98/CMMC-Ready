// Run with `npm test` (Node's built-in test runner; no extra dependencies).
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { conditionalStatus, verdict } from './verdict.js'

/** A minimal overview response. Deductions are [req_id, points] pairs. */
function overview({
  score, deductions = [], blockers = [], conditional = false, notAssessed = 0, sspMissing = false,
}) {
  return {
    score: {
      score,
      deductions: deductions.map(([reqId, points]) => ({ req_id: reqId, points, reason: 'Not met' })),
      not_assessed: notAssessed,
    },
    poam_blocker_ids: blockers,
    conditional_eligible: conditional,
    provisional: sspMissing || notAssessed > 0,
    ssp_missing: sspMissing,
  }
}

describe('verdict', () => {
  it('88 or more with blockers: clears the threshold but names what cannot go on a POA&M', () => {
    const ov = overview({ score: 90, deductions: [['3.8.8', 3], ['3.1.3', 1]], blockers: ['3.8.8'] })
    assert.deepEqual(verdict(ov), {
      tone: 'warn',
      text: "Clears the 88-point threshold, but MP.L2-3.8.8 can't be placed on a POA&M under 32 CFR §170.21, "
        + 'so conditional status needs it met first.',
    })
    assert.equal(conditionalStatus(ov).label, 'Not yet')
  })

  it('88 or more without blockers: meets the threshold and every gap can go on a POA&M', () => {
    const ov = overview({ score: 107, deductions: [['3.1.3', 1], ['3.1.4', 1], ['3.3.3', 1]], conditional: true })
    assert.deepEqual(verdict(ov), {
      tone: 'good',
      text: 'Meets the 88-point threshold for conditional Level 2 status, and all 3 open gaps can go on a POA&M '
        + 'with closeout within 180 days.',
    })
    assert.equal(conditionalStatus(ov).label, 'Eligible')
  })

  it('under 88 with blockers: points short, and the blockers by CMMC ID', () => {
    const ov = overview({ score: 86, deductions: [['3.5.3', 3], ['3.8.8', 3]], blockers: ['3.5.3', '3.8.8'] })
    assert.deepEqual(verdict(ov), {
      tone: 'bad',
      text: "2 points short of conditional status (88), and IA.L2-3.5.3 and MP.L2-3.8.8 can't be placed on a "
        + 'POA&M under 32 CFR §170.21.',
    })
    assert.equal(conditionalStatus(ov).label, 'Not yet')
  })

  it('under 88 without blockers', () => {
    const ov = overview({ score: 87, deductions: [['3.1.3', 1]] })
    assert.equal(verdict(ov).text, '1 point short of conditional status (88); every open gap could go on a POA&M.')
  })

  it('SSP missing: 3.12.4 is a blocker and the sentence is marked provisional', () => {
    const ov = overview({ score: 95, deductions: [['3.1.3', 1]], blockers: ['3.12.4'], sspMissing: true })
    const v = verdict(ov)
    assert.match(v.text, /CA\.L2-3\.12\.4 can't be placed on a POA&M/)
    assert.ok(v.text.endsWith('(provisional — SSP missing).'), v.text)
    assert.equal(conditionalStatus(ov).label, 'Provisional')
  })

  it('SSP missing among many blockers: 3.12.4 is named first', () => {
    const ov = overview({
      score: 41, deductions: [['3.2.1', 5], ['3.3.1', 5], ['3.4.1', 5], ['3.5.3', 5]],
      blockers: ['3.2.1', '3.3.1', '3.4.1', '3.5.3', '3.12.4'], sspMissing: true,
    })
    assert.equal(verdict(ov).text,
      "47 points short of conditional status (88), and CA.L2-3.12.4, AT.L2-3.2.1, AU.L2-3.3.1 and 2 more can't be "
      + 'placed on a POA&M under 32 CFR §170.21 (provisional — SSP missing).')
  })

  it('provisional (not assessed) never reads as Eligible, even when the server says eligible', () => {
    const ov = overview({ score: 105, deductions: [['3.1.3', 1]], notAssessed: 3, conditional: true })
    const v = verdict(ov)
    assert.equal(v.tone, 'warn')
    assert.ok(v.text.endsWith('(provisional — 3 requirements not assessed).'), v.text)
    assert.equal(conditionalStatus(ov).label, 'Provisional')
  })

  it('all met: the maximum score', () => {
    const ov = overview({ score: 110, conditional: true })
    assert.deepEqual(verdict(ov), {
      tone: 'good', text: 'Every requirement is met or not applicable: the maximum score of 110.',
    })
    assert.equal(conditionalStatus(ov).label, 'Eligible')
  })

  it('the sentence and the chip agree: no "Meets" sentence when the server says not eligible', () => {
    const ov = overview({ score: 100, deductions: [['3.1.3', 1]] })
    assert.ok(!verdict(ov).text.startsWith('Meets'))
    assert.equal(conditionalStatus(ov).label, 'Not yet')
  })
})
