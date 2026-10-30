export type Ticket = {
  ticket_number: string;
  subject: string;
  description: string;
  priority: "low" | "medium" | "high" | "urgent";
  status: "open" | "pending" | "resolved" | "escalated";
  customer_name: string;
  order_number: string | null;
  created_at: string;
  order_payment_status?: string | null;
  order_shipping_status?: string | null;
  order_total_minor?: number | null;
  days_past_promised_delivery?: number | null;
  order_refunded?: boolean | null;
};

export type Order = {
  order_number: string;
  total_amount_minor: number;
  currency: string;
  payment_status: string;
  shipping_status: string;
  promised_delivery_at: string;
  actual_delivery_at: string | null;
  customer_name: string;
  refunded: boolean;
};

export type DeliveryEvent = { event_type: string; event_time: string; description: string };
export type OrderDetail = Order & { delivery_events: DeliveryEvent[] };
export type TicketDetail = Ticket & { order: Order | null };
export type Page<T> = { items: T[]; next_cursor: string | null };

export type Evidence = {
  claim?: string;
  source_type?: string;
  source_id?: string;
  eligible?: boolean;
  reasons?: string[];
  max_amount_minor?: number;
  policy_version?: string;
};

export type Action = {
  action_id: string;
  action_type: "refund" | "send_reply" | "escalate_ticket";
  payload: Record<string, unknown>;
  status: string;
  status_reason: string | null;
  reason: string;
  evidence: Evidence[];
  policy_version: string | null;
  approval: { approval_id: string; status: string } | null;
};

export type Run = {
  run_id: string;
  mode: "ticket" | "batch";
  status: string;
  ticket_number: string | null;
  parent_run_id: string | null;
  original_instruction: string;
  requested_by_user_id: string;
  requested_by_name: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type Findings = {
  ticket_number: string;
  summary: string;
  findings: { claim: string; source_type: string; source_id: string }[];
  requires_human_followup: boolean;
};

export type RunDetail = Run & {
  findings: Findings | null;
  summary: { text: string | null; no_action_reasons?: string[]; error_code?: string } | null;
  usage: { model: string; tool_calls: number; tool_errors: number; duration_ms: number; input_tokens: number; output_tokens: number } | null;
  actions: Action[];
  children: Run[];
};

export type Approval = {
  approval_id: string;
  action_id: string;
  run_id: string;
  ticket_number: string;
  ticket_subject: string;
  order_number: string | null;
  action_type: Action["action_type"];
  payload: Record<string, unknown>;
  reason: string;
  evidence: Evidence[];
  policy_version: string | null;
  status: "pending" | "approved" | "rejected" | "expired";
  action_status: string;
  action_status_reason: string | null;
  action_hash: string;
  requested_by: string;
  requested_by_name: string | null;
  decided_by: string | null;
  decided_by_name: string | null;
  decided_at: string | null;
  decision_note: string | null;
  created_at: string;
  expires_at: string;
  permitted_reviewer_roles: string[];
  simulated: boolean;
};

export type Overview = {
  open_tickets: number;
  high_priority_open_tickets: number;
  pending_approvals: number;
  runs_today: number;
  simulated_refunds: number;
  simulated_refund_total_minor: number;
};

export type Refund = { refund_id: string; order_number: string; action_id: string | null; amount_minor: number; currency: string; status: string; created_at: string };
export type Message = { message_id: string; ticket_number: string; action_id: string; destination: string; body: string; status: string; created_at: string };
export type AuditEvent = { id: string; actor_type: string; actor_id: string; run_id: string | null; action_id: string | null; event_type: string; metadata: Record<string, unknown>; created_at: string };
export type RunEvent = { id: number; event: string; data: Record<string, unknown> & { run_id: string; created_at: string } };

export type Policy = { version: string; effective_from: string; min_delay_days: number; refund_percent: number; policy_text: string };
