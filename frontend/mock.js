// mock.js — static, dummy-data stand-in for the real FastAPI backend.
//
// This file exists ONLY so the dashboard can be deployed as a free static
// site (Vercel, GitHub Pages, ...) with no live Postgres/FastAPI behind it.
// The real system lives in /frontend + /src/api, backed by a real database,
// and that is what the project actually is. This is a demo shell around the
// same HTML/CSS/JS, showing the same flows with canned data.
//
// It exports the exact same getJSON/postJSON signatures app.js does, so
// every page's own script works completely unmodified against this instead.
//
// State lives in sessionStorage, not a plain JS variable: each HTML page is
// its own document load, so a plain in-memory object would silently reset
// every time you navigate between pages, losing the deletion request you
// just submitted before the certificate page could read it back.

const TENANT_1 = "00000000-0000-0000-0000-000000000001";
const TENANT_2 = "00000000-0000-0000-0000-000000000002";

const TENANT_LABELS = {
  [TENANT_1]: "Tenant 1",
  [TENANT_2]: "Tenant 2",
};

function tenantLabel(tenantId) {
  return TENANT_LABELS[tenantId] || tenantId;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function uuid() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function randomHex(length) {
  let s = "";
  while (s.length < length) s += Math.floor(Math.random() * 16).toString(16);
  return s.slice(0, length);
}

const GENESIS_HASH = "0".repeat(70);
const STORAGE_KEY = "lethe_demo_state_v1";

const SEARCH_RESULTS = {
  login: [
    "failed login alert: 9 failed login attempts for user priya from ip 142.88.21.60 on host auth-14 at 2026-09-02T11:14:22+00:00",
    "failed login alert: 6 failed login attempts for user noah from ip 203.15.77.9 on host web-07 at 2026-08-27T03:41:05+00:00",
    "failed login alert: 11 failed login attempts for user kenji from ip 88.201.44.133 on host auth-22 at 2026-09-14T19:02:51+00:00",
    "failed login alert: 4 failed login attempts for user mateo from ip 176.9.53.201 on host cache-11 at 2026-08-19T08:55:40+00:00",
    "failed login alert: 14 failed login attempts for user amara from ip 45.133.8.19 on host web-33 at 2026-09-06T22:17:09+00:00",
    "failed login alert: 7 failed login attempts for user zara from ip 91.204.17.80 on host auth-05 at 2026-08-30T14:28:16+00:00",
    "failed login alert: 5 failed login attempts for user devon from ip 23.88.145.6 on host api-19 at 2026-09-11T05:49:33+00:00",
    "failed login alert: 10 failed login attempts for user ivan from ip 199.21.6.144 on host web-41 at 2026-08-23T17:03:58+00:00",
  ],
  traffic: [
    "suspicious outbound traffic: host db-18 sent 612 MB to external ip 185.63.21.9 at 2026-09-05T02:11:40+00:00, flagged for review",
    "suspicious outbound traffic: host cache-26 sent 744 MB to external ip 92.118.4.77 at 2026-08-29T16:38:02+00:00, flagged for review",
    "suspicious outbound traffic: host web-09 sent 390 MB to external ip 45.9.221.33 at 2026-09-13T09:55:17+00:00, flagged for review",
    "suspicious outbound traffic: host api-33 sent 858 MB to external ip 178.62.5.190 at 2026-08-21T21:04:49+00:00, flagged for review",
    "suspicious outbound traffic: host auth-07 sent 521 MB to external ip 203.0.113.44 at 2026-09-08T13:22:31+00:00, flagged for review",
    "suspicious outbound traffic: host web-15 sent 667 MB to external ip 154.21.9.188 at 2026-08-25T06:17:55+00:00, flagged for review",
    "suspicious outbound traffic: host cache-02 sent 433 MB to external ip 198.51.100.77 at 2026-09-17T19:48:12+00:00, flagged for review",
    "suspicious outbound traffic: host db-31 sent 701 MB to external ip 203.0.113.19 at 2026-08-31T02:36:04+00:00, flagged for review",
  ],
  process: [
    "flagged process: unrecognized process 'remote_shell' spawned by user leah on host web-26 at 2026-09-04T08:12:46+00:00",
    "flagged process: unrecognized process 'netcrawl' spawned by user amara on host cache-09 at 2026-08-28T20:55:03+00:00",
    "flagged process: unrecognized process 'sysdiag.sh' spawned by user noah on host auth-18 at 2026-09-15T04:33:27+00:00",
    "flagged process: unrecognized process 'backup_agent' spawned by user kenji on host db-04 at 2026-08-22T12:09:14+00:00",
    "flagged process: unrecognized process 'svc_updater.exe' spawned by user mateo on host api-27 at 2026-09-09T23:41:38+00:00",
    "flagged process: unrecognized process 'remote_shell' spawned by user zara on host web-12 at 2026-08-26T15:17:52+00:00",
    "flagged process: unrecognized process 'netcrawl' spawned by user devon on host cache-33 at 2026-09-12T07:28:09+00:00",
    "flagged process: unrecognized process 'sysdiag.sh' spawned by user priya on host auth-21 at 2026-08-24T18:52:44+00:00",
  ],
  storage: [
    "unusual cloud-storage access: user noah downloaded 184 files from a shared bucket at 2026-09-07T02:14:09+00:00, source ip 91.204.17.80",
    "unusual cloud-storage access: user zara downloaded 97 files from a shared bucket at 2026-08-30T22:49:31+00:00, source ip 45.133.8.19",
    "unusual cloud-storage access: user kenji downloaded 211 files from a shared bucket at 2026-09-16T11:03:55+00:00, source ip 176.9.53.201",
    "unusual cloud-storage access: user amara downloaded 63 files from a shared bucket at 2026-08-20T06:27:18+00:00, source ip 23.88.145.6",
    "unusual cloud-storage access: user mateo downloaded 148 files from a shared bucket at 2026-09-10T14:55:46+00:00, source ip 199.21.6.144",
    "unusual cloud-storage access: user devon downloaded 76 files from a shared bucket at 2026-08-27T09:18:02+00:00, source ip 88.201.44.133",
    "unusual cloud-storage access: user ivan downloaded 192 files from a shared bucket at 2026-09-18T20:41:27+00:00, source ip 142.88.21.60",
    "unusual cloud-storage access: user priya downloaded 109 files from a shared bucket at 2026-08-23T03:36:50+00:00, source ip 203.15.77.9",
  ],
};

function pickSearchCategory(queryText) {
  const q = queryText.toLowerCase();
  if (q.includes("login") || q.includes("password") || q.includes("auth")) return "login";
  if (q.includes("traffic") || q.includes("outbound") || q.includes("transfer")) return "traffic";
  if (q.includes("process") || q.includes("spawn") || q.includes("executable")) return "process";
  if (q.includes("storage") || q.includes("cloud") || q.includes("bucket") || q.includes("file")) return "storage";
  return "login";
}

// Real benchmark numbers (docs/benchmark_results.csv), not fabricated. These
// never change at runtime, so they live outside the persisted/mutable state.
const mockBenchmarks = [
  { run_timestamp: "2026-09-26T05:12:15+00:00", metric: "hard_delete_latency", value: "64.75", unit: "ms", corpus_size: "6", k: "", notes: "" },
  { run_timestamp: "2026-09-26T05:12:22+00:00", metric: "cascading_erasure_latency", value: "4765.76", unit: "ms", corpus_size: "50", k: "", notes: "documents_deleted=50" },
  { run_timestamp: "2026-09-26T05:12:25+00:00", metric: "index_rebuild_cost", value: "10.72", unit: "ms", corpus_size: "100", k: "", notes: "" },
  { run_timestamp: "2026-09-26T05:12:41+00:00", metric: "index_rebuild_cost", value: "92.05", unit: "ms", corpus_size: "500", k: "", notes: "" },
  { run_timestamp: "2026-09-26T05:13:02+00:00", metric: "index_rebuild_cost", value: "108.36", unit: "ms", corpus_size: "1000", k: "", notes: "" },
  { run_timestamp: "2026-09-26T05:16:38+00:00", metric: "index_rebuild_cost", value: "870.89", unit: "ms", corpus_size: "5000", k: "", notes: "" },
  { run_timestamp: "2026-09-26T05:16:58+00:00", metric: "recall_at_k", value: "0.995", unit: "fraction", corpus_size: "4980", k: "10", notes: "num_queries=20, num_deleted=20" },
  { run_timestamp: "2026-09-27T06:40:09+00:00", metric: "hard_delete_latency", value: "67.92", unit: "ms", corpus_size: "54", k: "", notes: "" },
  { run_timestamp: "2026-09-27T06:40:14+00:00", metric: "cascading_erasure_latency", value: "4156.26", unit: "ms", corpus_size: "50", k: "", notes: "documents_deleted=50" },
  { run_timestamp: "2026-09-27T06:40:16+00:00", metric: "index_rebuild_cost", value: "9.52", unit: "ms", corpus_size: "100", k: "", notes: "" },
  { run_timestamp: "2026-09-27T06:40:31+00:00", metric: "index_rebuild_cost", value: "49.43", unit: "ms", corpus_size: "500", k: "", notes: "" },
  { run_timestamp: "2026-09-27T06:40:49+00:00", metric: "index_rebuild_cost", value: "120.94", unit: "ms", corpus_size: "1000", k: "", notes: "" },
  { run_timestamp: "2026-09-27T06:43:16+00:00", metric: "index_rebuild_cost", value: "333.18", unit: "ms", corpus_size: "5000", k: "", notes: "" },
  { run_timestamp: "2026-09-27T06:43:27+00:00", metric: "recall_at_k", value: "0.995", unit: "fraction", corpus_size: "4980", k: "10", notes: "num_queries=20, num_deleted=20" },
];

// ---------------------------------------------------------------------
// Mutable mock "database", persisted to sessionStorage across page loads
// ---------------------------------------------------------------------

function buildSeedState() {
  const subjects = [
    { subject_id: uuid(), display_name: "Meridian Health Systems", tenant_id: TENANT_1, consented: true, document_count: 24 },
    { subject_id: uuid(), display_name: "Northbridge Financial", tenant_id: TENANT_1, consented: true, document_count: 18 },
    { subject_id: uuid(), display_name: "Solace Retail Group", tenant_id: TENANT_1, consented: false, document_count: 12 },
    { subject_id: uuid(), display_name: "Arcfield Logistics", tenant_id: TENANT_2, consented: true, document_count: 20 },
    { subject_id: uuid(), display_name: "Bellwether Insurance", tenant_id: TENANT_2, consented: null, document_count: 15 },
    { subject_id: uuid(), display_name: "Cobalt Analytics", tenant_id: TENANT_2, consented: false, document_count: 9 },
    { subject_id: uuid(), display_name: "Vantage Property Group", tenant_id: TENANT_1, consented: true, document_count: 3 },
  ];

  const auditLog = [];
  const vantage = subjects.find((s) => s.display_name === "Vantage Property Group");
  const requestId = uuid();
  let previousHash = GENESIS_HASH;
  const baseTime = new Date("2026-09-20T10:15:00Z").getTime();

  for (let i = 0; i < 5; i++) {
    const hash = randomHex(64);
    auditLog.push({
      id: uuid(),
      deletion_request_id: requestId,
      document_id: uuid(),
      deleted_hash: hash,
      previous_hash: previousHash,
      signature: randomHex(140),
      signed_at: new Date(baseTime + i * 1500).toISOString().replace("T", " ").replace("Z", "+00:00"),
      valid: true,
    });
    previousHash = hash;
  }

  const deletionRequests = {
    [requestId]: {
      subject_id: vantage.subject_id,
      status: "completed",
      requested_at: new Date(baseTime - 60000).toISOString(),
      completed_at: new Date(baseTime + 5 * 1500).toISOString(),
    },
  };

  return { subjects, auditLog, deletionRequests };
}

function loadState() {
  const raw = sessionStorage.getItem(STORAGE_KEY);
  if (raw) {
    try {
      return JSON.parse(raw);
    } catch (e) {
      // fall through to a fresh seed if storage somehow got corrupted
    }
  }
  const seeded = buildSeedState();
  saveState(seeded);
  return seeded;
}

function saveState(state) {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

const STATE = loadState();

// ---------------------------------------------------------------------
// Mock network layer — same signatures as app.js's real getJSON/postJSON
// ---------------------------------------------------------------------

async function getJSON(path) {
  await sleep(250 + Math.random() * 200);

  if (path === "/subjects") {
    return STATE.subjects.map((s) => ({ ...s }));
  }

  if (path === "/audit-log") {
    return [...STATE.auditLog].reverse().map(({ valid, ...rest }) => rest);
  }

  let m = path.match(/^\/audit-log\/([^/]+)\/verify$/);
  if (m) {
    const entry = STATE.auditLog.find((e) => e.id === m[1]);
    return { entry_id: m[1], valid: entry ? entry.valid : false };
  }

  if (path === "/audit-log/verify-chain") {
    const firstBroken = STATE.auditLog.findIndex((e) => !e.valid);
    return { valid: firstBroken === -1 };
  }

  m = path.match(/^\/deletion-requests\/([^/]+)\/certificate$/);
  if (m) {
    const request = STATE.deletionRequests[m[1]];
    if (!request || request.status !== "completed") {
      throw new Error("Deletion request is not completed.");
    }
    const entries = STATE.auditLog.filter((e) => e.deletion_request_id === m[1]);
    return {
      deletion_request_id: m[1],
      subject_id: request.subject_id,
      requested_at: request.requested_at,
      completed_at: request.completed_at,
      audit_entries: entries.map((e) => ({
        document_id: e.document_id,
        hash: e.deleted_hash,
        previous_hash: e.previous_hash,
        signature: e.signature,
        signed_at: e.signed_at,
      })),
    };
  }

  if (path === "/benchmarks") {
    return mockBenchmarks;
  }

  throw new Error(`Mock backend: no handler for GET ${path}`);
}

async function postJSON(path, body) {
  await sleep(300 + Math.random() * 250);

  if (path === "/search") {
    const category = pickSearchCategory(body.query_text || "");
    const lines = SEARCH_RESULTS[category];
    let score = 0.6;
    return lines.map((content) => {
      const distance = +(1 - score).toFixed(3);
      score -= 0.004 + Math.random() * 0.006;
      return { id: uuid(), content, distance };
    });
  }

  if (path === "/deletion-requests") {
    const requestId = uuid();
    STATE.deletionRequests[requestId] = {
      subject_id: body.subject_id,
      status: "pending",
      requested_at: new Date().toISOString(),
      completed_at: null,
    };
    saveState(STATE);
    return {
      deletion_request_id: requestId,
      requested_at: STATE.deletionRequests[requestId].requested_at,
      due_at: null,
      status: "pending",
    };
  }

  let m = path.match(/^\/deletion-requests\/([^/]+)\/process$/);
  if (m) {
    const request = STATE.deletionRequests[m[1]];
    if (!request) throw new Error("Deletion request not found");

    const subject = STATE.subjects.find((s) => s.subject_id === request.subject_id);
    const docCount = subject ? subject.document_count : 0;

    let previousHash =
      STATE.auditLog.length > 0 ? STATE.auditLog[STATE.auditLog.length - 1].deleted_hash : GENESIS_HASH;

    for (let i = 0; i < docCount; i++) {
      const hash = randomHex(64);
      STATE.auditLog.push({
        id: uuid(),
        deletion_request_id: m[1],
        document_id: uuid(),
        deleted_hash: hash,
        previous_hash: previousHash,
        signature: randomHex(140),
        signed_at: new Date().toISOString().replace("T", " ").replace("Z", "+00:00"),
        valid: true,
      });
      previousHash = hash;
    }

    if (subject) subject.document_count = 0;
    request.status = "completed";
    request.completed_at = new Date().toISOString();
    saveState(STATE);

    return { deletion_request_id: m[1], status: "completed" };
  }

  m = path.match(/^\/audit-log\/([^/]+)\/corrupt-for-demo$/);
  if (m) {
    const entry = STATE.auditLog.find((e) => e.id === m[1]);
    if (!entry) throw new Error("Audit log entry not found");
    entry.valid = false;
    entry.deleted_hash = randomHex(64);
    saveState(STATE);
    return { entry_id: m[1], corrupted: true };
  }

  throw new Error(`Mock backend: no handler for POST ${path}`);
}

// ---------------------------------------------------------------------
// Shared DOM helpers (identical to app.js)
// ---------------------------------------------------------------------

function td(text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

function tdMono(text) {
  const cell = document.createElement("td");
  cell.className = "mono";
  cell.textContent = text;
  return cell;
}

function renderTable(container, columns, rows, rowRenderer) {
  container.innerHTML = "";

  if (rows.length === 0) {
    const empty = document.createElement("p");
    empty.className = "status-line";
    empty.textContent = "Nothing to show yet.";
    container.appendChild(empty);
    return;
  }

  const table = document.createElement("table");

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => tbody.appendChild(rowRenderer(row)));
  table.appendChild(tbody);

  container.appendChild(table);
}

function badge(text, kind) {
  const span = document.createElement("span");
  span.className = `badge ${kind}`;
  span.textContent = text;
  return span;
}
