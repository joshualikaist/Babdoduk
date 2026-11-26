export const meta = {
  name: 'babdoduk-panel',
  description: 'Virtual review panel: designer x2, developer x2, copy, founder review the lab capture; critic debates and ranks',
  phases: [
    { title: 'Review', detail: 'each reviewer reads the shared capture and reports findings' },
    { title: 'Critic', detail: 'critic checks evidence, merges duplicates, asks questions' },
    { title: 'Discuss', detail: 'reviewers comment on each other\'s strongest findings' },
    { title: 'Reply', detail: 'reviewers answer the critic' },
    { title: 'Verdict', detail: 'critic gives final verdicts and the top 10' },
  ],
}

// Owner 2026-11-26 ("소넷으로 돌려야지"): every panel agent runs on Sonnet, never the session's default model.
const MODEL = 'sonnet'
const REPO = args.repo
const CAP = args.capture
const CARD = id => `${REPO}/.claude/agents/panel-${id}.md`

const FINDINGS = {
  type: 'object',
  properties: {
    summary: { type: 'string', description: '이 평가자의 한두 문장 총평 (쉬운 한국어)' },
    findings: {
      type: 'array', maxItems: 12,
      items: {
        type: 'object',
        properties: {
          title: { type: 'string', description: '한 줄 제목' },
          page: { type: 'string', description: '예: index.html, 또는 전체' },
          device: { type: 'string', enum: ['iphone', 'android', 'desktop', 'all'] },
          evidence: { type: 'string', description: '사진 파일 이름과 위치, 또는 파일:줄, 또는 facts.json 항목' },
          shot: { type: 'string', description: '대표 사진 파일 이름 (예: index-iphone.jpg), 없으면 빈 문자열' },
          standard: { type: 'string', description: '근거 기준 (예: 닐슨 4번 일관성)' },
          severity: { type: 'integer', minimum: 0, maximum: 4 },
          detail: { type: 'string', description: '무엇이 왜 문제인지 2~4문장' },
          fix: { type: 'string', description: '구체적인 고칠 방법' },
          ask: { type: 'string', description: '창업가만: 진짜 학생에게 물을 질문. 다른 평가자는 빈 문자열' },
        },
        required: ['title', 'page', 'device', 'evidence', 'shot', 'standard', 'severity', 'detail', 'fix', 'ask'],
      },
    },
  },
  required: ['summary', 'findings'],
}

const REVIEWERS = [
  { id: 'designer', run: 1, focus: '먼저 아이폰 화면 전체를 본 뒤 안드로이드와 컴퓨터를 비교하라. 홈, 오늘의 꽁밥, 메뉴 뽑기를 가장 꼼꼼히.' },
  { id: 'designer', run: 2, focus: '이번에는 안드로이드 화면부터 보고, 매거진, 소식, 역사, 제보, 마이 밥도둑을 가장 꼼꼼히. 페이지 사이의 일관성을 특히 보라.' },
  { id: 'developer', run: 1, focus: 'facts.json 측정값과 홈, 오늘의 꽁밥, 메뉴 뽑기의 코드(js/home*.js, js/ggongbab*.js, js/pick.js, css)를 중심으로.' },
  { id: 'developer', run: 2, focus: '월드컵, 매거진, 제보, 마이 밥도둑의 코드(js/worldcup*.js, js/my.js, js/babdoduk-account.js, js/ggongbab-tips.js, api/, sw.js)와 유지보수(큰 파일, 복사된 코드)를 중심으로.' },
  { id: 'copy', run: 1, focus: '모든 페이지의 아이폰 화면 글과 i18n/ko.json.' },
  { id: 'founder', run: 1, focus: '처음 온 학생이 홈에서 3초 안에 무엇을 얻는지, 다시 올 이유, 친구에게 알릴 이유.' },
]

phase('Review')
const reviews = await parallel(REVIEWERS.map(r => () => agent(
  `너의 역할 설명서: ${CARD(r.id)} — 먼저 이 파일을 읽고 그대로 따른다.\n` +
  `저장소: ${REPO} (읽기만). 촬영 폴더: ${CAP} (shots/ 사진 30장과 facts.json; 실험 사이트를 아이폰 390, 안드로이드 412, 컴퓨터 1440 너비로 한국어로 찍은 것).\n` +
  `이번 평가의 초점: ${r.focus}\n` +
  `지적은 많아야 12개, 심각도 높은 순으로. 증거가 없는 지적은 넣지 않는다. 모든 글은 쉬운 한국어.`,
  { label: `review:${r.id}${r.run}`, phase: 'Review', model: MODEL, schema: FINDINGS })
  .then(out => out && { ...r, ...out })))

const all = []
reviews.filter(Boolean).forEach(r => r.findings.forEach((f, i) => all.push({ ...f, fid: `${r.id}${r.run}-${i + 1}`, from: r.id })))
log(`${all.length} findings from ${reviews.filter(Boolean).length} reviews`)

const CRITIC = {
  type: 'object',
  properties: {
    groups: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          gid: { type: 'string', description: 'g1, g2, ...' },
          title: { type: 'string' },
          fids: { type: 'array', items: { type: 'string' } },
          verdict: { type: 'string', enum: ['accept', 'question', 'reject'] },
          severity: { type: 'integer', minimum: 0, maximum: 4 },
          note: { type: 'string', description: '비판자가 평가자에게 하는 말: 인정 이유, 질문, 기각 이유 (1~3문장)' },
        },
        required: ['gid', 'title', 'fids', 'verdict', 'severity', 'note'],
      },
    },
  },
  required: ['groups'],
}

phase('Critic')
const critic = await agent(
  `너의 역할 설명서: ${CARD('critic')} — 먼저 읽고 따른다.\n저장소: ${REPO}. 촬영 폴더: ${CAP}.\n` +
  `아래는 평가자들의 지적 ${all.length}개다(JSON). 같은 문제는 한 묶음으로 합치고(fids에 모두), 묶음마다 증거를 직접 확인해 판정하라. ` +
  `같은 평가자의 두 번 평가(예: designer1, designer2)에서 모두 나온 문제는 신뢰도가 높다. 모든 지적은 정확히 한 묶음에 들어가야 한다.\n\n` +
  JSON.stringify(all.map(f => ({ fid: f.fid, from: f.from, title: f.title, page: f.page, device: f.device, evidence: f.evidence, standard: f.standard, severity: f.severity, detail: f.detail, fix: f.fix })), null, 1),
  { label: 'critic:merge', phase: 'Critic', model: MODEL, schema: CRITIC })

const groups = critic ? critic.groups : []
const byFid = Object.fromEntries(all.map(f => [f.fid, f]))
const questioned = groups.filter(g => g.verdict === 'question')

const REPLY = {
  type: 'object',
  properties: {
    replies: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          gid: { type: 'string' },
          keep: { type: 'boolean', description: '지적을 유지하면 true, 거두면 false' },
          severity: { type: 'integer', minimum: 0, maximum: 4 },
          text: { type: 'string', description: '비판자에게 하는 답 (근거를 보태거나 거두는 이유, 1~3문장)' },
        },
        required: ['gid', 'keep', 'severity', 'text'],
      },
    },
  },
  required: ['replies'],
}


const DISCUSS = {
  type: 'object',
  properties: {
    comments: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          gid: { type: 'string' },
          stance: { type: 'string', enum: ['agree', 'disagree', 'add'] },
          effort: { type: 'string', enum: ['small', 'medium', 'large', 'unknown'], description: '고치는 품 (개발자는 꼭 판단, 다른 평가자는 모르면 unknown)' },
          text: { type: 'string', description: '네 관점에서 한두 문장. 반대라면 이유를 증거와 함께. 같은 말 반복 금지' },
        },
        required: ['gid', 'stance', 'effort', 'text'],
      },
    },
  },
  required: ['comments'],
}

const fromOf = g => [...new Set(g.fids.map(id => (byFid[id] || {}).from).filter(Boolean))]
const candidates = groups.filter(g => g.verdict !== 'reject')
  .map(g => ({ g, score: g.severity * fromOf(g).length + (fromOf(g).some(w => w === 'designer' || w === 'developer') ? 1 : 0) }))
  .sort((a, b) => b.score - a.score).slice(0, 16).map(x => x.g)
const LENS = {
  designer: '이 지적을 고치면 화면이 더 나빠지거나 다른 곳과 어긋나지 않는지, 디자인 관점에서 동의하는지.',
  developer: '고치는 품(작음/중간/큼)과 위험, 고칠 파일. 지적의 기술적 사실이 틀렸으면 반대하라.',
  copy: '문구로 풀 수 있는 문제인지, 고칠 방법의 문장이 사용자에게 맞는지.',
  founder: '학생이 떠나거나 다시 오는 데 얼마나 영향이 있는지. 먼저 할 일인지 나중 일인지.',
}
phase('Discuss')
const discussion = await parallel(Object.keys(LENS).map(who => () => {
  const mine = candidates.filter(g => !fromOf(g).includes(who))
  if (!mine.length) return Promise.resolve([])
  return agent(
    `너의 역할 설명서: ${CARD(who)} — 먼저 읽고 따른다.\n저장소: ${REPO}. 촬영 폴더: ${CAP}.\n` +
    `다른 평가자들이 낸 지적이다. 네 관점에서 하나씩 의견을 달아라: ${LENS[who]}\n` +
    `무조건 동의하지 마라. 증거를 직접 확인하고, 동의할 이유가 약하면 반대하거나 보태라. 묶음마다 의견 하나.\n\n` +
    JSON.stringify(mine.map(g => ({ gid: g.gid, title: g.title, severity: g.severity, critic: g.note,
      findings: g.fids.map(id => byFid[id]).filter(Boolean).map(f => ({ from: f.from, detail: f.detail, evidence: f.evidence, fix: f.fix })) })), null, 1),
    { label: `discuss:${who}`, phase: 'Discuss', model: MODEL, schema: DISCUSS })
    .then(out => out ? out.comments.map(c => ({ ...c, from: who })) : [])
}))
const comments = discussion.flat().filter(Boolean)
log(`${comments.length} comments on ${candidates.length} findings`)

phase('Reply')
const owners = {}
questioned.forEach(g => {
  const who = (g.fids.map(id => byFid[id]).find(Boolean) || {}).from
  if (who) (owners[who] = owners[who] || []).push(g)
})
const replyLists = await parallel(Object.entries(owners).map(([who, gs]) => () => agent(
  `너의 역할 설명서: ${CARD(who)} — 먼저 읽고 따른다.\n저장소: ${REPO}. 촬영 폴더: ${CAP}.\n` +
  `비판자가 너의 지적에 질문했다. 증거를 다시 확인하고 묶음마다 답하라.\n\n` +
  JSON.stringify(gs.map(g => ({ gid: g.gid, title: g.title, question: g.note, yours: g.fids.map(id => byFid[id]).filter(f => f && f.from === who).map(f => ({ title: f.title, evidence: f.evidence, detail: f.detail })) })), null, 1),
  { label: `reply:${who}`, phase: 'Reply', model: MODEL, schema: REPLY })
  .then(out => out ? out.replies.map(r => ({ ...r, from: who })) : [])))
const replies = replyLists.flat().filter(Boolean)

const FINAL = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          gid: { type: 'string' },
          verdict: { type: 'string', enum: ['accept', 'reject'] },
          severity: { type: 'integer', minimum: 0, maximum: 4 },
          note: { type: 'string', description: '최종 판정 이유 1~2문장' },
        },
        required: ['gid', 'verdict', 'severity', 'note'],
      },
    },
    top: { type: 'array', maxItems: 10, items: { type: 'string' }, description: '인정된 묶음 gid, 고칠 순서대로 최대 10개 (심각도 × 말한 평가자 수, 디자이너와 개발자 지적에 가중)' },
    overall: { type: 'string', description: '평가단 전체 총평 2~3문장, 쉬운 한국어' },
  },
  required: ['verdicts', 'top', 'overall'],
}

phase('Verdict')
const final = await agent(
  `너의 역할 설명서: ${CARD('critic')} — 먼저 읽고 따른다.\n저장소: ${REPO}. 촬영 폴더: ${CAP}.\n` +
  `질문했던 묶음의 답변과 다른 평가자들의 의견이 모였다. 의견이 달린 묶음과 질문했던 묶음마다 최종 판정(인정 또는 기각)과 그 이유를 의견에 답하듯 쓰고, 인정된 모든 묶음 중 고칠 순서 상위 10개를 골라라.\n\n` +
  `묶음:\n${JSON.stringify(groups.map(g => ({ gid: g.gid, title: g.title, verdict: g.verdict, severity: g.severity, note: g.note, from: [...new Set(g.fids.map(id => (byFid[id] || {}).from).filter(Boolean))] })), null, 1)}\n\n` +
  `답변:\n${JSON.stringify(replies, null, 1)}\n\n다른 평가자들의 의견(동의/반대/보탬, 고치는 품):\n${JSON.stringify(comments, null, 1)}\n\n반대 의견이 증거로 맞으면 판정이나 심각도를 바꿔라. 순위는 영향(심각도 × 평가자 수)과 고치는 품을 함께 보라: 영향이 크고 품이 작은 것을 먼저.`,
  { label: 'critic:final', phase: 'Verdict', model: MODEL, schema: FINAL })

return { reviews: reviews.filter(Boolean), all, groups, replies, comments, final }
