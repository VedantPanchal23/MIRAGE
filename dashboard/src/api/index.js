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
  health,
  reports,
};

export default api;
