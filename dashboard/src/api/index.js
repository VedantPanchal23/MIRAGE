/**
 * Centralized API Client Barrel Export for MIRAGE Dashboard.
 */

export {
  apiFetch,
  setApiToken,
  getApiToken,
  onUnauthorized,
  ApiError,
} from "./client";

export {
  getDashboardStats,
  getDashboardSessions,
  getSessionById,
  getDriftReport,
} from "./dashboard";

export {
  getAlerts,
  acknowledgeAlert,
} from "./alerts";

export {
  getStreamWebSocketUrl,
} from "./stream";

export {
  getHealth,
  getReadiness,
} from "./health";

export {
  generateReport,
  getReportById,
  getReportPdf,
  verifyAuditChain,
  getSessionAuditReport,
  getSessionCertificatePdf,
  exportAuditLogs,
  queryAuditLogs,
} from "./reports";

import * as dashboard from "./dashboard";
import * as alerts from "./alerts";
import * as stream from "./stream";
import * as health from "./health";
import * as reports from "./reports";
import { apiFetch, setApiToken, getApiToken, onUnauthorized, ApiError } from "./client";

export const api = {
  fetch: apiFetch,
  setToken: setApiToken,
  getToken: getApiToken,
  onUnauthorized,
  ApiError,
  dashboard,
  alerts,
  stream,
  health,
  reports,
};

export default api;
