import type { RuleEvaluation } from '@/types'

/** Rules where TRIGGERED means the happy path succeeded — not an issue. */
const POSITIVE_TRIGGERED_RULES = new Set([
  'AUTHORITY_AUTO_APPROVE',
  'HARD_CONTROL_GATE',
  'STAGE3_STATE',
  'CONTRACT_GATE',
  'CONTRACT_SCHEMA',
  'CONTRACT_PROCESSING_STATE',
  'CONTRACT_FRESHNESS',
])

const POSITIVE_TRIGGERED_PREFIXES = ['MATERIALITY_']

export function isPositiveTriggeredRule(rule: RuleEvaluation): boolean {
  if (rule.result !== 'TRIGGERED') return false
  if (POSITIVE_TRIGGERED_RULES.has(rule.rule_id)) return true
  return POSITIVE_TRIGGERED_PREFIXES.some((prefix) => rule.rule_id.startsWith(prefix))
}

/** Rules that belong in the "Items needing attention" panel. */
export function isStage4AttentionRule(rule: RuleEvaluation): boolean {
  if (rule.result !== 'TRIGGERED') return false
  return !isPositiveTriggeredRule(rule)
}

export type RuleBadgeVariant = 'success' | 'warning' | 'danger' | 'muted'

export function stage4RuleBadgeVariant(rule: RuleEvaluation): RuleBadgeVariant {
  if (rule.result === 'ERROR') return 'danger'
  if (rule.result === 'NOT_TRIGGERED') return 'muted'
  if (isPositiveTriggeredRule(rule)) return 'success'
  return 'warning'
}

export function stage4RuleResultLabel(rule: RuleEvaluation): string {
  if (rule.result === 'TRIGGERED' && isPositiveTriggeredRule(rule)) {
    return 'APPLIED'
  }
  return rule.result
}
