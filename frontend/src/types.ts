export type Role = "admin" | "trader" | "viewer";

export interface User {
  id: number;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string | null;
}

export interface AccountInfo {
  login: number;
  name: string;
  server: string;
  currency: string;
  company: string;
  balance: number;
  equity: number;
  profit: number;
  margin: number;
  margin_free: number;
  margin_level: number;
  leverage: number;
  trade_mode: number;
  trade_mode_name: string;
  trade_allowed: boolean;
  trade_expert: boolean;
  currency_digits?: number;
}

export interface TerminalInfo {
  connected: boolean;
  trade_allowed: boolean;
  name: string;
  company: string;
  build: number;
  ping_last: number;
  path: string;
}

export interface Runtime {
  account_id: number;
  status: "disconnected" | "connecting" | "connected" | "error";
  error?: string | null;
  unavailable?: boolean;
  account?: AccountInfo | null;
  terminal?: TerminalInfo | null;
  connected_at?: number | null;
  last_update?: number | null;
  positions_count?: number;
  orders_count?: number;
}

export interface Account {
  id: number;
  name: string;
  connection_type: "local" | "bridge";
  login: number;
  server: string;
  has_password: boolean;
  terminal_path: string | null;
  bridge_url: string | null;
  has_bridge_token: boolean;
  auto_connect: boolean;
  trade_mode: number | null;
  trade_mode_name: string | null;
  currency: string | null;
  company: string | null;
  last_connected_at: string | null;
  runtime: Runtime;
}

export interface Tick {
  time: number;
  bid: number;
  ask: number;
  last: number;
  time_msc: number;
  digits: number;
  spread_points: number | null;
}

export interface Rate {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  tick_volume: number;
}

export interface SymbolBrief {
  name: string;
  description: string;
  path: string;
  digits: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  point: number;
}

export interface Position {
  ticket: number;
  time: number;
  type: number;
  side: "buy" | "sell";
  magic: number;
  volume: number;
  price_open: number;
  sl: number;
  tp: number;
  price_current: number;
  swap: number;
  profit: number;
  symbol: string;
  comment: string;
}

export interface Order {
  ticket: number;
  time_setup: number;
  type: number;
  order_type: string;
  magic: number;
  volume_current: number;
  volume_initial: number;
  price_open: number;
  sl: number;
  tp: number;
  price_current: number;
  symbol: string;
  comment: string;
  state?: number;
  time_done?: number;
}

export interface Deal {
  ticket: number;
  order: number;
  time: number;
  type: number;
  deal_type: string;
  entry: number;
  deal_entry: string;
  magic: number;
  position_id: number;
  volume: number;
  price: number;
  commission: number;
  swap: number;
  profit: number;
  fee: number;
  symbol: string;
  comment: string;
}

export interface TradeResult {
  ok: boolean;
  retcode: number | null;
  retcode_text: string;
  order?: number;
  deal?: number;
  price?: number;
  volume?: number;
  comment?: string;
  margin?: number;
  margin_free?: number;
}

export interface ParamDef {
  key: string;
  label: string;
  type: "int" | "float" | "bool";
  default: number | boolean;
  min: number | null;
  max: number | null;
  step: number | null;
  help: string;
}

export interface StrategyDef {
  key: string;
  title: string;
  description: string;
  params: ParamDef[];
}

export interface Catalog {
  strategies: StrategyDef[];
  risk: ParamDef[];
  timeframes: string[];
}

export interface BotMetrics {
  bot_id: number;
  running: boolean;
  uptime_s: number;
  cycles: number;
  errors: number;
  consecutive_errors: number;
  orders_sent: number;
  last_cycle: number | null;
  waiting_reason: string | null;
  state: Record<string, unknown>;
  status?: string;
}

export interface Bot {
  id: number;
  name: string;
  account_id: number;
  strategy: string;
  strategy_title: string;
  symbol: string;
  timeframe: string;
  params: Record<string, number | boolean>;
  risk: Record<string, number | boolean>;
  trade_mode: "live" | "signals";
  magic: number;
  status: "stopped" | "starting" | "running" | "error";
  desired_running: boolean;
  state: Record<string, any>;
  last_error: string | null;
  last_heartbeat: string | null;
  started_at: string | null;
  created_at: string | null;
  metrics: BotMetrics | null;
}

export interface BotLog {
  id: number;
  ts: string;
  level: string;
  message: string;
  data: Record<string, unknown> | null;
}

export interface BotOrderRow {
  id: number;
  ts: string;
  action: string;
  symbol: string;
  side: string | null;
  volume: number | null;
  price: number | null;
  ok: boolean;
  retcode: number | null;
  order: number | null;
  deal: number | null;
  comment: string | null;
}

export interface Performance {
  days: number;
  deals: Deal[];
  positions: Position[];
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  realized_pnl: number;
  floating_pnl: number;
  profit_factor: number | null;
  max_drawdown: number;
  equity_curve: { time: number; pnl: number }[];
}

export interface AuditRow {
  id: number;
  ts: string;
  username: string | null;
  action: string;
  target: string | null;
  ok: boolean;
  details: Record<string, unknown> | null;
  ip: string | null;
}

export interface SystemStatus {
  version: string;
  server_time: number;
  python: string;
  platform: string;
  os: string;
  mt5_package_installed: boolean;
  local_mode_available: boolean;
  local_mode_note: string | null;
  allow_real_trading: boolean;
  environment: string;
  accounts: Runtime[];
  bots_running: number[];
  ws_clients: number;
}
