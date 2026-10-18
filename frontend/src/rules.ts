// Plain-English wording for compiled rules, plus the policy kept between screens.
import { objectsLabel } from './format'
import type { Rule } from './types'

export const DEMO_POLICY =
  'At the main entrance, only clear bags are permitted and professional cameras require review. ' +
  'Keep the emergency exit clear; alert if a bag or chair blocks it for more than five seconds.'

const zoneLabel = (zone: string) => zone.replace(/_/g, ' ')

export function ruleCondition(rule: Rule): string {
  const what = objectsLabel(rule.objects)
  if (rule.type === 'persistent_object') {
    return `A ${what} stays in the ${zoneLabel(rule.zone)} for ${rule.duration_seconds} s or more`
  }
  if (rule.attribute?.name === 'transparent') {
    return rule.attribute.expected ? `A ${what} is probably not clear` : `A ${what} is probably see-through`
  }
  if (rule.attribute?.name === 'professional') {
    return rule.attribute.expected ? `A ${what} is probably not professional` : `A ${what} is probably professional`
  }
  return `A ${what} is seen in the ${zoneLabel(rule.zone)}`
}

const KEY = 'policylens.policy'

export function savePolicy(text: string, rules: Rule[]) {
  sessionStorage.setItem(KEY, JSON.stringify({ text, rules }))
}

export function loadPolicy(): { text: string; rules: Rule[] } | null {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? 'null')
  } catch {
    return null
  }
}
