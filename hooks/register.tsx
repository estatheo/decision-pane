import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { Decision, DecisionOption, WorkItem, WorkStatus } from '../types'

const PANE = 'decisions'
const STORE_KEY = 'decisions'
const WORK_STORE_KEY = 'work'

// The store is shared by every session on this machine, so each project keeps
// its own lists, keyed by the session's folder. Agent sessions that run inside a
// `.gc/` folder (Gas City) share the lists of the folder above it.
let scope: Promise<string> | undefined
function project($: any): Promise<string> {
  scope ??= (async () => {
    const cwd = String(await $.session.cwd().catch(() => ''))
    const i = cwd.indexOf('/.gc/')
    return i >= 0 ? cwd.slice(0, i) : cwd
  })()
  return scope
}
async function storeKey($: any, base: string): Promise<string> {
  return `${base}@${await project($)}`
}
const KEEP_ANSWERED = 40

// ---------------------------------------------------------------------------
// Beads store (store = "beads"): decisions and work items live in the Gas City
// city's beads, so agents on any model post with `gc decisions ask` and answers
// go back to them by gc mail. The atoms below stay the panel's copy, refreshed
// from beads every few seconds and after every write.
// ---------------------------------------------------------------------------
let useBeads = false
let gcPath = ''
let gcBin: string | undefined
// Decisions the person pushed back with "Later", shown after the others.
const later: string[] = []

async function gc($: any, args: string[]): Promise<{ ok: boolean; out: string; err: string }> {
  const tries = gcBin ? [gcBin] : [gcPath || 'gc', `${(await $.env.get('HOME').catch(() => '')) || ''}/.local/bin/gc`]
  let last = { ok: false, out: '', err: 'gc not found' }
  for (const bin of tries) {
    try {
      const r = await $.process.run([bin, ...args], { timeoutMs: 20000 })
      last = { ok: r.exitCode === 0, out: String(r.stdout ?? ''), err: String(r.stderr ?? '') }
      gcBin = bin
      return last
    } catch (err) {
      last = { ok: false, out: '', err: String(err) }
    }
  }
  return last
}

async function bd($: any, args: string[]): Promise<string> {
  const r = await gc($, ['bd', ...args])
  if (!r.ok) throw new Error(`gc bd ${args[0]}: ${r.err.trim().split('\n').pop() ?? 'failed'}`)
  return r.out
}

async function bdList($: any, args: string[]): Promise<any[]> {
  const out = await bd($, ['list', '--json', '--limit', '0', ...args])
  const i = out.indexOf('[')
  if (i < 0) return []
  try {
    return JSON.parse(out.slice(i))
  } catch {
    return []
  }
}

function dayOffset(days: number): string {
  return new Date(Date.now() + days * 86400000).toISOString().slice(0, 10)
}

function beadToDecision(b: any): Decision | undefined {
  const m = b.metadata ?? {}
  if (m.withdrawn) return undefined
  if (b.status === 'closed' && m.pick === undefined) return undefined
  return {
    id: b.id,
    question: String(b.title ?? ''),
    context: b.description ? String(b.description) : undefined,
    from: m.from || b.created_by || undefined,
    options: Array.isArray(m.options) ? m.options : [],
    recommended: Number.isInteger(m.recommended) ? m.recommended : undefined,
    postedAt: String(b.created_at ?? ''),
    pick: Number.isInteger(m.pick) ? m.pick : undefined,
    answer: m.answer,
    answeredAt: m.answered_at,
    isDelivered: !!m.delivered,
    replyTo: m.reply_to || b.created_by || undefined,
    viaPanel: !!m.via_panel,
  }
}

function beadToWork(b: any): WorkItem | undefined {
  const m = b.metadata ?? {}
  if (m.removed) return undefined
  return {
    key: String(m.key ?? b.id),
    bead: b.id,
    title: String(b.title ?? ''),
    status: STATUSES.includes(m.status) ? m.status : b.status === 'closed' ? 'done' : 'todo',
    note: m.note,
    who: m.who,
    link: m.link,
    group: m.group,
    order: typeof m.order === 'number' ? m.order : undefined,
    due: m.due,
    day: String(m.day ?? String(b.created_at ?? '').slice(0, 10)),
    updatedAt: String(b.updated_at ?? ''),
  }
}

// Refreshes run one after another, so one asked for after a write always reads it.
let refreshing: Promise<void> = Promise.resolve()
async function refresh($: any): Promise<void> {
  if (!useBeads) return
  refreshing = refreshing.then(async () => {
    try {
      const open = await bdList($, ['--label-any', 'decision,work'])
      const recent = await bdList($, ['--label-any', 'decision,work', '--all', '--updated-after', dayOffset(-1)])
      const byId = new Map<string, any>()
      for (const b of [...open, ...recent]) byId.set(b.id, b)
      const all = [...byId.values()].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
      const has = (b: any, l: string) => Array.isArray(b.labels) && b.labels.includes(l)
      let ds = all.filter(b => has(b, 'decision')).map(beadToDecision).filter(Boolean) as Decision[]
      ds = [...ds.filter(d => !later.includes(d.id)), ...later.map(id => ds.find(d => d.id === id)).filter(Boolean) as Decision[]]
      const ws = all.filter(b => has(b, 'work')).map(beadToWork).filter(Boolean) as WorkItem[]
      await update($, decisions, () => trimAnswered(ds))
      await update($, work, () => ws)
      const n = ds.filter(isOpen).length
      $.ui.status(n ? `${n} decision${n === 1 ? '' : 's'} waiting · /decisions` : undefined)
    } catch (err) {
      $.ui.status(`decisions: can't read beads (${String((err as any)?.message ?? err).slice(0, 80)})`)
    }
  })
  return refreshing
}

async function beadsPost($: any, d: Omit<Decision, 'id' | 'postedAt'>): Promise<string> {
  const meta = { kind: 'decision', options: d.options, recommended: d.recommended, from: d.from, via_panel: true }
  const out = await bd($, [
    'create', d.question, '--labels', 'decision', '--description', d.context ?? '', '--allow-empty-description',
    '--metadata', JSON.stringify(meta), '--silent',
  ])
  return out.trim().split('\n').pop() ?? '?'
}

async function beadsWork($: any, r: any, now: WorkItem | undefined): Promise<'ok' | 'missing'> {
  const status = STATUSES.includes(r?.status) ? (r.status as WorkStatus) : undefined
  const fields: Record<string, unknown> = {}
  for (const k of ['note', 'who', 'link', 'group', 'due']) if (r?.[k] !== undefined) fields[k] = String(r[k])
  if (typeof r?.order === 'number') fields.order = r.order
  if (status) fields.status = status
  let id = now?.bead
  if (id) {
    const args = ['update', id, '--metadata', JSON.stringify(fields)]
    if (r?.title) args.push('--title', String(r.title))
    await bd($, args)
  } else {
    if (!r?.title) return 'missing'
    const meta = { kind: 'work', key: String(r.key), status: status ?? 'todo', day: today(), ...fields }
    const out = await bd($, ['create', String(r.title), '--labels', 'work', '--allow-empty-description', '--metadata', JSON.stringify(meta), '--silent'])
    id = out.trim().split('\n').pop()
  }
  if (id && status && (status === 'done' || status === 'dropped')) await bd($, ['close', id, '--reason', status])
  return 'ok'
}

// Bump the tag when Decision's fields change: it declines what an older
// version stored, which outlives a reload.
const decisions = atom({ plugin: 'decisions', key: 'list' } as const, [], {
  shape: 'decisions-1',
})
const work = atom({ plugin: 'decisions', key: 'work' } as const, [], {
  shape: 'work-1',
})
// Whether the Done group is open. Closed by default.
const showDone = atom({ plugin: 'decisions', key: 'showDone' } as const, false)
// Groups the person folded to their header line.
const folded = atom({ plugin: 'decisions', key: 'folded' } as const, [] as string[])
// Groups the person opened past their first few items.
const expanded = atom({ plugin: 'decisions', key: 'expanded' } as const, [] as string[])
// Statuses whose note is worth a second line; the rest stay one line each.
const NOTE_STATUSES: WorkStatus[] = ['running', 'review', 'blocked']
// Open items a group shows before "n more", so the pane fits its window
// without scrolling (a focused button low in the pane pins the window down).
const GROUP_ROWS = 5

const DEFAULT_GROUP = 'Today'

function isFinished(w: WorkItem): boolean {
  return w.status === 'done' || w.status === 'dropped'
}

/** Done of counted (dropped items don't count), and the whole percentage. */
function progress(items: WorkItem[]): { done: number; total: number; pct: number } {
  const counted = items.filter(w => w.status !== 'dropped')
  const done = counted.filter(w => w.status === 'done').length
  const total = counted.length
  return { done, total, pct: total ? Math.round((done / total) * 100) : 0 }
}

/** Groups in the order they first appear in the list, each with its items. */
function groupWork(items: WorkItem[]): { name: string; items: WorkItem[] }[] {
  const out: { name: string; items: WorkItem[] }[] = []
  for (const w of items) {
    const name = w.group?.trim() || DEFAULT_GROUP
    let g = out.find(x => x.name === name)
    if (!g) out.push((g = { name, items: [] }))
    g.items.push(w)
  }
  for (const g of out) {
    g.items.sort((a, b) => {
      const oa = a.order ?? Number.MAX_SAFE_INTEGER
      const ob = b.order ?? Number.MAX_SAFE_INTEGER
      return oa !== ob ? oa - ob : ORDER[a.status] - ORDER[b.status]
    })
  }
  return out
}

const POST_TOOL = 'mcp__decisions__post'
const LIST_TOOL = 'mcp__decisions__list'
const WITHDRAW_TOOL = 'mcp__decisions__withdraw'
const WORK_UPDATE_TOOL = 'mcp__decisions__work_update'
const WORK_LIST_TOOL = 'mcp__decisions__work_list'
const WORK_REMOVE_TOOL = 'mcp__decisions__work_remove'
// The Atlassian MCP server's transition tool, under the names it gets when added
// as a local server or as the claude.ai connector.
const JIRA_TRANSITION_TOOL = /^mcp__(atlassian|claude_ai_Atlassian_MCP)__transitionJiraIssue$/

const STATUSES: WorkStatus[] = ['todo', 'running', 'waiting', 'review', 'blocked', 'done', 'dropped']
const ORDER: Record<WorkStatus, number> = { running: 0, review: 1, waiting: 2, blocked: 3, todo: 4, done: 5, dropped: 6 }
const LABEL: Record<WorkStatus, string> = {
  running: 'working',
  review: 'to merge',
  waiting: 'waiting',
  blocked: 'blocked',
  todo: 'to do',
  done: 'done',
  dropped: 'dropped',
}

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

function statusFromJira(name: string): WorkStatus | undefined {
  const n = name.toLowerCase()
  if (n === 'done' || n === 'closed' || n === "won't do" || n === 'resolved') return 'done'
  if (n.includes('review')) return 'review'
  if (n.includes('progress')) return 'running'
  if (n === 'to do' || n === 'backlog' || n === 'open') return 'todo'
  if (n.includes('block')) return 'blocked'
  return undefined
}

/** Today's items, plus anything still open from an earlier day. */
function visibleWork(list: WorkItem[]): WorkItem[] {
  const d = today()
  return list.filter(w => w.day === d || (w.status !== 'done' && w.status !== 'dropped'))
}

async function saveWork($: any, list: WorkItem[]): Promise<void> {
  if (useBeads) return
  try {
    await $.store.set(await storeKey($, WORK_STORE_KEY), list)
  } catch {
    // Kept for this session.
  }
}

async function changeWork($: any, fn: (list: WorkItem[]) => WorkItem[]): Promise<WorkItem[]> {
  let after: WorkItem[] = []
  await update($, work, list => {
    const d = today()
    // Drop finished items from earlier days; keep 200 at most.
    after = fn(list ?? [])
      .filter(w => w.day === d || (w.status !== 'done' && w.status !== 'dropped'))
      .slice(-200)
    return after
  })
  await saveWork($, after)
  return after
}

function summariseWork(list: WorkItem[]): string {
  const v = visibleWork(list)
  if (!v.length) return 'The work list is empty.'
  const all = progress(v)
  const lines = [`Work: ${all.done} of ${all.total} done (${all.pct}%).`]
  for (const g of groupWork(v)) {
    const p = progress(g.items)
    lines.push(`## ${g.name}: ${p.done} of ${p.total} done (${p.pct}%)`)
    for (const w of g.items) {
      const pos = w.order !== undefined ? `${w.order}. ` : ''
      const due = w.due ? ` [due ${w.due}]` : ''
      lines.push(`- ${pos}${w.key} [${w.status}] ${w.title}${due}${w.note ? ` (${w.note})` : ''}`)
    }
  }
  return lines.join('\n')
}

function isOpen(d: Decision): boolean {
  return d.pick === undefined
}

function trimAnswered(list: Decision[]): Decision[] {
  const open = list.filter(isOpen)
  const answered = list.filter(d => !isOpen(d)).slice(-KEEP_ANSWERED)
  return [...open, ...answered]
}

function nextId(list: Decision[]): string {
  const max = list.reduce((m, d) => {
    const n = Number(d.id.replace(/^D/, ''))
    return Number.isFinite(n) && n > m ? n : m
  }, 0)
  return `D${max + 1}`
}

function answerText(d: Decision): string {
  if (d.pick === -1) return `in their own words: "${d.answer ?? ''}"`
  if (d.pick === -2) return 'that they want to discuss it before deciding'
  const opt = d.options[d.pick ?? 0]
  return `option ${(d.pick ?? 0) + 1}: "${opt?.label ?? '?'}"`
}

function deliveryText(d: Decision): string {
  const lines = [
    `DECISION ${d.id}: the user answered ${answerText(d)}.`,
    `Question: ${d.question}`,
  ]
  if (d.from) lines.push(`Raised by: ${d.from}`)
  lines.push(
    d.pick === -2
      ? 'Ask them about it in chat (or by gc mail); do not act on it yet.'
      : 'Act on it now. Do not ask them again.',
  )
  return lines.join('\n')
}

function summarise(list: Decision[]): string {
  const open = list.filter(isOpen)
  const answered = list.filter(d => !isOpen(d)).slice(-10)
  const out: string[] = []
  out.push(open.length ? `Waiting on the user (${open.length}):` : 'Nothing waiting on the user.')
  for (const d of open) out.push(`- ${d.id}: ${d.question}`)
  if (answered.length) {
    out.push('', 'Recently answered:')
    for (const d of answered) out.push(`- ${d.id}: ${d.question} -> ${answerText(d)}`)
  }
  return out.join('\n')
}

async function save($: any, list: Decision[]): Promise<void> {
  if (useBeads) return
  try {
    await $.store.set(await storeKey($, STORE_KEY), list)
  } catch {
    // The panel still works for this session.
  }
  const n = list.filter(isOpen).length
  $.ui.status(n ? `${n} decision${n === 1 ? '' : 's'} waiting · /decisions` : undefined)
}

async function change($: any, fn: (list: Decision[]) => Decision[]): Promise<Decision[]> {
  let after: Decision[] = []
  await update($, decisions, list => {
    after = trimAnswered(fn(list ?? []))
    return after
  })
  await save($, after)
  return after
}

async function answer($: any, id: string, pick: number, text?: string): Promise<void> {
  let picked: Decision | undefined
  await change($, list =>
    list.map(d => {
      if (d.id !== id || !isOpen(d)) return d
      picked = { ...d, pick, answer: text, answeredAt: new Date().toISOString() }
      return picked
    }),
  )
  if (!picked) return
  const d = picked
  if (useBeads) {
    try {
      const reason = d.pick === -1 ? 'answered in own words' : d.pick === -2 ? 'discuss first' : `answered: ${d.options[d.pick ?? 0]?.label ?? ''}`
      await bd($, ['update', d.id, '--metadata', JSON.stringify({ pick, answer: text, answered_at: d.answeredAt })])
      await bd($, ['close', d.id, '--reason', reason])
      if (!d.viaPanel && d.replyTo) {
        const subject = deliveryText(d).split('\n')[0]!
        const r = await gc($, ['mail', 'send', d.replyTo, '-s', subject, '-m', deliveryText(d), '--notify'])
        if (!r.ok) throw new Error(r.err)
      } else {
        await $.prompt.submit({ text: deliveryText(d) })
      }
      await bd($, ['update', d.id, '--metadata', JSON.stringify({ delivered: true })])
    } catch {
      $.ui.toast(`Couldn't send ${d.id}; the answer is saved on the bead.`)
    }
    await refresh($)
    return
  }
  try {
    await $.prompt.submit({ text: deliveryText(d) })
    await change($, list => list.map(x => (x.id === d.id ? { ...x, isDelivered: true } : x)))
  } catch {
    $.ui.toast(`Couldn't send ${d.id} to Claude; it's kept in the panel.`)
  }
}

function cleanOptions(raw: unknown): DecisionOption[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((o: any) =>
      typeof o === 'string'
        ? { label: o }
        : { label: String(o?.label ?? '').trim(), detail: o?.detail ? String(o.detail) : undefined },
    )
    .filter(o => o.label)
    .slice(0, 9)
}

export const register: Register = (on, options) => {
  useBeads = (options as any)?.store === 'beads'
  gcPath = String((options as any)?.gcPath ?? '')
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'decisions',
      description: 'Show the decisions waiting on you',
    })
    await $.tool.register({
      name: 'post',
      isDeferred: false,
      description:
        "Put one or more decisions in the user's Decisions panel instead of asking in chat. " +
        'Use it whenever you need the user to choose: a merge, a priority, an approach, whether to close or keep something. ' +
        'Each decision has a question, optional short context, 2-9 options (put your recommendation first and set recommended to its index), and who raised it. ' +
        'The user answers each one in the panel, one by one; each answer comes back to you as a new message starting "DECISION <id>:". ' +
        'Returns immediately with the ids. Keep working on other things meanwhile.',
      inputSchema: {
        type: 'object',
        properties: {
          decisions: {
            type: 'array',
            minItems: 1,
            items: {
              type: 'object',
              properties: {
                question: { type: 'string', description: 'One plain question, standing on its own.' },
                context: { type: 'string', description: 'What the user needs to know to choose, in 1-4 short lines.' },
                from: { type: 'string', description: 'Who raised it, e.g. "mayor", "reviewer agent".' },
                options: {
                  type: 'array',
                  minItems: 2,
                  maxItems: 9,
                  items: {
                    type: 'object',
                    properties: {
                      label: { type: 'string', description: 'The choice, a few words.' },
                      detail: { type: 'string', description: 'What happens if they pick it, one line.' },
                    },
                    required: ['label'],
                  },
                },
                recommended: { type: 'integer', description: 'Index (0-based) of the option you recommend.' },
              },
              required: ['question', 'options'],
            },
          },
        },
        required: ['decisions'],
      },
    })
    await $.tool.register({
      name: 'list',
      isDeferred: false,
      description: "List the decisions waiting in the user's Decisions panel and the ones answered recently.",
      inputSchema: { type: 'object', properties: {} },
    })
    await $.tool.register({
      name: 'withdraw',
      isDeferred: false,
      description: "Remove open decisions from the user's Decisions panel once they no longer need the user (overtaken, done another way).",
      inputSchema: {
        type: 'object',
        properties: { ids: { type: 'array', items: { type: 'string' } } },
        required: ['ids'],
      },
    })

    await $.tool.register({
      name: 'work_update',
      isDeferred: false,
      description:
        "Add or update items in the 'Work of the day' list in the user's panel. Upserts by key (a ticket key such as ABC-123 when there is one). " +
        'Call it whenever work starts, moves on, waits on someone, gets a PR, is ready to merge, finishes or is dropped, ' +
        'and right after any Jira create or transition you make for tracked work. Jira transitions of keys already on the list also update it by themselves. ' +
        'Statuses: todo, running, waiting, review (ready for the user to merge), blocked, done, dropped. Keep note to one short line on where it stands now. ' +
        'Put items from one source list in a named group (group: "Sprint 12"), with order for their position and due for the deadline; the panel shows each group with its own progress bar and percentage, and keeps finished items in a collapsed Done group.',
      inputSchema: {
        type: 'object',
        properties: {
          items: {
            type: 'array',
            minItems: 1,
            items: {
              type: 'object',
              properties: {
                key: { type: 'string', description: 'Ticket key (ABC-123) or a short id.' },
                title: { type: 'string', description: 'What the work is, a few words. Required when adding.' },
                status: { type: 'string', enum: STATUSES },
                note: { type: 'string', description: 'Where it stands now, one short line.' },
                who: { type: 'string', description: 'Who is on it.' },
                link: { type: 'string', description: 'PR or ticket URL.' },
                group: { type: 'string', description: 'The list it belongs to, e.g. "Sprint 12". Empty string moves it back to Today.' },
                order: { type: 'number', description: 'Position in its group, 1 first.' },
                due: { type: 'string', description: 'When it is due, short ("tonight", "Fri 13"). Empty string clears it.' },
              },
              required: ['key'],
            },
          },
        },
        required: ['items'],
      },
    })
    await $.tool.register({
      name: 'work_list',
      isDeferred: false,
      description: "Show the 'Work of the day' list from the user's panel.",
      inputSchema: { type: 'object', properties: {} },
    })
    await $.tool.register({
      name: 'work_remove',
      isDeferred: false,
      description: "Remove items from the 'Work of the day' list by key (added by mistake or no longer worth showing).",
      inputSchema: { type: 'object', properties: { keys: { type: 'array', items: { type: 'string' } } }, required: ['keys'] },
    })
    // Load this project's lists.
    const load = async (base: string) => await $.store.get(await storeKey($, base)).catch(() => undefined)
    if (useBeads) {
      await refresh($)
      $.clock.every(8000, () => refresh($))
    } else {
      const w = (await load(WORK_STORE_KEY)) as WorkItem[] | undefined
      await changeWork($, () => (Array.isArray(w) ? w : []))
      const stored = (await load(STORE_KEY)) as Decision[] | undefined
      await change($, () => (Array.isArray(stored) ? stored : []))
    }
    const now = (await read($, decisions)) ?? []
    if (now.some(isOpen)) void $.ui.open({ id: PANE, title: 'Decisions' })

    return next(e)
  })

  on('command.run', { command: 'decisions' }, async $ => {
    await $.ui.open({ id: PANE, title: 'Decisions', focus: true })
    const n = ((await read($, decisions)) ?? []).filter(isOpen).length
    return { text: n ? `${n} decision${n === 1 ? '' : 's'} waiting in the panel.` : 'Nothing is waiting on you.' }
  })

  on('tool.call', { tool: POST_TOOL }, async ($, e) => {
    const raw = (e as any).decisions
    if (!Array.isArray(raw) || raw.length === 0) return { deny: 'decisions must be a non-empty array.' }
    const ids: string[] = []
    if (useBeads) {
      for (const r of raw) {
        const options = cleanOptions(r?.options)
        const question = String(r?.question ?? '').trim()
        if (!question || options.length < 2) continue
        const rec = Number.isInteger(r?.recommended) && r.recommended >= 0 && r.recommended < options.length ? r.recommended : undefined
        try {
          ids.push(await beadsPost($, { question, options, recommended: rec, context: r?.context ? String(r.context) : undefined, from: r?.from ? String(r.from) : undefined }))
        } catch (err) {
          return { deny: `Couldn't write the decision to beads: ${String((err as any)?.message ?? err)}` }
        }
      }
      await refresh($)
    } else await change($, list => {
      const out = [...list]
      for (const r of raw) {
        const options = cleanOptions(r?.options)
        const question = String(r?.question ?? '').trim()
        if (!question || options.length < 2) continue
        const id = nextId(out)
        const rec = Number.isInteger(r?.recommended) && r.recommended >= 0 && r.recommended < options.length ? r.recommended : undefined
        out.push({
          id,
          question,
          context: r?.context ? String(r.context) : undefined,
          from: r?.from ? String(r.from) : undefined,
          options,
          recommended: rec,
          postedAt: new Date().toISOString(),
        })
        ids.push(id)
      }
      return out
    })
    if (ids.length === 0) return { deny: 'No decision had a question and at least two options.' }
    void $.ui.open({ id: PANE, title: 'Decisions' })
    $.ui.toast(`${ids.length} decision${ids.length === 1 ? '' : 's'} waiting · /decisions`)
    return {
      result: `Posted ${ids.join(', ')} to the user's Decisions panel. Each answer arrives as a message starting "DECISION <id>:". Carry on with other work.`,
    } as any
  })

  on('tool.call', { tool: LIST_TOOL }, async $ => {
    await refresh($)
    return { result: summarise((await read($, decisions)) ?? []) } as any
  })

  on('tool.call', { tool: WITHDRAW_TOOL }, async ($, e) => {
    const ids = new Set<string>(((e as any).ids ?? []).map(String))
    if (useBeads) {
      for (const id of ids) {
        await bd($, ['update', id, '--metadata', JSON.stringify({ withdrawn: true })]).catch(() => '')
        await bd($, ['close', id, '--reason', 'withdrawn']).catch(() => '')
      }
      await refresh($)
      return { result: `Withdrawn. ${summarise((await read($, decisions)) ?? [])}` } as any
    }
    const after = await change($, list => list.filter(d => !(isOpen(d) && ids.has(d.id))))
    return { result: `Withdrawn. ${summarise(after)}` } as any
  })

  on('tool.call', { tool: WORK_UPDATE_TOOL }, async ($, e) => {
    const raw = (e as any).items
    if (!Array.isArray(raw) || raw.length === 0) return { deny: 'items must be a non-empty array.' }
    const now = new Date().toISOString()
    const missing: string[] = []
    if (useBeads) {
      await refresh($)
      const list = (await read($, work)) ?? []
      try {
        for (const r of raw) {
          const key = String(r?.key ?? '').trim()
          if (!key) continue
          if ((await beadsWork($, { ...r, key }, list.find(w => w.key === key))) === 'missing') missing.push(key)
        }
      } catch (err) {
        return { deny: `Couldn't write to beads: ${String((err as any)?.message ?? err)}` }
      }
      await refresh($)
      const warn = missing.length ? `\nNot added (no title given for a new item): ${missing.join(', ')}` : ''
      return { result: summariseWork((await read($, work)) ?? []) + warn } as any
    }
    const after = await changeWork($, list => {
      const out = [...list]
      for (const r of raw) {
        const key = String(r?.key ?? '').trim()
        if (!key) continue
        const status = STATUSES.includes(r?.status) ? (r.status as WorkStatus) : undefined
        const i = out.findIndex(w => w.key === key)
        if (i >= 0) {
          const old = out[i]!
          out[i] = {
            ...old,
            title: r?.title ? String(r.title) : old.title,
            status: status ?? old.status,
            note: r?.note !== undefined ? String(r.note) : old.note,
            who: r?.who !== undefined ? String(r.who) : old.who,
            link: r?.link !== undefined ? String(r.link) : old.link,
            group: r?.group !== undefined ? String(r.group) || undefined : old.group,
            order: typeof r?.order === 'number' ? r.order : old.order,
            due: r?.due !== undefined ? String(r.due) || undefined : old.due,
            updatedAt: now,
          }
        } else if (r?.title) {
          out.push({
            key,
            title: String(r.title),
            status: status ?? 'todo',
            note: r?.note ? String(r.note) : undefined,
            who: r?.who ? String(r.who) : undefined,
            link: r?.link ? String(r.link) : undefined,
            group: r?.group ? String(r.group) : undefined,
            order: typeof r?.order === 'number' ? r.order : undefined,
            due: r?.due ? String(r.due) : undefined,
            day: today(),
            updatedAt: now,
          })
        } else missing.push(key)
      }
      return out
    })
    const warn = missing.length ? `\nNot added (no title given for a new item): ${missing.join(', ')}` : ''
    return { result: summariseWork(after) + warn } as any
  })

  on('tool.call', { tool: WORK_LIST_TOOL }, async $ => {
    await refresh($)
    return { result: summariseWork((await read($, work)) ?? []) } as any
  })

  on('tool.call', { tool: WORK_REMOVE_TOOL }, async ($, e) => {
    const keys = new Set(((e as any).keys ?? []).map(String))
    if (useBeads) {
      for (const w of ((await read($, work)) ?? []).filter(w => keys.has(w.key) && w.bead)) {
        await bd($, ['update', w.bead!, '--metadata', JSON.stringify({ removed: true })]).catch(() => '')
        await bd($, ['close', w.bead!, '--reason', 'removed']).catch(() => '')
      }
      await refresh($)
      return { result: summariseWork((await read($, work)) ?? []) } as any
    }
    const after = await changeWork($, list => list.filter(w => !keys.has(w.key)))
    return { result: summariseWork(after) } as any
  })

  // A Jira transition of a key on the list moves the list item too.
  on('tool.call', { tool: JIRA_TRANSITION_TOOL }, async ($, e, next) => {
    const ran = await next(e)
    try {
      const key = String((e as any).issueIdOrKey ?? '').toUpperCase()
      const text = String((ran as any)?.text ?? JSON.stringify((ran as any)?.result ?? ''))
      const m = text.match(/"statusName"\s*:\s*"([^"]+)"/)
      const status = m ? statusFromJira(m[1]!) : undefined
      if (key && status) {
        const list = (await read($, work)) ?? []
        const hit = list.find(w => w.key.toUpperCase() === key)
        if (hit && useBeads) {
          await beadsWork($, { key: hit.key, status, note: status === 'done' ? `Jira: ${m![1]}` : undefined }, hit)
          await refresh($)
        } else if (hit) {
          await changeWork($, l =>
            l.map(w =>
              w.key.toUpperCase() === key
                ? { ...w, status, note: status === 'done' ? `Jira: ${m![1]}` : w.note, updatedAt: new Date().toISOString() }
                : w,
            ),
          )
        }
      }
    } catch {
      // The transition itself stands; the list just isn't moved.
    }
    return ran
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Input } = $.ui.resolve(e) as any
    const list = (await read($, decisions)) ?? []
    const open = list.filter(isOpen)
    const answered = list.filter(d => !isOpen(d)).slice(-2).reverse()
    const cur = open[0]
    const items = visibleWork((await read($, work)) ?? [])
    const isDoneOpen = (await read($, showDone)) ?? false
    const foldedGroups = new Set((await read($, folded)) ?? [])
    const expandedGroups = new Set((await read($, expanded)) ?? [])
    const flip = (l: string[] | undefined, name: string) => {
      const s = new Set(l ?? [])
      if (s.has(name)) s.delete(name)
      else s.add(name)
      return [...s]
    }
    const toggleFold = (name: string) => void update($, folded, l => flip(l, name))
    const toggleMore = (name: string) => void update($, expanded, l => flip(l, name))
    const cols = Math.max(20, Number((e as any).props?.bodyColumns ?? 40))
    const bigBar = Math.max(10, Math.min(30, cols - 16))
    const smallBar = Math.max(6, Math.min(14, Math.floor(bigBar / 2)))
    const all = progress(items)
    const groups = groupWork(items)
    const finished = items.filter(isFinished)

    // One segment per status, in this order, sized by its share of the counted
    // items (dropped ones don't count). Cumulative rounding keeps the width exact.
    const SEGMENTS: WorkStatus[] = ['done', 'review', 'running', 'waiting', 'blocked', 'todo']
    const bar = (list: WorkItem[], width: number, key: string) => {
      const counted = list.filter(w => w.status !== 'dropped')
      if (!counted.length) return <Text key={key} dimColor>{'░'.repeat(width)}</Text>
      let acc = 0
      let drawn = 0
      return (
        <Text key={key}>
          {SEGMENTS.map(s => {
            acc += counted.filter(w => w.status === s).length
            const end = Math.round((acc / counted.length) * width)
            const n = end - drawn
            drawn = end
            if (n <= 0) return null
            return s === 'todo' ? (
              <Text key={`${key}-${s}`} dimColor>
                {'░'.repeat(n)}
              </Text>
            ) : (
              <Text key={`${key}-${s}`} color={statusColor(s)}>
                {'█'.repeat(n)}
              </Text>
            )
          })}
        </Text>
      )
    }
    const legend = SEGMENTS.map(s => ({ s, n: items.filter(w => w.status === s).length })).filter(x => x.n > 0)
    // bar() runs only while the tree below is built, after this is defined.
    const statusColor = (s: WorkStatus) =>
      s === 'done'
        ? 'green'
        : s === 'review'
          ? 'magenta'
          : s === 'blocked'
            ? 'red'
            : s === 'running'
              ? 'cyan'
              : s === 'waiting'
                ? 'yellow'
                : undefined
    const row = (w: WorkItem, prefix: string) => (
      <Box key={`${prefix}-${w.key}`} flexDirection="column">
        <Text dimColor={isFinished(w)}>
          <Text color={statusColor(w.status)}>{(LABEL[w.status] ?? w.status).padEnd(8)}</Text>{' '}
          {w.order !== undefined && <Text dimColor>{w.order}. </Text>}
          <Text bold>{w.key}</Text> {w.title}
          {w.due && !isFinished(w) && <Text color="yellow"> · {w.due}</Text>}
        </Text>
        {w.note && NOTE_STATUSES.includes(w.status) && (
          <Text dimColor>
            {'         '}
            {w.note}
            {w.who ? ` · ${w.who}` : ''}
          </Text>
        )}
      </Box>
    )

    const workSection = (
      <Box flexDirection="column" gap={1}>
        <Box flexDirection="column">
          <Text bold>
            Work <Text dimColor>· {all.done} of {all.total} done</Text> <Text color="green">{all.pct}%</Text>
          </Text>
          {items.length > 0 && bar(items, bigBar, 'bar-all')}
          {legend.length > 0 && (
            <Text>
              {legend.map(({ s, n }, i) => (
                <Text key={`lg-${s}`}>
                  {i > 0 ? '  ' : ''}
                  {s === 'todo' ? <Text dimColor>░</Text> : <Text color={statusColor(s)}>█</Text>}
                  <Text dimColor>
                    {' '}
                    {LABEL[s]} {n}
                  </Text>
                </Text>
              ))}
            </Text>
          )}
          {items.length === 0 && <Text dimColor>Nothing on the list yet.</Text>}
        </Box>
        {groups.map(g => {
          const p = progress(g.items)
          const active = g.items.filter(w => !isFinished(w))
          const isFolded = foldedGroups.has(g.name)
          return (
            <Box key={`g-${g.name}`} flexDirection="column">
              <Box flexDirection="row" gap={1}>
                <Button
                  key={`fold-${g.name}`}
                  plain
                  label={`${isFolded ? '▸' : '▾'} ${g.name}`}
                  onPress={() => toggleFold(g.name)}
                />
                {bar(g.items, smallBar, `bar-${g.name}`)}
                <Text>
                  <Text dimColor>{p.done}/{p.total}</Text> <Text color="green">{p.pct}%</Text>
                  {isFolded && active.length > 0 ? <Text dimColor> · {active.length} open</Text> : null}
                </Text>
              </Box>
              {!isFolded && active.length === 0 && <Text dimColor>All done.</Text>}
              {!isFolded && (expandedGroups.has(g.name) ? active : active.slice(0, GROUP_ROWS)).map(w => row(w, g.name))}
              {!isFolded && active.length > GROUP_ROWS && (
                <Button
                  key={`more-${g.name}`}
                  plain
                  dimColor
                  label={expandedGroups.has(g.name) ? '  show fewer' : `  ${active.length - GROUP_ROWS} more`}
                  onPress={() => toggleMore(g.name)}
                />
              )}
            </Box>
          )
        })}
        {finished.length > 0 && (
          <Box flexDirection="column">
            <Button
              key="done-toggle"
              hotkey="w"
              plain
              dimColor
              label={isDoneOpen ? `Done · ${finished.length} (hide)` : `Done · ${finished.length} (show)`}
              onPress={() => void update($, showDone, v => !v)}
            />
            {isDoneOpen &&
              groupWork(finished).map(g => (
                <Box key={`dg-${g.name}`} flexDirection="column">
                  {groups.length > 1 && <Text dimColor>{g.name}</Text>}
                  {g.items.map(w => row(w, `done-${g.name}`))}
                </Box>
              ))}
          </Box>
        )}
      </Box>
    )

    return (
      <Box flexDirection="column" gap={1}>
        {!cur && <Text dimColor>No decisions waiting on you.</Text>}
        {cur && (
          <Box flexDirection="column">
            <Text dimColor>
              {cur.id} · {open.length === 1 ? 'the only one waiting' : `1 of ${open.length} waiting`}
              {cur.from ? ` · from ${cur.from}` : ''}
            </Text>
            <Text bold>{cur.question}</Text>
            {cur.context && <Text dimColor>{cur.context}</Text>}
          </Box>
        )}
        {cur && (
          <Box flexDirection="column">
            {cur.options.map((o, i) => (
              <Box key={`${cur.id}-o${i}`} flexDirection="column">
                <Button
                  key={`${cur.id}-b${i}`}
                  hotkey={String(i + 1)}
                  plain
                  variant={cur.recommended === i ? 'primary' : undefined}
                  label={cur.recommended === i ? `${o.label} (recommended)` : o.label}
                  onPress={() => void answer($, cur.id, i)}
                />
                {o.detail && <Text dimColor>   {o.detail}</Text>}
              </Box>
            ))}
          </Box>
        )}
        {cur && (
          <Input
            key={`${cur.id}-other`}
            label="Other: "
            placeholder="type your own answer"
            submitLabel="send"
            onSubmit={(v: string) => {
              if (v.trim()) void answer($, cur.id, -1, v.trim())
            }}
          />
        )}
        {cur && (
          <Box flexDirection="row" gap={2}>
            <Button key={`${cur.id}-discuss`} hotkey="d" plain dimColor label="Discuss first" onPress={() => void answer($, cur.id, -2)} />
            {open.length > 1 && (
              <Button
                key={`${cur.id}-later`}
                hotkey="l"
                plain
                dimColor
                label="Later"
                onPress={() => {
                  if (useBeads) {
                    const i = later.indexOf(cur.id)
                    if (i >= 0) later.splice(i, 1)
                    later.push(cur.id)
                  }
                  void change($, l => {
                    const me = l.find(d => d.id === cur.id)
                    return me ? [...l.filter(d => d.id !== cur.id), me] : l
                  })
                }}
              />
            )}
          </Box>
        )}
        {answered.length > 0 && (
          <Box flexDirection="column">
            <Text dimColor>Answered</Text>
            {answered.map(d => (
              <Text key={`${d.id}-done`} dimColor>
                {d.id} {d.question} → {d.pick === -1 ? d.answer : d.pick === -2 ? 'discuss first' : d.options[d.pick ?? 0]?.label}
                {d.isDelivered ? '' : ' (not sent yet)'}
              </Text>
            ))}
          </Box>
        )}
        {workSection}
      </Box>
    )
  })
}
