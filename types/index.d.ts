export type DecisionOption = { label: string; detail?: string }

export type Decision = {
  id: string
  question: string
  context?: string
  from?: string
  options: DecisionOption[]
  recommended?: number
  postedAt: string
  /** The option's index, or -1 for a written answer. Absent while open. */
  pick?: number
  answer?: string
  answeredAt?: string
  isDelivered?: boolean
}

export type WorkStatus = 'todo' | 'running' | 'waiting' | 'review' | 'blocked' | 'done' | 'dropped'

export type WorkItem = {
  /** Jira key when there is one (ABC-123), else a short id. */
  key: string
  title: string
  status: WorkStatus
  /** One line on where it stands now. */
  note?: string
  who?: string
  link?: string
  /** The list it belongs to ("Sprint 12"). Ungrouped items show under "Today". */
  group?: string
  /** Position inside its group (1 first). Unordered items follow, by status. */
  order?: number
  /** When it is due, as short text ("tonight", "Fri 13"). */
  due?: string
  /** YYYY-MM-DD the item was first added. */
  day: string
  updatedAt: string
}

declare module 'claude-code' {
  interface PluginState {
    decisions: { list: Shaped<Decision[]>; work: Shaped<WorkItem[]>; showDone: boolean; folded: string[]; expanded: string[] }
  }
}
