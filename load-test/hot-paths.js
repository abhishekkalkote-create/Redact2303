/*
 * Phase 6 build-plan item: "load test to SLOs (k6: 200 concurrent orgs simulated)."
 *
 * Each VU iteration simulates one org's full first-session lifecycle against the API's
 * hottest path (specs/00-overview.md "Performance SLOs"; specs/10-build-plan.md Phase 1/3
 * ACs): dev-login -> create org -> process the free sample document (exercises extract +
 * deterministic + contextual detection) -> bulk-approve every candidate -> complete review
 * -> export (clean PDF + exemption log + certificate). No two VUs ever touch the same org
 * — every iteration mints a fresh org via a fresh dev-login email, so this is genuinely
 * "N concurrent orgs," not N requests hammering one shared tenant.
 *
 * What this proves and doesn't: the sample document is a single synthetic page, not the
 * spec's 20-page/500-page/100-page benchmark fixtures, so the upload/detect/export timings
 * here are a proxy at a much smaller scale, not a literal test of specs/00-overview.md's
 * 60s/20min/90s targets — those need the real golden-fixture PDFs and a real deployed
 * environment (this sandbox has neither). What IS a direct, literal SLO check regardless
 * of document size is the review-action latency target (specs/01-product-spec.md US-6:
 * "p95 action latency < 300ms") — the bulk-approve call below is measured against exactly
 * that threshold.
 *
 * Usage:
 *   k6 run load-test/hot-paths.js
 *   BASE_URL=https://staging.example.com TARGET_VUS=200 RAMP_DURATION=2m k6 run load-test/hot-paths.js
 *
 * Requires the API running with ENV=local (or another env with dev_auth_enabled=true) —
 * this never touches real Cognito. See load-test/README.md.
 */

import http from "k6/http";
import { check, fail } from "k6";
import { Trend } from "k6/metrics";
import { randomString } from "https://jslib.k6.io/k6-utils/1.4.0/index.js";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const TARGET_VUS = parseInt(__ENV.TARGET_VUS || "5", 10);
const RAMP_DURATION = __ENV.RAMP_DURATION || "10s";
const HOLD_DURATION = __ENV.HOLD_DURATION || "20s";

const uploadToReadyTrend = new Trend("upload_to_ready_ms");
const reviewActionTrend = new Trend("review_action_ms");
const exportTrend = new Trend("export_ms");

export const options = {
  scenarios: {
    orgs: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: RAMP_DURATION, target: TARGET_VUS },
        { duration: HOLD_DURATION, target: TARGET_VUS },
        { duration: RAMP_DURATION, target: 0 },
      ],
    },
  },
  thresholds: {
    // The one target below is a literal, size-independent spec number
    // (specs/01-product-spec.md US-6). The other two are proxy budgets sized for this
    // single-page sample document, NOT the spec's 20-page/100-page targets — see the
    // module docstring above.
    review_action_ms: ["p(95) < 300"],
    upload_to_ready_ms: ["p(95) < 5000"],
    export_ms: ["p(95) < 3000"],
    http_req_failed: ["rate < 0.01"],
  },
};

function jsonHeaders(token) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

function devLogin() {
  const email = `k6-drill-${__VU}-${__ITER}-${randomString(6)}@example.com`;
  const res = http.post(
    `${BASE_URL}/v1/auth/dev-login`,
    JSON.stringify({ email, name: "k6 load-test user" }),
    { headers: jsonHeaders(), tags: { name: "dev_login" } }
  );
  check(res, { "dev-login 200": (r) => r.status === 200 });
  if (res.status !== 200) fail(`dev-login failed: ${res.status} ${res.body}`);
  return res.json("access_token");
}

function createOrg(token) {
  const res = http.post(
    `${BASE_URL}/v1/orgs`,
    JSON.stringify({
      name: `k6 Drill Org ${__VU}-${__ITER}-${randomString(4)}`,
      jurisdiction_state: "WA",
      org_type: "city_clerk",
    }),
    { headers: jsonHeaders(token), tags: { name: "create_org" } }
  );
  check(res, { "create org 201": (r) => r.status === 201 });
  if (res.status !== 201) fail(`create org failed: ${res.status} ${res.body}`);
  return res.json("id");
}

function processSampleDocument(token) {
  const startedAt = Date.now();
  const res = http.post(`${BASE_URL}/v1/documents/sample`, null, {
    headers: jsonHeaders(token),
    tags: { name: "process_sample_document" },
  });
  const ok = check(res, {
    "sample doc 201": (r) => r.status === 201,
    "sample doc ready_for_review": (r) => r.json("status") === "ready_for_review",
  });
  if (!ok) fail(`sample document processing failed: ${res.status} ${res.body}`);
  uploadToReadyTrend.add(Date.now() - startedAt);
  return res.json("id");
}

function fetchCandidates(token, docId) {
  const res = http.get(`${BASE_URL}/v1/documents/${docId}/manifest`, {
    headers: jsonHeaders(token),
    tags: { name: "get_manifest" },
  });
  check(res, { "manifest 200": (r) => r.status === 200 });
  if (res.status !== 200) fail(`manifest fetch failed: ${res.status} ${res.body}`);
  return res.json("candidates") || [];
}

function approveAllCandidates(token, docId, candidates) {
  const byCode = {};
  const noCode = [];
  for (const c of candidates) {
    if (c.exemption_code_id) {
      (byCode[c.exemption_code_id] = byCode[c.exemption_code_id] || []).push(c.id);
    } else {
      noCode.push(c.id);
    }
  }

  const startedAt = Date.now();
  for (const [exemptionCodeId, ids] of Object.entries(byCode)) {
    const res = http.post(
      `${BASE_URL}/v1/documents/${docId}/candidates:bulk`,
      JSON.stringify({ action: "approve", candidate_ids: ids, exemption_code_id: exemptionCodeId }),
      { headers: jsonHeaders(token), tags: { name: "bulk_approve" } }
    );
    check(res, { "bulk approve 200": (r) => r.status === 200 });
    if (res.status !== 200) fail(`bulk approve failed: ${res.status} ${res.body}`);
  }
  // Candidates the deterministic/contextual pass didn't resolve to an org exemption code
  // (rare, but possible) can't be bulk-approved without one — reject them instead so
  // review:complete's "no unresolved low-confidence candidates" gate still clears.
  if (noCode.length > 0) {
    const res = http.post(
      `${BASE_URL}/v1/documents/${docId}/candidates:bulk`,
      JSON.stringify({ action: "reject", candidate_ids: noCode }),
      { headers: jsonHeaders(token), tags: { name: "bulk_reject" } }
    );
    check(res, { "bulk reject 200": (r) => r.status === 200 });
  }
  reviewActionTrend.add(Date.now() - startedAt);
}

// The sample document deliberately repeats some names/text (specs/07-ui-spec.md's
// "apply to all similar" is exactly for this) — NER-based deterministic detection isn't
// guaranteed to catch every occurrence of a given string, and export_service.create_export
// correctly BLOCKS export if any approved candidate's text still appears elsewhere in the
// document (specs/05-redaction-pipeline.md Stage 7's integrity verifier). A real reviewer
// closes that gap with search-and-redact before completing review; this does the same for
// every distinct text an approved candidate already covers, so the export step below is
// exercising the same completed-review state a real reviewer would produce, not tripping
// over an incomplete one.
function sweepRemainingOccurrences(token, docId, candidates) {
  const seen = new Set();
  for (const c of candidates) {
    if (!c.exemption_code_id || !c.display_text || seen.has(c.display_text)) continue;
    seen.add(c.display_text);
    const res = http.post(
      `${BASE_URL}/v1/documents/${docId}/search-redact`,
      JSON.stringify({
        query: c.display_text,
        is_pattern: false,
        scope: "document",
        exemption_code_id: c.exemption_code_id,
      }),
      { headers: jsonHeaders(token), tags: { name: "search_redact" } }
    );
    check(res, { "search-redact 200": (r) => r.status === 200 });
    if (res.status !== 200) fail(`search-redact failed: ${res.status} ${res.body}`);
  }
}

function completeReview(token, docId) {
  const res = http.post(`${BASE_URL}/v1/documents/${docId}/review:complete`, null, {
    headers: jsonHeaders(token),
    tags: { name: "review_complete" },
  });
  check(res, { "review:complete 200": (r) => r.status === 200 });
  if (res.status !== 200) fail(`review:complete failed: ${res.status} ${res.body}`);
}

function exportDocument(token, docId) {
  const startedAt = Date.now();
  const res = http.post(`${BASE_URL}/v1/documents/${docId}/exports`, JSON.stringify({}), {
    headers: jsonHeaders(token),
    tags: { name: "create_export" },
  });
  const ok = check(res, { "export 201": (r) => r.status === 201 });
  if (!ok) fail(`export failed: ${res.status} ${res.body}`);
  exportTrend.add(Date.now() - startedAt);
}

export default function () {
  const token = devLogin();
  createOrg(token);
  const docId = processSampleDocument(token);
  const candidates = fetchCandidates(token, docId);
  if (candidates.length > 0) {
    approveAllCandidates(token, docId, candidates);
    sweepRemainingOccurrences(token, docId, candidates);
  }
  completeReview(token, docId);
  exportDocument(token, docId);
}
