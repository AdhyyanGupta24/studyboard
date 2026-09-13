const state = {
  csrf: "",
  user: null,
  editingId: null,
  board: "friends",
  tasks: [],
  subjects: []
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
}[c]));

function toast(message, error=false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.className = "toast", 2800);
}

async function api(path, options={}) {
  const opts = {...options, headers: {...(options.headers || {})}};
  if (opts.body && typeof opts.body !== "string") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  if (state.csrf && ["POST","PUT","PATCH","DELETE"].includes((opts.method || "GET").toUpperCase())) {
    opts.headers["X-CSRF-Token"] = state.csrf;
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  if (data.csrf_token) state.csrf = data.csrf_token;
  return data;
}

function showAuth() {
  $("authView").classList.remove("hidden");
  $("appView").classList.add("hidden");
}
function showApp() {
  $("authView").classList.add("hidden");
  $("appView").classList.remove("hidden");
  const h = new Date().getHours();
  $("greeting").textContent = h < 12 ? "Good morning." : h < 18 ? "Good afternoon." : "Good evening.";
  $("usernameLabel").textContent = state.user.username;
  $("scoreValue").textContent = state.user.score;
}

async function bootstrap() {
  try {
    const data = await api("/api/session");
    state.csrf = data.csrf_token;
    if (data.authenticated) {
      state.user = data.user;
      showApp();
      await refreshAll();
    } else {
      showAuth();
    }
  } catch (e) {
    toast(e.message, true);
  }
}

async function refreshAll() {
  await Promise.all([loadTasks(), loadFriends(), loadLeaderboard()]);
}

function taskQuery() {
  const p = new URLSearchParams();
  const fields = [
    ["subjectFilter","subject"], ["priorityFilter","priority"],
    ["completedFilter","completed"], ["dueFilter","due"], ["sortFilter","sort"]
  ];
  fields.forEach(([id,key]) => { if ($(id).value) p.set(key, $(id).value); });
  return p.toString();
}

async function loadTasks() {
  const data = await api(`/api/tasks?${taskQuery()}`);
  state.tasks = data.tasks;
  state.subjects = data.subjects;
  const select = $("subjectFilter");
  const current = select.value;
  select.innerHTML = `<option value="">All subjects</option>` +
    data.subjects.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  select.value = data.subjects.includes(current) ? current : "";
  renderTasks();
}

function formatDue(value) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString([], {dateStyle:"medium", timeStyle:"short"});
}
function dueClass(task) {
  if (task.completed) return "";
  return new Date(task.due_at) < new Date() ? "priority-high" : "";
}

function renderTasks() {
  const list = $("taskList");
  $("emptyState").classList.toggle("hidden", state.tasks.length > 0);
  list.innerHTML = state.tasks.map(task => `
    <article class="task ${task.completed ? "completed" : ""}">
      <button class="check ${task.completed ? "done" : ""}" data-action="complete" data-id="${task.id}" aria-label="${task.completed ? "Reopen" : "Complete"}">
        ${task.completed ? "✓" : ""}
      </button>
      <div>
        <div class="task-title">${esc(task.subject)}</div>
        <div class="task-desc">${esc(task.description)}</div>
        <div class="task-meta">
          <span class="chip ${dueClass(task)}">Due ${esc(formatDue(task.due_at))}</span>
          <span class="chip priority-${task.priority}">${esc(task.priority)}</span>
          <span class="chip">+${task.points} pts</span>
        </div>
      </div>
      <div class="task-actions">
        <button class="icon-btn" data-action="edit" data-id="${task.id}" title="Edit">✎</button>
        <button class="icon-btn" data-action="delete" data-id="${task.id}" title="Delete">⌫</button>
      </div>
    </article>
  `).join("");
}

async function toggleTask(id) {
  const task = state.tasks.find(t => t.id === id);
  try {
    const data = await api(`/api/tasks/${id}/complete`, {method:"POST", body:{completed:!task.completed}});
    state.user.score = data.score;
    $("scoreValue").textContent = data.score;
    toast(task.completed ? "Assignment reopened." : `Completed — +${task.points} points.`);
    await Promise.all([loadTasks(), loadLeaderboard()]);
  } catch (e) { toast(e.message, true); }
}

function openTask(task=null) {
  state.editingId = task?.id || null;
  $("modalTitle").textContent = task ? "Edit assignment" : "Add assignment";
  $("taskId").value = task?.id || "";
  $("taskSubject").value = task?.subject || "";
  $("taskDescription").value = task?.description || "";
  $("taskDue").value = task ? task.due_at.slice(0,16) : defaultDue();
  $("taskPriority").value = task?.priority || "medium";
  $("taskPoints").value = task?.points ?? "";
  $("taskDialog").showModal();
}
function defaultDue() {
  const d = new Date(Date.now() + 86400000);
  d.setMinutes(Math.ceil(d.getMinutes()/30)*30, 0, 0);
  const pad = n => String(n).padStart(2,"0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function saveTask(e) {
  e.preventDefault();
  const body = {
    subject:$("taskSubject").value,
    description:$("taskDescription").value,
    due_at:$("taskDue").value,
    priority:$("taskPriority").value,
    points:$("taskPoints").value || undefined
  };
  try {
    if (state.editingId) {
      await api(`/api/tasks/${state.editingId}`, {method:"PUT", body});
      toast("Assignment updated.");
    } else {
      await api("/api/tasks", {method:"POST", body});
      toast("Assignment added.");
    }
    $("taskDialog").close();
    await loadTasks();
  } catch (e) { toast(e.message, true); }
}

async function deleteTask(id) {
  if (!confirm("Delete this assignment?")) return;
  try {
    const data = await api(`/api/tasks/${id}`, {method:"DELETE"});
    state.user.score = data.score;
    $("scoreValue").textContent = data.score;
    toast("Assignment deleted.");
    await Promise.all([loadTasks(), loadLeaderboard()]);
  } catch (e) { toast(e.message, true); }
}

async function loadFriends() {
  const data = await api("/api/friends");
  $("incomingRequests").innerHTML = data.incoming.length
    ? data.incoming.map(p => `
      <div class="person"><div class="person-main"><div class="person-name">${esc(p.username)}</div><div class="person-score">${p.score} points</div></div>
      <div><button class="primary" data-request="accept" data-id="${p.id}">Accept</button>
      <button class="ghost" data-request="decline" data-id="${p.id}">Decline</button></div></div>`).join("")
    : `<span class="hint">No pending requests.</span>`;

  $("friendsList").innerHTML = data.friends.length
    ? data.friends.map(p => `<div class="person"><div class="person-main"><div class="person-name">${esc(p.username)}</div><div class="person-score">${p.score} points</div></div></div>`).join("")
    : `<span class="hint">Connect with classmates to build your friends leaderboard.</span>`;
}

let friendTimer;
$("friendSearch").addEventListener("input", () => {
  clearTimeout(friendTimer);
  friendTimer = setTimeout(searchFriends, 250);
});
async function searchFriends() {
  const q = $("friendSearch").value.trim();
  if (q.length < 2) { $("friendResults").innerHTML = ""; return; }
  try {
    const data = await api(`/api/friends/search?q=${encodeURIComponent(q)}`);
    $("friendResults").innerHTML = data.users.length
      ? data.users.map(p => `<div class="person"><div class="person-main"><div class="person-name">${esc(p.username)}</div><div class="person-score">${p.score} points</div></div><button class="ghost" data-connect="${p.id}">Connect</button></div>`).join("")
      : `<span class="hint">No users found.</span>`;
  } catch (e) { toast(e.message, true); }
}

async function connect(id) {
  try {
    await api(`/api/friends/request/${id}`, {method:"POST", body:{}});
    toast("Connection request sent.");
    await loadFriends();
    await searchFriends();
  } catch (e) { toast(e.message, true); }
}

async function respondRequest(id, action) {
  try {
    await api(`/api/friends/request/${id}/respond`, {method:"POST", body:{action}});
    toast(action === "accept" ? "Connection accepted." : "Request declined.");
    await Promise.all([loadFriends(), loadLeaderboard()]);
  } catch (e) { toast(e.message, true); }
}

async function loadLeaderboard() {
  const data = await api("/api/leaderboard");
  const rows = data[state.board] || [];
  $("leaderboardList").innerHTML = rows.length
    ? rows.map((p,i) => `<div class="rank-row ${p.id === state.user.id ? "me" : ""}">
        <span class="rank">${i+1}</span><span class="rank-name">${esc(p.username)}</span><span class="rank-score">${p.score}</span>
      </div>`).join("")
    : `<span class="hint">No connected classmates yet.</span>`;
}

document.querySelectorAll("[data-auth-tab]").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll("[data-auth-tab]").forEach(x => x.classList.remove("active"));
  btn.classList.add("active");
  const login = btn.dataset.authTab === "login";
  $("loginForm").classList.toggle("hidden", !login);
  $("registerForm").classList.toggle("hidden", login);
}));

$("loginForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    const data = await api("/api/login", {method:"POST", body:{
      username:$("loginUsername").value, password:$("loginPassword").value
    }});
    state.user = data.user;
    showApp();
    await refreshAll();
  } catch (e) { toast(e.message, true); }
});

$("registerForm").addEventListener("submit", async e => {
  e.preventDefault();
  try {
    await api("/api/register", {method:"POST", body:{
      username:$("registerUsername").value, password:$("registerPassword").value
    }});
    toast("Account created. Sign in to continue.");
    document.querySelector('[data-auth-tab="login"]').click();
    $("loginUsername").value = $("registerUsername").value;
    $("loginPassword").value = "";
  } catch (e) { toast(e.message, true); }
});

$("logoutBtn").addEventListener("click", async () => {
  try { await api("/api/logout", {method:"POST", body:{}}); } catch {}
  state.user = null;
  state.csrf = "";
  showAuth();
});

$("addTaskBtn").addEventListener("click", () => openTask());
$("closeModal").addEventListener("click", () => $("taskDialog").close());
$("cancelModal").addEventListener("click", () => $("taskDialog").close());
$("taskForm").addEventListener("submit", saveTask);

["subjectFilter","priorityFilter","completedFilter","dueFilter","sortFilter"].forEach(id =>
  $(id).addEventListener("change", loadTasks)
);

$("taskList").addEventListener("click", e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const id = Number(btn.dataset.id);
  const task = state.tasks.find(t => t.id === id);
  if (btn.dataset.action === "complete") toggleTask(id);
  if (btn.dataset.action === "edit") openTask(task);
  if (btn.dataset.action === "delete") deleteTask(id);
});

$("friendResults").addEventListener("click", e => {
  const btn = e.target.closest("[data-connect]");
  if (btn) connect(Number(btn.dataset.connect));
});
$("incomingRequests").addEventListener("click", e => {
  const btn = e.target.closest("[data-request]");
  if (btn) respondRequest(Number(btn.dataset.id), btn.dataset.request);
});

document.querySelectorAll("[data-board]").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll("[data-board]").forEach(x => x.classList.remove("active"));
  btn.classList.add("active");
  state.board = btn.dataset.board;
  loadLeaderboard();
}));

bootstrap();
