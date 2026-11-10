// Pure helpers and catalog facts, with no React, so Node's test runner can import them.

// -- catalog facts used for labels (NIST SP 800-171 Rev 2 families) ------------------------

export const FAMILIES = [
  ['AC', '3.1', 'Access Control'],
  ['AT', '3.2', 'Awareness and Training'],
  ['AU', '3.3', 'Audit and Accountability'],
  ['CM', '3.4', 'Configuration Management'],
  ['IA', '3.5', 'Identification and Authentication'],
  ['IR', '3.6', 'Incident Response'],
  ['MA', '3.7', 'Maintenance'],
  ['MP', '3.8', 'Media Protection'],
  ['PS', '3.9', 'Personnel Security'],
  ['PE', '3.10', 'Physical Protection'],
  ['RA', '3.11', 'Risk Assessment'],
  ['CA', '3.12', 'Security Assessment'],
  ['SC', '3.13', 'System and Communications Protection'],
  ['SI', '3.14', 'System and Information Integrity'],
].map(([code, number, name]) => ({ code, number, name }))

const FAMILY_BY_NUMBER = Object.fromEntries(FAMILIES.map((f) => [f.number, f.code]))

/** "3.5.3" -> "IA.L2-3.5.3", the CMMC Level 2 practice identifier. */
export function cmmcId(reqId) {
  const code = FAMILY_BY_NUMBER[reqId.split('.').slice(0, 2).join('.')]
  return code ? `${code}.L2-${reqId}` : reqId
}

export const THRESHOLD = 88
export const MAX_SCORE = 110
export const MIN_SCORE = -203
export const POAM_CITATION = '32 CFR §170.21'

export const DISCLAIMER =
  'CMMC Ready is a self-assessment aid. It does not certify compliance or replace an assessment by a C3PAO or DIBCAC.'

export const GITHUB_URL = 'https://github.com/AndrewPrice98/CMMC-Ready'

export function plural(n, one, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`
}

/** "A", "A and B", "A, B and C", "A, B, C and 2 more". */
export function listWords(items, max = 3) {
  if (items.length <= 1) return items.join('')
  if (items.length > max) return `${items.slice(0, max).join(', ')} and ${items.length - max} more`
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}
