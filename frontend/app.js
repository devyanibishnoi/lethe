const TENANT_LABELS = {
  "00000000-0000-0000-0000-000000000001": "Tenant 1",
  "00000000-0000-0000-0000-000000000002": "Tenant 2",
};

function tenantLabel(tenantId) {
  return TENANT_LABELS[tenantId] || tenantId;
}

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) {
    throw new Error((await res.json()).detail || res.statusText);
  }
  return res.json();
}

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    throw new Error((await res.json()).detail || res.statusText);
  }
  return res.json();
}

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
