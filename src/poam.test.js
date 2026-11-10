// Run with `npm test` (Node's built-in test runner; no extra dependencies).
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  addDays, closeoutDeadline, compareReqIds, daysBetween, dueFlags, isIsoDate, milestoneProgress, openGaps,
  poamBody, poamSummary, todayIso, validatePoamForm,
} from './poam.js'

describe('closeout deadline', () => {
  it('is 180 days after the start date while the assessment is in progress', () => {
    assert.equal(closeoutDeadline({ started_at: '2026-10-12T13:00:00Z', completed_at: null }), '2027-04-10')
  })
  it('runs from the completion date once the assessment is complete', () => {
    assert.equal(closeoutDeadline({ started_at: '2026-06-01T13:00:00Z', completed_at: '2026-06-19T16:00:00Z' }),
      '2026-12-16')
  })
  it('crosses a leap day correctly', () => {
    assert.equal(addDays('2027-12-31', 60), '2028-02-29')
  })
  it('is null without a date', () => {
    assert.equal(closeoutDeadline({}), null)
    assert.equal(closeoutDeadline(null), null)
  })
})

describe('due-date flags', () => {
  const deadline = '2027-04-10'
  const today = '2026-11-09'
  it('flags an open item whose due date has passed', () => {
    const f = dueFlags({ status: 'open', due_date: '2026-11-08' }, deadline, today)
    assert.equal(f.overdue, true)
    assert.equal(f.daysLeft, -1)
  })
  it('is not overdue on the due date itself', () => {
    assert.equal(dueFlags({ status: 'in_progress', due_date: today }, deadline, today).overdue, false)
  })
  it('never flags a closed item', () => {
    const f = dueFlags({ status: 'closed', due_date: '2020-01-01' }, deadline, today)
    assert.deepEqual(f, { overdue: false, beyondCloseout: false, noDueDate: false, daysLeft: null })
  })
  it('flags a due date after the 180-day closeout deadline, not on it', () => {
    assert.equal(dueFlags({ status: 'open', due_date: '2027-04-11' }, deadline, today).beyondCloseout, true)
    assert.equal(dueFlags({ status: 'open', due_date: '2027-04-10' }, deadline, today).beyondCloseout, false)
  })
  it('flags a missing due date', () => {
    assert.equal(dueFlags({ status: 'open', due_date: null }, deadline, today).noDueDate, true)
  })
  it('summarises a list', () => {
    const items = [
      { status: 'open', due_date: '2026-10-01' },
      { status: 'in_progress', due_date: '2027-05-01' },
      { status: 'closed', due_date: '2026-10-01' },
      { status: 'open', due_date: '2027-01-01' },
    ]
    assert.deepEqual(poamSummary(items, deadline, today),
      { total: 4, open: 2, in_progress: 1, closed: 1, overdue: 1, beyondCloseout: 1 })
  })
})

describe('dates', () => {
  it('accepts only real calendar dates', () => {
    assert.equal(isIsoDate('2027-02-28'), true)
    assert.equal(isIsoDate('2027-02-29'), false)
    assert.equal(isIsoDate('2027-2-1'), false)
    assert.equal(isIsoDate(''), false)
  })
  it('counts days and gives today in UTC', () => {
    assert.equal(daysBetween('2026-11-09', '2026-12-09'), 30)
    assert.equal(todayIso(new Date('2026-11-09T23:30:00-05:00')), '2026-11-10')
  })
})

describe('gaps without an item', () => {
  it('splits drafts into allowed and not allowed, skipping requirements that have an item', () => {
    const drafts = [
      { req_id: '3.13.12', allowed: true },
      { req_id: '3.5.3', allowed: false, reason: 'weighted 5' },
      { req_id: '3.8.4', allowed: true },
      { req_id: '3.1.3', allowed: true },
    ]
    const { eligible, notAllowed } = openGaps(drafts, [{ req_id: '3.1.3' }])
    assert.deepEqual(eligible.map((d) => d.req_id), ['3.8.4', '3.13.12'])
    assert.deepEqual(notAllowed.map((d) => d.req_id), ['3.5.3'])
  })
  it('sorts requirement IDs numerically', () => {
    assert.deepEqual(['3.13.1', '3.1.21', '3.1.3', '3.10.6'].sort(compareReqIds), ['3.1.3', '3.1.21', '3.10.6', '3.13.1'])
  })
})

describe('editor form', () => {
  const form = {
    weakness: ' Missing lockout ', remediation: '', owner: ' Dana ', due_date: '', status: 'open',
    milestones: [{ description: ' Apply policy ', due: '2026-12-01', done: true }],
  }
  it('builds the request body with trimmed text and a null due date', () => {
    assert.deepEqual(poamBody(form), {
      weakness: 'Missing lockout', remediation: '', owner: 'Dana', due_date: null, status: 'open',
      milestones: [{ description: 'Apply policy', due: '2026-12-01', done: true }],
    })
  })
  it('requires a weakness, valid dates and described milestones', () => {
    assert.equal(validatePoamForm(form), null)
    assert.match(validatePoamForm({ ...form, weakness: '  ' }), /weakness/)
    assert.match(validatePoamForm({ ...form, due_date: '2026-13-01' }), /due date/)
    assert.match(validatePoamForm({ ...form, milestones: [{ description: '' }] }), /Milestone 1/)
    assert.match(validatePoamForm({ ...form, status: 'done' }), /status/)
  })
  it('counts milestones done', () => {
    assert.deepEqual(milestoneProgress([{ done: true }, { done: false }]), { done: 1, total: 2 })
    assert.deepEqual(milestoneProgress(), { done: 0, total: 0 })
  })
})
