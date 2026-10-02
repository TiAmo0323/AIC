import assert from 'node:assert/strict'
import {filterIssues, timelineSegments} from '../project/src/utils/motionlintView.js'
const issues = [
  {test_name:'foot_sliding',severity:'high',start_frame:3,end_frame:6},
  {test_name:'foot_sliding',severity:'high',start_frame:1,end_frame:4},
  {test_name:'foot_sliding',severity:'medium',start_frame:2,end_frame:3},
  {test_name:'collision',severity:'high',start_frame:3,end_frame:4},
  {test_name:'foot_sliding',severity:'high',start_frame:9,end_frame:10}
]
const original = JSON.stringify(issues)
const segments = timelineSegments(issues)
assert.equal(segments.length, 4)
assert.equal(segments[0].start_frame, 1)
assert.equal(segments[0].end_frame, 6)
assert.equal(segments[0].count, 2)
assert.equal(segments[0].issue.start_frame, 1)
assert.equal(filterIssues(issues, 'foot_sliding', 'high').length, 3)
assert.equal(JSON.stringify(issues), original)
const actors = timelineSegments([
  {test_name:'collision',severity:'high',actor_id:0,start_frame:1,end_frame:4},
  {test_name:'collision',severity:'high',actor_id:1,start_frame:1,end_frame:4}
])
assert.equal(actors.length,2,'Different actors must keep separate clickable intervals')
console.log('Timeline merging, filtering, exact seek frame and input immutability: PASS')
