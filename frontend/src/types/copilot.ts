export interface GeneratorSetpointChange {
  generator_id: string
  new_setpoint_mw: number
  ramp_rate_mw_per_min: number | null
}

export interface RedispatchRequest {
  generator_id: string
  region: string
  upward_mw: number
  downward_mw: number
  reason: string
}

export interface LoadSheddingFlag {
  load_id: string
  region: string
  shed_mw: number
  priority: number
}

export interface InterconnectFlowAdjustment {
  border: string
  target_flow_mw: number
  current_flow_mw: number
}

export interface ProposalAction {
  timestamp: string
  agent_id: string
  generator_setpoint_changes: GeneratorSetpointChange[]
  redispatch_requests: RedispatchRequest[]
  load_shedding_flags: LoadSheddingFlag[]
  interconnect_flow_adjustments: InterconnectFlowAdjustment[]
}

export interface N1Violation {
  element: string
  status?: string
  violations?: string[]
}

export interface N1Context {
  available: boolean
  passed?: boolean
  status?: string
  message?: string
  violated_contingencies?: N1Violation[]
}

export interface ObservationSummary {
  hour_index: number
  timestamp: string
  total_generation_mw: number
  total_load_mw: number
  imbalance_mw: number
  system_frequency_hz: number
  num_generators: number
  num_loads: number
  num_buses: number
  num_branches: number
  has_violations: boolean
  market_price_eur_mwh: number
}

export interface AgentOutput {
  agent_id: string
  reasoning: string
  has_action: boolean
  model: string
  proposal_id?: string
}

export interface Proposal {
  proposal_id: string
  hour_index: number
  agent_id: string
  reasoning: string
  action: ProposalAction
  timestamp: string
  status: 'pending' | 'confirmed' | 'rejected' | 'executed' | 'error'
  execution_result?: Record<string, unknown> | null
  n1_result?: { passed: boolean; status: string; message: string } | null
}

export interface AnalysisResult {
  hour_index: number
  timestamp: string
  observation: ObservationSummary
  n1_context: N1Context
  agent_outputs: AgentOutput[]
  proposals: Proposal[]
}

export interface ChatMessage {
  role: 'operator' | 'athena'
  content: string
  timestamp: string
}

export interface CopilotStatus {
  initialised: boolean
  simulation_running: boolean
  simulation_status: string
  current_hour: number
  completed_hours: number
  total_hours: number
  failed_hours: number
  n1_failed_hours: number
  replay_coverage: number
  total_proposals: number
  chat_messages: number
}

export interface SimulationStatus {
  run_id: string
  status: string
  start_hour: number
  end_hour: number
  current_hour: number
  total_hours: number
  completed_hours: number
  failed_hours: number[]
  n1_failed_hours: number[]
  replay_coverage_percent: number
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface SimulationHourResult {
  hour_index: number
  timestamp: string
  observation: ObservationSummary
  agent_outputs: AgentOutput[]
  proposals: Proposal[]
  actions_executed: number
  actions_accepted: number
  n1_passed: boolean | null
  n1_detail: {
    passed: boolean
    status: string
    message: string
    contingencies_tested: number
    violated_contingencies: N1Violation[]
  } | null
  n1_failed: boolean
  step_failed: boolean
  evaluation_results?: Record<string, unknown>[]
}
