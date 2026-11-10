// The conditional-status verdict on the overview. Pure functions over the overview API
// response, so the sentence and the status chip always come from the same data:
// the server's `conditional_eligible` and `poam_blocker_ids`.
import { POAM_CITATION, THRESHOLD, cmmcId, listWords, plural } from './lib.js'

const SSP = '3.12.4'

export function scoreTone(score) {
  if (score >= THRESHOLD) return 'good'
  if (score >= 0) return 'warn'
  return 'bad'
}

/** Why the score is provisional; empty when it is final. */
export function provisionalReasons(ov) {
  const reasons = []
  if (ov.score.not_assessed) reasons.push(`${plural(ov.score.not_assessed, 'requirement')} not assessed`)
  if (ov.ssp_missing) reasons.push('SSP missing')
  return reasons
}

/** The "Conditional Level 2 status" chip. A provisional score never reads as Eligible. */
export function conditionalStatus(ov) {
  if (ov.provisional) return { tone: 'warn', glyph: '!', label: 'Provisional' }
  if (ov.conditional_eligible) return { tone: 'good', glyph: '✓', label: 'Eligible' }
  return { tone: 'bad', glyph: '✕', label: 'Not yet' }
}

/** One sentence on conditional Level 2 status (32 CFR 170.21). */
export function verdict(ov) {
  const score = ov.score.score
  // The missing SSP is named first: without it the assessment can't be submitted at all.
  const blockers = [...(ov.poam_blocker_ids || [])].sort((a, b) => (b === SSP) - (a === SSP))
  const gaps = ov.score.deductions.length
  const names = listWords(blockers.map(cmmcId))
  const cant = `can't be placed on a POA&M under ${POAM_CITATION}`
  let tone
  let text
  if (ov.conditional_eligible) {
    tone = 'good'
    text = gaps === 0
      ? 'Every requirement is met or not applicable: the maximum score of 110'
      : `Meets the ${THRESHOLD}-point threshold for conditional Level 2 status, and `
        + `${gaps === 1 ? 'the one open gap' : `all ${gaps} open gaps`} can go on a POA&M with closeout within 180 days`
  } else if (score >= THRESHOLD) {
    tone = 'warn'
    text = blockers.length
      ? `Clears the ${THRESHOLD}-point threshold, but ${names} ${cant}, so conditional status needs `
        + `${blockers.length === 1 ? 'it' : 'them'} met first`
      : `Clears the ${THRESHOLD}-point threshold, but conditional status is not available yet`
  } else {
    const short = `${plural(THRESHOLD - score, 'point')} short of conditional status (${THRESHOLD})`
    if (blockers.length) {
      tone = 'bad'
      text = `${short}, and ${names} ${cant}`
    } else {
      tone = scoreTone(score)
      text = `${short}; every open gap could go on a POA&M`
    }
  }
  if (ov.provisional) {
    const reasons = provisionalReasons(ov)
    text += ` (provisional — ${reasons.length ? reasons.join('; ') : 'not final'})`
    if (tone === 'good') tone = 'warn'
  }
  return { tone, text: `${text}.` }
}
