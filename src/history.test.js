// Run with `npm test` (Node's built-in test runner; no extra dependencies).
import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { changeRows, chartPoints, scoreRange, scoreTicks, signed } from './history.js'

describe('score chart', () => {
  it('runs from 0 to 110 when no score is negative', () => {
    assert.deepEqual(scoreRange([41, 86]), { min: 0, max: 110 })
    assert.deepEqual(scoreTicks({ min: 0, max: 110 }), [110, 0])
  })
  it('drops to a round number below a negative score', () => {
    assert.deepEqual(scoreRange([-37, 20]), { min: -50, max: 110 })
    assert.deepEqual(scoreRange([-203]), { min: -225, max: 110 })
    assert.deepEqual(scoreTicks({ min: -50, max: 110 }), [110, 0, -50])
  })
  it('places points left to right and higher scores higher', () => {
    const box = { left: 0, right: 100, top: 0, bottom: 110 }
    const { points, y } = chartPoints([{ id: 1, score: 41 }, { id: 2, score: 86 }, { id: 3, score: 110 }], box)
    assert.deepEqual(points.map((p) => p.x), [0, 50, 100])
    assert.equal(points[2].y, 0)
    assert.ok(points[1].y < points[0].y)
    assert.equal(y(0), 110)
  })
  it('centres a single assessment', () => {
    const { points } = chartPoints([{ id: 1, score: 50 }], { left: 10, right: 90, top: 0, bottom: 100 })
    assert.equal(points[0].x, 50)
  })
})

describe('changes between assessments', () => {
  it('adds titles, the score change and a total', () => {
    const rows = changeRows({
      assessments: [{ id: 1, title: 'June', score: 41 }, { id: 2, title: 'Autumn', score: 86 }],
      changes: [{ from_id: 1, to_id: 2, became_met: ['3.2.1', '3.3.1'], regressed: ['3.1.1'], became_na: [], no_longer_na: [] }],
    })
    assert.equal(rows[0].from.title, 'June')
    assert.equal(rows[0].to.title, 'Autumn')
    assert.equal(rows[0].delta, 45)
    assert.equal(rows[0].total, 3)
  })
  it('writes signed numbers with a real minus sign', () => {
    assert.equal(signed(45), '+45')
    assert.equal(signed(-3), '−3')
    assert.equal(signed(0), '0')
  })
})
