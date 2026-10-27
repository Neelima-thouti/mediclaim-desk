export const DECISIONS = {
  APPROVE: { label: 'Approve', tone: 'good' },
  PARTIAL_APPROVE: { label: 'Partial approval', tone: 'good' },
  QUERY_MORE_INFO: { label: 'Query: more information needed', tone: 'warn' },
  REJECT: { label: 'Reject', tone: 'bad' },
  ESCALATE_TO_HUMAN: { label: 'Escalate to officer', tone: 'alert' },
}

export const STATUSES = {
  RECEIVED: { label: 'Received', tone: 'neutral' },
  PROCESSING: { label: 'Processing', tone: 'info' },
  AWAITING_REVIEW: { label: 'Awaiting review', tone: 'warn' },
  COMPLETED: { label: 'Completed', tone: 'good' },
  FAILED: { label: 'Failed', tone: 'bad' },
}

// Who does each step: the AI model, plain code, or a person. This is the story of the demo.
export const STEPS = {
  classify: { label: 'Classify documents', by: 'ai' },
  extract_one: { label: 'Extract fields', by: 'ai' },
  rules: { label: 'Rules engine', by: 'code' },
  consistency: { label: 'Consistency agent', by: 'ai' },
  coverage: { label: 'Coverage agent', by: 'ai' },
  fraud: { label: 'Fraud agent', by: 'ai' },
  decide: { label: 'Decision supervisor and guardrails', by: 'ai' },
  human_review: { label: 'Officer review', by: 'person' },
}

export const BY = { ai: 'AI model', code: 'Plain code', person: 'Person' }

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })
export const money = (v) => (v === null || v === undefined ? '-' : inr.format(v))
