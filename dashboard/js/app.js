/* Agent Mesh: the Claude Design "Agent Dashboard" bound to dashboard/data/*.json.
   Views: Canvas, Graph, Matrix, Sessions, Usage; Overview/selection panel; Recent runs drawer.
   Vanilla JS, no build. Everything rendered from the collector's JSON every 30 s. */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const LS = 'cosdash:';
const WIN_LABEL = { d1: 'today', d7: 'last 7 days', d30: 'last 30 days' };
const WIN_SHORT = { d1: 'today', d7: '7d', d30: '30d' };
const LOCAL = new Set(['This Mac', 'iPhone']);
const EXPECT_LABEL = { watcher: 'hourly', 'brief-8am': 'daily', 'brief-1pm': 'daily', 'brief-6pm': 'daily', optimizer: 'weekly' };
const CTX_MONO = { skill: 'SK', agents: 'AG', folders: 'FD', connector: 'CN', email: 'EM', internet: 'WW', github: 'GH', plugins: 'PL', calendar: 'CL', memory: 'ME', browser: 'BR', skills: 'SK', connectors: 'CN' };

const saved = k => { try { return JSON.parse(localStorage.getItem(LS + k)); } catch (e) { return null; } };
const S = {
  view: (location.hash.slice(1) || saved('view') || 'canvas'), sel: null, hov: null, q: '', drawer: false,
  collapsed: false, secs: { team: true, sess: false, links: true, items: true }, hops: 1, win: saved('win') || 'd1',
  hidden: saved('hidden') || {}, pulses: true, ws: saved('ws') || '', sort: 'recent', invFilter: 'all', open: saved('open') || {}, regType: '', regStatus: '', note: saved('note') || '',
};
let D = null, loadErr = null, REMOTE = null;

/* ---------- data ---------- */
async function load() {
  try {
    const get = n => fetch('data/' + n + '.json', { cache: 'no-store' }).then(r => { if (!r.ok) throw new Error(n + '.json ' + r.status); if (n === 'stats' && r.headers.get('x-agents-source')) REMOTE = { src: r.headers.get('x-agents-source'), mac: +r.headers.get('x-agents-mac-at'), cloud: +r.headers.get('x-agents-cloud-at') }; return r.json(); });
    const opt = n => get(n).catch(() => null);
    const [g, s, st, inv, hl, gh, mem, reg, vault] = await Promise.all([get('graph'), get('sessions'), get('stats'), opt('inventory'), opt('health'), opt('github'), opt('memory'), opt('registry'), opt('vault')]);
    D = { g, s: s.sessions, st, inv: inv ? inv.groups : [], health: hl ? hl.signals : [], gh, mem: mem ? mem.stores : [], reg: Array.isArray(reg) ? reg : [], vault: vault || { notes: [] } }; loadErr = null;
  } catch (e) { loadErr = e; }
  render();
}

/* ---------- helpers ---------- */
const money = (v, d = 2) => '$' + (v || 0).toFixed(d);
const hm = t => { const d = new Date(t * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); };
const since = t => {
  const d = new Date(t * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return hm(t);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
};
const ago = t => { if (!t) return 'never'; const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? 'just now' : m < 60 ? m + ' min ago' : m < 1440 ? Math.round(m / 60) + ' h ago' : Math.round(m / 1440) + ' d ago'; };
const dur = ms => ms == null ? '' : ms < 1000 ? ms + 'ms' : ms < 60000 ? (ms / 1000).toFixed(1) + 's' : Math.round(ms / 60000) + 'm';
const ktok = n => n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : n >= 1e3 ? Math.round(n / 1e3) + 'k' : String(n);
const idsafe = s => s.replace(/[^A-Za-z0-9_-]/g, '-');
const winStart = () => { const now = Date.now() / 1000; if (S.win === 'd1') { const d = new Date(); d.setHours(0, 0, 0, 0); return d / 1000; } return now - (S.win === 'd7' ? 7 : 30) * 86400; };
const mono = a => a.id === 'cos' ? 'C' : a.kind === 'live' ? (a.name.match(/[A-Za-z0-9]+/g) || ['?']).slice(0, 2).map(w => w[0]).join('').toUpperCase() : a.kind === 'routine' ? a.name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() : (a.name.split(/[\s-]/).length > 1 ? a.name.split(/[\s-]/).map(w => w[0]).join('').slice(0, 2).toUpperCase() : a.name.slice(0, 2).replace(/^./, c => c.toUpperCase()));
const chipA = a => a.id === 'cos' ? 'background:var(--color-accent);color:var(--color-bg)' : a.kind === 'live' ? 'background:var(--color-bg);color:var(--color-accent-200);box-shadow:inset 0 0 0 1px var(--color-accent-600)' : 'background:var(--color-accent-800);color:var(--color-accent-100)';
const selAttr = (k, id) => `data-act="sel" data-k="${k}" data-id="${esc(id)}"`;
const ctxWindow = m => /haiku/.test(m || '') ? 200000 : 1000000;

/* ---------- model: everything derived for one render ---------- */
function model() {
  const { g, s: sessions, st } = D;
  const w = S.win, wN = 'w' + w.slice(1), start = winStart(), now = Date.now() / 1000;
  const A = g.agents, R = g.resources;
  const aIdx = new Map(A.map((a, i) => [a.id, i])), rIdx = new Map(R.map((r, i) => [r.id, i]));
  const wi = { d1: 0, d7: 1, d30: 2 }[w];
  const cnt = e => S.ws ? ((e.ws || {})[S.ws] || [0, 0, 0, 0, 0, 0]) : [e.d1, e.d7, e.d30, e.w1, e.w7, e.w30];
  const all = g.edges.filter(e => aIdx.has(e.a) && rIdx.has(e.r) && cnt(e)[wi] > 0).map(e => { const c = cnt(e); return {
    k: e.a + '>' + e.r, a: aIdx.get(e.a), r: rIdx.get(e.r), perm: c[wi + 3] > 0 ? 'write' : 'read', calls: c[wi],
    writes: c[wi + 3], items: e.items, failed: e.failed, last: e.last, declared: e.declared,
  }; });
  const edges = all.filter(e => !S.hidden[e.k]);
  // a routine run touches every resource its prompt declares: count runs, not links
  const callsA = i => A[i].kind === 'routine' ? (S.ws && S.ws !== 'cos' ? 0 : (A[i].health || {})['r' + w.slice(1)] || 0) : edges.filter(e => e.a === i).reduce((s, e) => s + e.calls, 0);
  const callsR = i => edges.filter(e => e.r === i).reduce((s, e) => s + e.calls, 0);
  const runs = g.runs;
  const recent = t => now - t < 180;
  const activeA = new Set(runs.filter(r => recent(r.t)).map(r => r.a));
  const runningSess = sessions.filter(x => x.status === 'running');
  if (runningSess.length) activeA.add('cos');
  for (const x of runningSess) activeA.add('live:' + x.id);
  const liveA = i => activeA.has(A[i].id);
  const fKey = 'f' + w.slice(1);
  const flagged = new Set((D.health || []).filter(x => x.level !== 'info' && x.ref).map(x => x.ref));
  const needsLook = i => {
    const a = A[i], h = a.health || {};
    if (flagged.has(a.id)) return true;
    if (a.kind === 'routine') return h.stale || h.last_st === 'failed';
    const c = callsA(i); return c >= 8 && h[fKey] / c > 0.25;
  };
  const sessOfA = i => {
    const a = A[i];
    if (a.id === 'cos') return sessions;
    if (a.kind === 'live') return sessions.filter(x => x.id === a.session);
    if (a.kind === 'subagent') { const t = a.id.slice(4); return sessions.filter(x => x.subagents && x.subagents[t]); }
    return [];
  };
  const inWin = x => x.last_t >= start && (!S.ws || x.ws === S.ws);
  return { g, st, sessions, A, R, aIdx, rIdx, all, edges, callsA, callsR, liveA, needsLook, sessOfA, inWin, start, now, runningSess, activeA };
}

/* ---------- render ---------- */
function render() {
  for (const el of document.querySelectorAll('#views input')) el.checked = el.value === S.view;
  for (const el of document.querySelectorAll('#wins input')) el.checked = el.value === S.win;
  $('#collapseBtn').textContent = S.collapsed ? 'Expand all' : 'Collapse all';
  $('#collapseBtn').style.visibility = ['canvas', 'graph', 'matrix'].includes(S.view) ? 'visible' : 'hidden';
  document.body.classList.toggle('full', S.view === 'memory');
  if (!D) {
    $('#stage').innerHTML = `<div class="empty">${loadErr ? `<p>No data yet (${esc(loadErr.message)}).</p>` : '<p>Loading…</p>'}
      <p>Start the collector and server with <code>dashboard/serve.sh</code>, or run <code>collect/collect.py run</code> once.</p></div>`;
    $('#panel').innerHTML = ''; $('#drawer').innerHTML = ''; return;
  }
  const M = model();
  $('#running').textContent = (M.st.running || 0) + ' running · ' + (M.st.open || 0) + ' open';
  const wsSel = $('#ws');
  if (wsSel.options.length !== M.g.workspaces.length + 1) wsSel.innerHTML = '<option value="">All spaces</option>' + M.g.workspaces.map(w => `<option value="${esc(w)}">${esc(w)}</option>`).join('');
  wsSel.value = S.ws;
  if (REMOTE) {
    const macOff = REMOTE.src === 'cloud';
    $('#age').textContent = macOff ? (REMOTE.mac ? 'Mac off since ' + since(REMOTE.mac) : 'Mac not seen yet') + ' · cloud ' + ago(REMOTE.cloud) : 'Mac ' + ago(REMOTE.mac);
    $('#age').title = 'Mac data ' + (REMOTE.mac ? new Date(REMOTE.mac * 1000).toLocaleString() : 'never') + ' · GitHub data ' + (REMOTE.cloud ? new Date(REMOTE.cloud * 1000).toLocaleString() : 'never') + ' · showing ' + REMOTE.src;
  } else {
    $('#age').textContent = ago(M.g.generated_at);
    $('#age').title = new Date(M.g.generated_at * 1000).toLocaleString();
  }
  const stage = $('#stage');
  const sx = stage.scrollLeft, sy = stage.scrollTop;
  const W = stage.clientWidth, H = stage.clientHeight;
  const views = { canvas, graph, matrix, sessions: sessionsView, usage, inventory, registry, memory: memoryView };
  stage.innerHTML = (views[S.view] || canvas)(M, W, H);
  stage.scrollLeft = sx; stage.scrollTop = sy;
  $('#panel').innerHTML = panel(M);
  $('#drawer').innerHTML = drawer(M);
  $('#drawer').style.height = (S.drawer ? 220 : 36) + 'px';
}

/* selection/lighting shared by canvas, graph, matrix */
function lighting(M) {
  const { A, R, edges } = M;
  const sel = S.sel && S.sel.kind !== 's' ? S.sel : (S.view === 'graph' ? S.hov : null);
  const selI = sel ? (sel.kind === 'a' ? M.aIdx.get(sel.id) : M.rIdx.get(sel.id)) : null;
  const noChat = i => !(S.view === 'graph' && A[i].kind === 'live');
  const visA = S.collapsed ? [0] : A.map((_, i) => i).filter(noChat);
  const vedges = S.collapsed ? R.map((r, ri) => { const gr = edges.filter(e => e.r === ri); return gr.length ? { k: 'c>' + r.id, a: 0, r: ri, perm: gr.some(e => e.perm === 'write') ? 'write' : 'read', calls: gr.reduce((s, e) => s + e.calls, 0) } : null; }).filter(Boolean) : edges.filter(e => noChat(e.a));
  const ql = S.q.trim().toLowerCase();
  const matchA = i => !ql || A[i].name.toLowerCase().includes(ql) || A[i].sub.toLowerCase().includes(ql);
  const matchR = i => !ql || R[i].name.toLowerCase().includes(ql) || R[i].sub.toLowerCase().includes(ql);
  const cosOpen = sel && sel.kind === 'a' && selI === 0;
  const conA = new Set(), conR = new Set();
  if (sel) for (const e of vedges) { if (sel.kind === 'a' && (e.a === selI || cosOpen)) conR.add(e.r); if (sel.kind === 'r' && e.r === selI) conA.add(e.a); }
  const two = S.view === 'graph' && S.hops === 2 && sel && !cosOpen;
  const hop2A = new Set(), hop2R = new Set();
  if (two) for (const e of vedges) { if (sel.kind === 'a' && conR.has(e.r)) hop2A.add(e.a); if (sel.kind === 'r' && conA.has(e.a)) hop2R.add(e.r); }
  const litA = i => !sel ? true : (sel.kind === 'a' ? (selI === i || cosOpen || hop2A.has(i)) : conA.has(i));
  const litR = i => !sel ? true : (sel.kind === 'r' ? (selI === i || hop2R.has(i)) : conR.has(i));
  const opA = i => (matchA(i) && litA(i)) ? 1 : 0.18, opR = i => (matchR(i) && litR(i)) ? 1 : 0.18;
  const edgeOn = e => matchA(e.a) && matchR(e.r) && (!sel || (sel.kind === 'a' ? (e.a === selI || cosOpen || (two && conR.has(e.r) && hop2A.has(e.a))) : (e.r === selI || (two && conA.has(e.a) && hop2R.has(e.r)))));
  const edgeFar = e => two && !!sel && (sel.kind === 'a' ? e.a !== selI : e.r !== selI);
  const isSelA = i => sel && sel.kind === 'a' && selI === i, isSelR = i => sel && sel.kind === 'r' && selI === i;
  const pulses = list => S.pulses ? list.filter(edgeOn).slice(0, 60).map((e, n) => ({ key: idsafe(e.k), dur: (2.6 + ((n * 7) % 9) * 0.35).toFixed(2) + 's', begin: '-' + ((n * 1.3) % 5).toFixed(2) + 's' })) : [];
  return { sel, selI, visA, vedges, matchA, matchR, cosOpen, opA, opR, edgeOn, edgeFar, isSelA, isSelR, pulses };
}
const SEL_SHADOW = '0 0 0 1px var(--color-accent),0 0 18px var(--color-accent-800)';
const pulseSvg = (ps, prefix, r) => ps.map(p => `<circle r="${r}" fill="var(--color-accent-300)"><animateMotion dur="${p.dur}" begin="${p.begin}" repeatCount="indefinite"><mpath href="#${prefix}-${p.key}"/></animateMotion></circle>`).join('');

/* ---------- Canvas ---------- */
const MCP_RES = n => { const l = n.toLowerCase(); return /gmail/.test(l) ? 'email' : /calendar/.test(l) ? 'calendar' : /github/.test(l) ? 'github' : /firecrawl/.test(l) ? 'internet' : /cmux|chrome|browser|computer/.test(l) ? 'browser' : 'connectors'; };
const groupOpen = a => S.collapsed ? false : (S.open[a.id] ?? (a.kind === 'live' && /running/.test(a.cadence || '')));
/* a chat's children: what that chat used (whole session, from sessions.json) */
function chatChildren(M, a) {
  const s = M.sessions.find(x => x.id === a.session); if (!s) return [];
  const kids = [];
  for (const [n, c] of Object.entries(s.subagents || {})) kids.push({ name: n, kind: 'subagent', n: c, r: 'agents', sel: ['a', 'sub:' + n] });
  for (const [n, c] of Object.entries(s.skills || {})) kids.push({ name: n, kind: 'skill', n: c, r: 'skills', sel: ['r', 'skills'] });
  for (const [n, c] of Object.entries(s.mcp || {})) kids.push({ name: n, kind: 'connector', n: c, r: MCP_RES(n), sel: ['r', MCP_RES(n)] });
  return kids.sort((x, y) => y.n - x.n);
}
function canvas(M, W, H) {
  const L = lighting(M), { A, R } = M;
  const pitch = 56, top = 44, AX = 80, AW = 190, SUBX = 104, RX = Math.max(620, W - 270);
  const mid = (SUBX + AW + RX) / 2;
  // rows: a top-level group (COS or an open chat) followed by its children when open
  const tops = A.map((a, i) => i).filter(i => i === 0 || A[i].kind === 'live');
  const rows = [], rowOfA = {}, parentOfA = {};
  for (const i of tops) {
    const a = A[i], open = groupOpen(a);
    rowOfA[i] = rows.length; rows.push({ t: 'a', i, open });
    const kids = i === 0 ? A.map((x, j) => j > 0 && x.kind !== 'live' ? { t: 'a', i: j, parent: i } : null).filter(Boolean)
      : chatChildren(M, a).map(k => ({ t: 'c', parent: i, ...k, ri: M.rIdx.get(k.r) }));
    rows[rows.length - 1].kids = kids.length;
    for (const k of kids) { if (k.t === 'a') parentOfA[k.i] = i; if (open) { if (k.t === 'a') rowOfA[k.i] = rows.length; rows.push(k); } }
  }
  const nRows = Math.max(rows.length, R.length);
  const CH = Math.max(H, top + nRows * pitch + 16), CW = Math.max(W, RX + 220);
  const yA = i => top + (rowOfA[i] ?? rowOfA[parentOfA[i]] ?? 0) * pitch + 22;
  const yR = i => top + i * pitch + 22;
  // wires: an agent's edges; a hidden child's edges start from its group box
  const wires = M.edges.map(e => {
    const y1 = yA(e.a), y2 = yR(e.r), on = L.edgeOn(e), x1 = SUBX + AW;
    return `<path id="w-${idsafe(e.k)}" d="M${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${RX} ${y2}" fill="none" stroke="${e.perm === 'write' ? 'var(--color-accent-500)' : 'var(--color-neutral-700)'}" stroke-width="${e.perm === 'write' ? 1.25 : 1}" stroke-dasharray="${e.declared ? '3 4' : 'none'}" opacity="${on ? (L.sel ? 0.9 : 0.5) : 0.06}"/>`;
  }).join('');
  const kidWires = rows.map((r, n) => r.t !== 'c' || r.ri == null ? '' : (() => {
    const y1 = top + n * pitch + 22, y2 = yR(r.ri), on = L.opA(r.parent) === 1 && L.matchR(r.ri);
    return `<path d="M${SUBX + AW} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${RX} ${y2}" fill="none" stroke="var(--color-neutral-700)" stroke-width="1" opacity="${on ? 0.35 : 0.05}"/>`;
  })()).join('');
  const elbows = rows.map((r, n) => {
    if (r.parent == null) return '';
    const p = rowOfA[r.parent], x0 = AX + 11, y0 = top + p * pitch + 44, y1 = top + n * pitch + 22;
    const lit = L.opA(r.parent) === 1;
    return `<path d="M${x0} ${y0} L${x0} ${y1 - 8} Q${x0} ${y1} ${x0 + 8} ${y1} L${SUBX} ${y1}" fill="none" stroke="${lit && L.isSelA(r.parent) ? 'var(--color-accent-500)' : 'var(--color-neutral-700)'}" stroke-width="1" opacity="${lit ? 0.6 : 0.1}"/>`;
  }).join('');
  const chip = (mono, style) => `<span class="chip" style="${style}">${esc(mono)}</span>`;
  const boxes = rows.map((r, n) => {
    const y = top + n * pitch;
    if (r.t === 'a') {
      const a = A[r.i], i = r.i, isTop = r.parent == null;
      const sub = a.where + (a.cadence ? ' · ' + a.cadence : '') + (isTop && !r.open && r.kids ? ' · ' + r.kids + ' under it' : '');
      const dot = M.needsLook(i) ? 'var(--color-accent-300)' : M.liveA(i) ? 'var(--color-accent)' : 'transparent';
      return `<div class="nd nd-agent" ${selAttr('a', a.id)} title="${esc(a.sub)}" style="left:${isTop ? AX : SUBX}px;top:${y}px;width:${isTop ? AW + (SUBX - AX) : AW}px;opacity:${L.opA(i)};box-shadow:${L.isSelA(i) ? SEL_SHADOW : 'var(--shadow-sm)'}">
        ${chip(mono(a), chipA(a))}
        <span class="nd-text"><span class="nd-name">${esc(a.name)}</span><span class="nd-sub">${esc(sub)}</span></span>
        <span class="nd-dot" style="background:${dot}" title="${M.needsLook(i) ? 'needs a look' : M.liveA(i) ? 'active now' : ''}"></span>
        <span class="badge" title="${a.kind === 'routine' ? 'runs' : 'calls'} ${WIN_LABEL[S.win]}">${M.callsA(i)}</span>
        ${isTop && r.kids ? `<span class="nd-toggle" data-act="tog" data-id="${esc(a.id)}" title="${r.open ? 'Collapse' : 'Expand'}"><b>${r.open ? '▾' : '▸'}</b></span>` : ''}
      </div>`;
    }
    const op = L.opA(r.parent);
    return `<div class="nd nd-agent" data-act="sel" data-k="${r.sel[0]}" data-id="${esc(r.sel[1])}" title="${esc(r.kind + ' used by this chat')}" style="left:${SUBX}px;top:${y}px;width:${AW}px;opacity:${op};box-shadow:var(--shadow-sm)">
      ${chip((r.name.match(/[A-Za-z0-9]+/g) || ['?']).slice(0, 2).map(w => w[0]).join('').toUpperCase(), 'background:var(--color-neutral-800);color:var(--color-neutral-200)')}
      <span class="nd-text"><span class="nd-name">${esc(r.name)}</span><span class="nd-sub">${esc(r.kind)}</span></span>
      <span class="badge badge-res" title="uses in this chat">${r.n}</span></div>`;
  }).join('');
  const res = R.map((r, i) => `<div class="nd nd-res" ${selAttr('r', r.id)} title="${esc(r.desc)}" style="left:${RX}px;top:${top + i * pitch}px;opacity:${L.opR(i)};box-shadow:${L.isSelR(i) ? SEL_SHADOW : 'none'}">
      <span class="chip chip-res">${esc(r.mono)}</span>
      <span class="nd-text"><span class="nd-name">${esc(r.name)}</span><span class="nd-sub">${esc(r.where + ' · ' + r.sub)}</span></span><span class="badge badge-res" title="calls ${WIN_LABEL[S.win]}">${M.callsR(i)}</span></div>`).join('');
  return `<div class="stage-inner" style="width:${CW}px;height:${CH}px" data-act="clear">
    <svg class="wires" width="${CW}" height="${CH}">${wires}${kidWires}${elbows}${pulseSvg(L.pulses(M.edges), 'w', 3)}</svg>
    <div class="lane-label" style="left:80px">Agents</div>
    <div class="lane-label" style="left:${RX}px;width:250px;display:flex;justify-content:space-between"><span>Resources</span><span style="display:flex;gap:10px;letter-spacing:0;text-transform:none"><span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:2px;background:var(--color-accent-500)"></span>write</span><span style="display:flex;align-items:center;gap:4px"><span style="width:10px;height:1px;background:var(--color-neutral-600)"></span>read</span><span style="display:flex;align-items:center;gap:4px" title="Routine links are what the prompt declares, not observed calls"><span style="width:10px;height:0;border-top:1px dashed var(--color-neutral-500)"></span>declared</span></span></div>
    ${boxes}${res}
    ${M.edges.length ? '' : `<div class="lane-label" style="left:${mid - 120}px;top:${top + 120}px;width:240px;text-align:center;text-transform:none;letter-spacing:0;font-size:12px">No calls ${WIN_LABEL[S.win]}. Try 7 days.</div>`}
  </div>`;
}

/* ---------- Graph (clusters by where things live) ---------- */
function clusters(M, W, H) {
  const { A, R } = M;
  // COS lives on This Mac: that halo sits in the centre around COS, every other place rings it
  const home = A[0].where;
  const names = [...new Set([...A.slice(1).map(a => a.where), ...R.map(r => r.where)])].filter(n => n !== home);
  const cx = W / 2, cy = H / 2 + 10, cap = Math.min(W, H) * 0.19;
  const pos = { a: { 0: { x: cx, y: cy } }, r: {} };
  const out = [home, ...names].map((name, k) => {
    const members = [...A.map((a, i) => i > 0 && a.kind !== 'live' && a.where === name ? { kind: 'a', i } : null), ...R.map((r, i) => r.where === name ? { kind: 'r', i } : null)].filter(Boolean);
    const centre = name === home;
    const ang = -Math.PI / 2 + (k - 1) / names.length * Math.PI * 2;
    const r = centre ? Math.min(60 + members.length * 10, cap) : Math.min(30 + members.length * 12, 90);
    const c = { name, members, r, local: LOCAL.has(name),
      x: centre ? cx : Math.max(r + 40, Math.min(W - r - 40, cx + Math.cos(ang) * W * 0.38)),
      y: centre ? cy : Math.max(r + 44, Math.min(H - r - 28, cy + Math.sin(ang) * H * 0.41)) };
    members.forEach((m, j) => {
      const a = -Math.PI / 2 + j / members.length * Math.PI * 2, rr = members.length === 1 ? 0 : c.r - 24;
      pos[m.kind][m.i] = { x: c.x + Math.cos(a) * rr, y: c.y + Math.sin(a) * rr, above: members.length > 2 && (Math.sin(a) < -0.1 || (Math.abs(Math.cos(a)) > 0.3 && j % 2 === 1)) };
    });
    return c;
  });
  return { out, pos };
}
function graph(M, W, H) {
  const L = lighting(M), { A, R, edges } = M;
  H = Math.max(H, 520); W = Math.max(W, 760);
  const C = clusters(M, W, H), gp = (k, i) => C.pos[k][i] || { x: W / 2, y: H / 2 };
  const maxAC = Math.max(1, ...A.map((_, i) => M.callsA(i))), maxRC = Math.max(1, ...R.map((_, i) => M.callsR(i)));
  const hotR = new Set(edges.filter(e => M.liveA(e.a)).map(e => e.r));
  const overPriv = i => edges.filter(e => e.a === i && e.perm === 'write').length >= 3;
  const orphan = i => edges.filter(e => e.r === i).length === 0;
  const crosses = e => LOCAL.has(A[e.a].where) !== LOCAL.has(R[e.r].where);
  const halos = C.out.map(c => `<circle cx="${c.x}" cy="${c.y}" r="${c.r}" fill="var(--color-accent-900)" opacity="0.35"/><circle cx="${c.x}" cy="${c.y}" r="${c.r}" fill="none" stroke="var(--color-neutral-800)"/>`).join('');
  const wires = L.vedges.map(e => {
    const a = gp('a', e.a), b = gp('r', e.r), x = crosses(e), on = L.edgeOn(e);
    return `<path id="g-${idsafe(e.k)}" d="M${a.x} ${a.y} L${b.x} ${b.y}" fill="none" stroke="${x ? 'var(--color-accent-300)' : (e.perm === 'write' ? 'var(--color-accent-500)' : 'var(--color-neutral-700)')}" stroke-width="${e.perm === 'write' ? 1.2 : 0.8}" stroke-dasharray="${x ? '4 4' : 'none'}" opacity="${on ? (L.edgeFar(e) ? 0.4 : (L.sel ? 0.9 : 0.5)) : 0.05}"/>`;
  }).join('');
  const node = (k, i, n) => `<div class="gn" ${selAttr(k, n.id)} data-hov="${k}:${esc(n.id)}" style="left:${n.x}px;top:${n.y}px;opacity:${n.op};flex-direction:${n.above ? 'column-reverse' : 'column'}">
      <span class="dot" style="width:${n.r}px;height:${n.r}px;background:${n.fill};box-shadow:${n.ring},${n.glow};border:1px solid ${n.stroke}"></span>
      <span class="lbl" style="color:${n.lc}">${esc(n.name)}</span></div>`;
  const tips = {};
  const nodes = [...L.visA.map(i => {
    const a = A[i], p = gp('a', i), live = M.liveA(i), c = M.callsA(i);
    const size = i === 0 ? (S.collapsed ? 44 : 34) : 14 + Math.round(c / maxAC * 18);
    tips['a:' + a.id] = { x: p.x, y: p.y - size / 2 - 30, text: (S.collapsed && i === 0 ? M.edges.reduce((s, e) => s + e.calls, 0) : c) + ' calls ' + WIN_SHORT[S.win] + ' · ' + (live ? 'active now' : 'idle') + (overPriv(i) ? ' · writes to 3+' : '') + (M.needsLook(i) ? ' · needs a look' : '') };
    return node('a', i, { id: a.id, name: a.name, x: p.x, y: p.y, above: p.above, r: size, op: L.opA(i), fill: i === 0 ? 'var(--color-accent-700)' : 'var(--color-accent-900)', stroke: L.isSelA(i) ? 'var(--color-accent-300)' : 'var(--color-accent-600)', glow: live ? '0 0 18px var(--color-accent)' : (L.isSelA(i) ? '0 0 18px var(--color-accent-700)' : '0 0 0 0 transparent'), ring: overPriv(i) ? '0 0 0 3px var(--color-bg),0 0 0 4px var(--color-accent-300)' : '0 0 0 0 transparent', lc: 'var(--color-text)' });
  }), ...R.map((r, i) => {
    const p = gp('r', i), hot = hotR.has(i), o = orphan(i), size = o ? 10 : 10 + Math.round(M.callsR(i) / maxRC * 16);
    tips['r:' + r.id] = { x: p.x, y: p.y - size / 2 - 30, text: o ? 'no agent called this ' + WIN_LABEL[S.win] : M.callsR(i) + ' calls · ' + edges.filter(e => e.r === i).length + ' agents' + (hot ? ' · active now' : '') };
    return node('r', i, { id: r.id, name: r.name, x: p.x, y: p.y, above: p.above, r: size, op: L.opR(i), fill: 'var(--color-neutral-800)', stroke: L.isSelR(i) ? 'var(--color-accent-300)' : (o ? 'var(--color-neutral-700)' : 'var(--color-neutral-600)'), glow: hot ? '0 0 14px var(--color-accent-700)' : '0 0 0 0 transparent', ring: o ? '0 0 0 3px var(--color-bg),0 0 0 4px var(--color-neutral-700)' : '0 0 0 0 transparent', lc: o ? 'var(--color-neutral-600)' : 'var(--color-neutral-400)' });
  })].join('');
  const tsel = L.sel ? tips[(L.sel.kind) + ':' + L.sel.id] : null;
  const boundary = L.vedges.filter(crosses).length;
  return `<div class="stage-inner" style="width:${W}px;height:${H}px" data-act="clear">
    <svg class="wires" width="${W}" height="${H}">${halos}${wires}${pulseSvg(L.pulses(L.vedges), 'g', 2.5)}</svg>
    ${C.out.map(c => `<div class="halo-lbl" style="left:${c.x}px;top:${c.y < H / 2 ? c.y - c.r - 18 : c.y + c.r + 18}px">${esc(c.name)}</div>`).join('')}
    ${nodes}
    ${tsel ? `<div class="tip" style="left:${tsel.x}px;top:${tsel.y}px">${esc(tsel.text)}</div>` : ''}
    <div class="overlay-tl" data-act="noop">
      <div class="seg seg-sm"><label class="seg-opt"><input type="radio" name="hops" data-act="hops" data-v="1" ${S.hops === 1 ? 'checked' : ''}>1 hop</label><label class="seg-opt"><input type="radio" name="hops" data-act="hops" data-v="2" ${S.hops === 2 ? 'checked' : ''}>2 hops</label></div>
      <span style="font-size:11px;color:var(--color-neutral-500)">Hover a node to see its reach</span>
    </div>
    <div class="overlay-tr" data-act="noop">
      <span style="display:flex;align-items:center;gap:6px"><span style="width:14px;height:0;border-top:1px dashed var(--color-accent-300)"></span>${boundary} wires leave this Mac</span>
      <span class="info">i<div class="legend">
        <span><span class="sw" style="width:16px;height:16px;border:1px solid var(--color-accent-600)"></span>Size = calls ${WIN_LABEL[S.win]}</span>
        <span><span class="sw" style="border:1px solid var(--color-accent-600);box-shadow:0 0 10px var(--color-accent)"></span>Glow = active in the last 3 min</span>
        <span><span class="sw" style="box-shadow:0 0 0 2px var(--color-bg),0 0 0 3px var(--color-accent-300)"></span>Ring = writes to 3+ resources</span>
        <span><span class="sw" style="background:var(--color-neutral-800);box-shadow:0 0 0 2px var(--color-bg),0 0 0 3px var(--color-neutral-700)"></span>Grey ring = nothing called it</span>
        <span><span style="width:16px;height:0;border-top:1px dashed var(--color-accent-300)"></span>Dashed = data leaves This Mac</span>
        <span><span class="sw" style="width:16px;height:16px;opacity:.5"></span>Halo = where things live</span>
      </div></span>
    </div>
  </div>`;
}

/* ---------- Matrix ---------- */
function matrix(M) {
  const L = lighting(M), { A, R } = M;
  const head = R.map(r => `<div class="mhead" title="${esc(r.desc)}">${esc(r.name)}</div>`).join('');
  const rows = L.visA.map(i => {
    const a = A[i], calls = S.collapsed ? M.edges.reduce((s, e) => s + e.calls, 0) : M.callsA(i);
    const cells = R.map((r, j) => {
      const e = L.vedges.find(x => x.a === i && x.r === j);
      const t = e ? `${a.name} → ${r.name}: ${e.calls} calls${e.writes ? ', ' + e.writes + ' writes' : ''}${e.items ? ' · ' + e.items.slice(0, 3).map(x => x[0]).join(', ') : ''}` : `${a.name} → ${r.name}: none`;
      return `<div class="cell" ${selAttr('a', a.id)} title="${esc(t)}" style="background:${e ? (e.perm === 'write' ? 'var(--color-accent-700)' : 'var(--color-neutral-800)') : 'var(--color-surface)'};color:${e ? 'var(--color-text)' : 'transparent'};opacity:${L.opA(i)}">${e ? e.calls : ''}</div>`;
    }).join('');
    return `<div class="mrow" ${selAttr('a', a.id)} style="opacity:${L.opA(i)}"><span class="chip chip-sm" style="${chipA(a)}">${esc(mono(a))}</span><span class="ellip" style="font-weight:500">${esc(S.collapsed ? 'COS · all agents' : a.name)}</span><span class="num" style="margin-left:auto;font-size:11px;color:var(--color-neutral-500)">${calls}</span></div>${cells}`;
  }).join('');
  return `<div class="pad" data-act="clear"><div class="matrix" style="grid-template-columns:200px repeat(${R.length},minmax(56px,1fr))"><div></div>${head}${rows}</div>
    <div class="legend-row"><span><span class="sq" style="background:var(--color-accent-700)"></span>Write</span><span><span class="sq" style="background:var(--color-neutral-800)"></span>Read</span><span>Calls ${WIN_LABEL[S.win]}</span></div></div>`;
}

/* ---------- Sessions ---------- */
const statusTag = st => st === 'running' ? 'tag-accent' : st === 'failed' ? 'tag-outline' : 'tag-neutral';
const sdot = st => st === 'running' ? 'background:var(--color-accent);box-shadow:0 0 8px var(--color-accent)' : st === 'waiting' ? 'background:var(--color-accent-500)' : 'background:var(--color-neutral-600)';
const statusLabel = st => st === 'waiting' ? 'open' : st;
function sessView(x, M) {
  const pct = Math.min(100, Math.round(x.ctx_tokens / ctxWindow(x.model) * 100));
  return { ...x, pct, ctxLabel: ktok(x.ctx_tokens) + ' context (' + pct + '%)' };
}
function sessionsView(M) {
  const L = lighting(M);
  const ql = S.q.trim().toLowerCase();
  const selAgent = L.sel && L.sel.kind === 'a' ? M.A[L.selI] : null;
  const pool = selAgent ? M.sessOfA(L.selI) : M.sessions;
  const sorters = { recent: (a, b) => b.last_t - a.last_t, context: (a, b) => b.ctx_tokens / ctxWindow(b.model) - a.ctx_tokens / ctxWindow(a.model), cost: (a, b) => (b.cost_today || 0) - (a.cost_today || 0) };
  const list = pool.filter(M.inWin).filter(x => !ql || (x.title + ' ' + x.ws + ' ' + x.last).toLowerCase().includes(ql)).sort(sorters[S.sort] || sorters.recent).slice(0, 60).map(x => sessView(x, M));
  const sortBar = `<div style="display:flex;align-items:center;gap:var(--space-4);margin-bottom:var(--space-4)" data-act="noop"><div class="seg seg-sm">${[['recent', 'Most recent'], ['context', 'Fullest context'], ['cost', 'Cost today']].map(([k, l]) => `<label class="seg-opt"><input type="radio" name="sort" data-act="sort" data-v="${k}" ${S.sort === k ? 'checked' : ''}>${l}</label>`).join('')}</div><span class="sub-n">${list.length} sessions ${WIN_LABEL[S.win]}${S.ws ? ' in ' + esc(S.ws) : ''}</span></div>`;
  if (!list.length) return `<div class="pad">${sortBar}<div class="empty" style="padding:0">No sessions ${WIN_LABEL[S.win]}${selAgent ? ' for ' + esc(selAgent.name) : ''}.</div></div>`;
  return `<div class="pad" data-act="clear">${sortBar}<div class="cards">${list.map(s => `
    <div class="card elev-sm nd-card" ${selAttr('s', s.id)} style="gap:var(--space-3);cursor:pointer;${S.sel && S.sel.kind === 's' && S.sel.id === s.id ? 'box-shadow:' + SEL_SHADOW : ''}">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="chip chip-sm" style="${chipA({ id: 'cos' })}">C</span>
        <span class="ellip" style="font-size:11px;color:var(--color-neutral-400);flex:1">COS · ${esc(s.ws)}${s.entry && s.entry !== 'cli' ? ' · ' + esc(s.entry) : ''}</span>
        <span class="sdot" style="${sdot(s.status)}"></span>
        <span class="tag ${statusTag(s.status)}">${statusLabel(s.status)}</span>
      </div>
      <span class="card-title" style="font-size:15px">${esc(s.title)}</span>
      <p style="margin:0;font-size:12px;color:var(--color-neutral-400);text-wrap:pretty;max-height:3.2em;overflow:hidden">${esc(s.last)}</p>
      <div style="display:flex;flex-wrap:wrap;gap:4px">${s.ctx.map(c => `<span class="ctx"><span class="chip chip-xs chip-res">${CTX_MONO[c[0]] || '··'}</span>${esc(c[1])}</span>`).join('')}</div>
      <div style="display:flex;flex-direction:column;gap:4px">
        <span class="bar bar-3"><span style="width:${s.pct}%"></span></span>
        <span class="card-meta"><span>${s.ctxLabel}</span><span>·</span><span>${s.prompts} prompts</span><span>·</span><span title="${s.cost_estimated ? 'Estimated: this session has not written its cost total yet' : 'From the session cost total'}">${money(s.cost_today)} today${s.cost_estimated ? '*' : ''}, ${money(s.cost)} total</span><span>·</span><span>since ${since(s.started)}</span></span>
      </div>
    </div>`).join('')}</div></div>`;
}

/* ---------- Usage ---------- */
function usage(M) {
  const { st, A, R } = M;
  const plan = st.plan || {};
  const today = new Date(), dim = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate(), dom = today.getDate();
  const monthDays = Array.from({ length: dom }, (_, i) => { const d = new Date(today.getFullYear(), today.getMonth(), i + 1); const key = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(i + 1).padStart(2, '0'); const row = st.by_day.find(x => x.day === key); return { key, usd: row ? row.usd : 0, tokens: row ? row.tokens : 0 }; });
  const maxDay = Math.max(1, ...monthDays.map(d => d.usd));
  const mon = today.toLocaleDateString('en-US', { month: 'short' });
  const projected = st.cost_month + (dom > 1 ? (st.cost_month - st.cost_today) / (dom - 1) : st.cost_today) * (dim - dom);
  const pct = st.cost_last_month ? Math.round(st.cost_month / st.cost_last_month * 100) : 0;
  const dayCost = id => st.by_agent_day[id] || 0, monCost = id => st.by_agent_month[id] || 0;
  const maxA = Math.max(0.01, ...A.map(a => monCost(a.id)));
  const totDay = Math.max(0.0001, Object.values(st.by_agent_day).reduce((s, v) => s + v, 0));
  const rows = A.filter(a => a.kind !== 'live').map(a => ({ a, day: dayCost(a.id), mon: monCost(a.id) })).sort((x, y) => y.mon - x.mon || y.day - x.day);
  const places = [...new Set([...A.map(a => a.where), ...R.map(r => r.where)])].map(p => {
    const ag = A.filter(a => a.where === p), rs = R.filter(r => r.where === p);
    const c = ag.reduce((s, a) => s + dayCost(a.id), 0);
    return { p, ag, rs, count: ag.length + rs.length, cost: ag.length ? money(c) + ' today' : '' };
  }).sort((x, y) => y.count - x.count);
  const models = Object.entries(st.by_model_month || {});
  return `<div class="pad" style="display:flex;flex-direction:column;gap:var(--space-8)" data-act="clear">
    <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:var(--space-4)">
      <div class="card elev-sm" style="gap:var(--space-3)" title="${esc(plan.note || '')}">
        <div style="display:flex;align-items:baseline;justify-content:space-between"><span class="card-kicker">${esc(plan.name || 'Plan')}</span><span style="font-size:11px;color:var(--color-neutral-500)">${dim - dom} days left in ${mon}</span></div>
        <div style="display:flex;align-items:baseline;gap:8px"><span class="big">${money(st.cost_month)}</span><span style="font-size:13px;color:var(--color-neutral-500)">API-equivalent so far</span></div>
        <span class="card-meta">${pct}% of last month's ${money(st.cost_last_month, 0)} · projected ${money(projected, 0)} for ${mon}</span>
        <span class="card-meta">You pay the flat plan fee${plan.credits_usd ? ' + up to $' + plan.credits_usd + ' usage credits' : ''}, not these amounts</span>
      </div>
      <div class="card elev-sm"><span class="card-kicker">Today</span><span class="big">${money(st.cost_today)}</span><span class="card-meta">${ktok((monthDays[dom - 1] || {}).tokens || 0)} tokens${st.cost_today_estimated > 0.5 ? ` · ${money(st.cost_today_estimated)} is estimated (±30%) until those sessions write their cost total` : ''}</span>
        <span class="card-meta">${Object.entries(st.by_ws_day || {}).map(([w, v]) => esc(w) + ' ' + money(v, 0)).join(' · ')}</span></div>
      <div class="card elev-sm"><span class="card-kicker">This month</span><span class="big">${money(st.cost_month, 0)}</span><span class="card-meta">${mon} 1 – today · ${models.map(([m, v]) => esc(m.replace('claude-', '')) + ' ' + money(v, 0)).join(' · ')}</span></div>
    </div>
    <div style="display:flex;flex-direction:column;gap:var(--space-3)">
      <span class="kicker-row">Daily spend · ${today.toLocaleDateString('en-US', { month: 'long' })}</span>
      <div class="days">${monthDays.map((d, i) => `<span title="${mon} ${i + 1} · ${money(d.usd)} · ${ktok(d.tokens)} tokens" style="height:${Math.round(d.usd / maxDay * 100)}%;background:${i === dom - 1 ? 'var(--color-accent)' : 'var(--color-accent-800)'}"></span>`).join('')}</div>
      <div class="axis"><span>${mon} 1</span><span>${mon} ${Math.ceil(dom / 2)} · tallest bar ${money(maxDay, 0)}</span><span>today</span></div>
    </div>
    <div style="display:grid;grid-template-columns:1.1fr 1fr;gap:var(--space-8)">
      <div style="display:flex;flex-direction:column;gap:var(--space-3)">
        <div class="kicker-row" style="display:grid;grid-template-columns:1fr 100px 64px 64px;gap:var(--space-3)"><span>Spend by agent</span><span>Lives on</span><span style="text-align:right">Day</span><span style="text-align:right">Month</span></div>
        ${rows.map(u => `<div class="row rule" ${selAttr('a', u.a.id)} style="display:grid;grid-template-columns:1fr 100px 64px 64px;gap:var(--space-3);align-items:center;padding:5px 0;font-size:12px">
          <span style="display:flex;flex-direction:column;gap:3px;min-width:0"><span style="display:flex;justify-content:space-between"><span style="font-weight:500">${esc(u.a.name)}</span><span style="color:var(--color-neutral-600);font-size:11px">${Math.round(u.day / totDay * 100)}%</span></span><span class="bar bar-3"><span style="width:${Math.round(u.mon / maxA * 100)}%"></span></span></span>
          <span style="color:var(--color-neutral-400);font-size:11px">${esc(u.a.where)}</span>
          <span class="num" style="text-align:right">${u.a.kind === 'routine' ? '<span title="Cloud routine spend is not visible from this Mac" style="color:var(--color-neutral-600)">n/a</span>' : money(u.day)}</span>
          <span class="num" style="text-align:right;color:var(--color-neutral-400)">${u.a.kind === 'routine' ? '' : money(u.mon, 0)}</span></div>`).join('')}
      </div>
      <div style="display:flex;flex-direction:column;gap:var(--space-3)">
        <span class="kicker-row">Where things live</span>
        ${places.map(p => `<div class="rule" style="display:flex;flex-direction:column;gap:6px;padding:8px 0">
          <div style="display:flex;align-items:baseline;gap:8px"><span style="font-size:13px;font-weight:500">${esc(p.p)}</span><span style="font-size:11px;color:var(--color-neutral-600)">${p.count}</span><span style="margin-left:auto;font-size:11px;color:var(--color-neutral-500)">${p.cost}</span></div>
          <div style="display:flex;flex-wrap:wrap;gap:4px">
            ${p.ag.map(a => `<span class="pill pill-a" ${selAttr('a', a.id)}><span class="chip chip-xs" style="${chipA(a)}">${esc(mono(a))}</span>${esc(a.name)}</span>`).join('')}
            ${p.rs.map(r => `<span class="pill pill-r" ${selAttr('r', r.id)}><span class="chip chip-xs chip-res">${esc(r.mono)}</span>${esc(r.name)}</span>`).join('')}
          </div></div>`).join('')}
      </div>
    </div>
  </div>`;
}

/* ---------- Memory: the Obsidian vault, read-only ---------- */
const inlineMd = t => esc(t)
  .replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]/g, (m, p, a) => `<a class="wl" data-act="note" data-v="${p.trim()}">${(a || p.split('/').pop()).trim()}</a>`)
  .replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>')
  .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
  .replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
function md(text) {
  const out = [], lines = text.split('\n');
  let i = 0, list = null, para = [];
  const flushP = () => { if (para.length) { out.push('<p>' + inlineMd(para.join(' ')) + '</p>'); para = []; } };
  const flushL = () => { if (list) { out.push(`</${list}>`); list = null; } };
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { flushP(); flushL(); const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); out.push('<pre><code>' + esc(buf.join('\n')) + '</code></pre>'); i++; continue; }
    const h = l.match(/^(#{1,6})\s+(.*)/);
    if (h) { flushP(); flushL(); out.push(`<h${Math.min(h[1].length, 3)}>${inlineMd(h[2])}</h${Math.min(h[1].length, 3)}>`); i++; continue; }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { flushP(); flushL(); out.push('<hr>'); i++; continue; }
    const li = l.match(/^\s*([-*+]|\d+[.)])\s+(.*)/);
    if (li) { flushP(); const kind = /\d/.test(li[1]) ? 'ol' : 'ul'; if (list !== kind) { flushL(); out.push(`<${kind}>`); list = kind; } out.push('<li>' + inlineMd(li[2].replace(/^\[([ xX])\]\s*/, (m, c) => c === ' ' ? '☐ ' : '☑ ')) + '</li>'); i++; continue; }
    if (/^\s*>/.test(l)) { flushP(); flushL(); const buf = []; while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, '')); out.push('<blockquote>' + inlineMd(buf.join(' ')) + '</blockquote>'); continue; }
    if (/^\s*\|/.test(l)) { flushP(); flushL(); const rows = []; while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]); const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inlineMd(c.trim())); const body = rows.filter(r => !/^\s*\|?\s*:?-{2,}/.test(r)); out.push('<table>' + body.map((r, n) => '<tr>' + cells(r).map(c => `<${n ? 'td' : 'th'}>${c}</${n ? 'td' : 'th'}>`).join('') + '</tr>').join('') + '</table>'); continue; }
    if (!l.trim()) { flushP(); flushL(); i++; continue; }
    flushL(); para.push(l.trim()); i++;
  }
  flushP(); flushL();
  return out.join('\n');
}
function memoryView(M) {
  const V = D.vault || { notes: [] }, notes = V.notes || [];
  const ql = S.q.trim().toLowerCase();
  const hit = n => !ql || (n.title + ' ' + n.path + ' ' + n.text).toLowerCase().includes(ql);
  const shown = notes.filter(hit);
  const byFolder = new Map();
  for (const n of shown) { const f = n.folder || ''; if (!byFolder.has(f)) byFolder.set(f, []); byFolder.get(f).push(n); }
  const order = [...byFolder.keys()].sort((a, b) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b)));
  const find = p => { const q = p.toLowerCase(); return notes.find(n => n.path.toLowerCase() === q + '.md') || notes.find(n => n.name.toLowerCase() === q.split('/').pop()) || notes.find(n => n.path.toLowerCase().endsWith('/' + q.split('/').pop() + '.md')); };
  const cur = (S.note && find(S.note.replace(/\.md$/, ''))) || find('Home') || shown[0];
  const list = order.map(f => `<div class="vault-folder">${esc(f || 'Vault')}</div>` + byFolder.get(f).sort((a, b) => a.name === f.split('/').pop() ? -1 : b.name === f.split('/').pop() ? 1 : b.mtime - a.mtime).map(n => `<div class="vault-item${cur && n.path === cur.path ? ' on' : ''}" data-act="note" data-v="${esc(n.path.replace(/\.md$/, ''))}"><span class="t">${esc(n.title)}</span><span class="m">${esc((n.fm.status || '') + (n.fm.status ? ' · ' : ''))}${ago(n.mtime)}${n.fm.last_activity ? ' · activity ' + esc(n.fm.last_activity) : ''}</span></div>`).join('')).join('');
  const body = !notes.length ? `<div class="empty">${V.missing ? 'No vault at <code>' + esc(V.root || '~/vault') + '</code>. Set <code>vault</code> in dashboard/config.json.' : 'No notes yet.'}</div>` :
    !cur ? '<div class="empty">Nothing matches.</div>' : `<div class="note">
      <div class="note-meta"><span>${esc(cur.path)}</span><span>· edited ${ago(cur.mtime)}</span>${cur.fm.workspace ? `<span class="ws">${esc(cur.fm.workspace)}</span>` : ''}${(Array.isArray(cur.fm.tags) ? cur.fm.tags : []).map(t => `<span class="ws">#${esc(t)}</span>`).join('')}
        <a style="margin-left:auto" href="obsidian://open?path=${encodeURIComponent((V.root || '') + '/' + cur.path)}">Open in Obsidian ↗</a></div>
      ${md(cur.text)}
      ${cur.links.length ? `<hr><div class="sub-n">Links to: ${cur.links.map(l => `<a class="wl" data-act="note" data-v="${esc(l)}">${esc(l.split('/').pop())}</a>`).join(' · ')}</div>` : ''}
    </div>`;
  return `<div class="vault" data-act="noop"><div class="vault-list"><div class="sub-n" style="padding:4px 8px">${shown.length} of ${notes.length} notes${ql ? ' match' : ''} · ${esc((V.root || '').replace(/^\/Users\/[^/]+/, '~'))}</div>${list}</div><div class="vault-note">${body}</div></div>`;
}

/* ---------- Registry: everything built, from registry/registry.json (optional; empty when the file is absent) ---------- */
function registry(M) {
  const items = D.reg || [];
  const ql = S.q.trim().toLowerCase();
  const types = [...new Set(items.map(x => x.type))].sort(), statuses = [...new Set(items.map(x => x.status))].sort();
  const keep = x => (!S.regType || x.type === S.regType) && (!S.regStatus || x.status === S.regStatus) &&
    (!ql || [x.name, x.purpose, x.workspace, x.path, (x.tags || []).join(' ')].join(' ').toLowerCase().includes(ql));
  const rows = items.filter(keep).sort((a, b) => String(b.updated || '').localeCompare(String(a.updated || '')) || a.name.localeCompare(b.name));
  const byName = new Map(items.map(x => [x.id, x.name]));
  const link = x => x.url || x.repo || '';
  const stTag = st => `<span class="tag ${st === 'live' || st === 'active' ? 'tag-accent' : st === 'done' ? 'tag-neutral' : 'tag-outline'}">${esc(st || '')}</span>`;
  const seg = (list, cur, act, all) => `<div class="seg seg-sm">${[['', all], ...list.map(t => [t, t])].map(([k, l]) => `<label class="seg-opt"><input type="radio" name="${act}" data-act="${act}" data-v="${k}" ${cur === k ? 'checked' : ''}>${l}</label>`).join('')}</div>`;
  const card = x => `<div class="reg-card elev-sm">
      <div style="display:flex;align-items:center;gap:8px;min-width:0"><span class="nm ellip" style="flex:1" title="${esc(x.name)}">${esc(x.name)}</span>${stTag(x.status)}</div>
      <div class="mt"><span>${esc(x.type)}</span>${x.workspace ? `<span class="ws">${esc(x.workspace)}</span>` : ''}${x.updated ? `<span>updated ${esc(x.updated)}</span>` : ''}</div>
      <span class="pu" title="${esc(x.purpose || '')}">${esc(x.purpose || '')}</span>
      ${x.next ? `<span class="nx" title="${esc(x.next)}">Next: ${esc(x.next)}</span>` : ''}
      <div class="mt">${link(x) ? `<a href="${esc(link(x))}" target="_blank" rel="noopener">${esc(link(x).replace(/^https?:\/\//, '').slice(0, 48))}</a>` : ''}${x.path ? `<span class="ellip" title="${esc(x.path)}" style="max-width:220px">${esc(x.path.replace(/^\/Users\/[^/]+\//, '~/'))}</span>` : ''}</div>
      ${(x.links || []).length ? `<div class="mt" title="${esc(x.links.map(l => byName.get(l) || l).join(', '))}">links: ${esc(x.links.slice(0, 4).map(l => byName.get(l) || l).join(' · '))}${x.links.length > 4 ? ' · +' + (x.links.length - 4) : ''}</div>` : ''}
    </div>`;
  return `<div class="pad" style="display:flex;flex-direction:column;gap:var(--space-6)" data-act="clear">
    <div style="display:flex;flex-direction:column;gap:var(--space-3)" data-act="noop">
      <div style="display:flex;align-items:center;gap:var(--space-4);flex-wrap:wrap">${seg(types, S.regType, 'regt', 'All types')}${seg(statuses, S.regStatus, 'regs', 'Any status')}
        <span class="sub-n">${rows.length} of ${items.length}</span>
        </div>
      <span class="sub-n">Read-only copy of registry/registry.json.</span>
    </div>
    ${rows.length ? `<div class="reg-grid">${rows.map(card).join('')}</div>` : '<div class="empty">Nothing matches.</div>'}
  </div>`;
}

/* ---------- Inventory: everything installed, with use and health ---------- */
function inventory(M) {
  const groups = D.inv || [];
  const ql = S.q.trim().toLowerCase();
  const f = S.invFilter;
  const keep = r => (!ql || (r.name + ' ' + (r.source || '')).toLowerCase().includes(ql)) &&
    (f === 'all' || (f === 'unused' && !r.d30 && !['hook', 'launchd', 'n8n'].includes(r.kind) && r.status !== 'needs sign-in') ||
     (f === 'used' && r.d30 > 0) || (f === 'problems' && (r.status === 'failing' || (r.d30 >= 10 && (r.failed || 0) / r.d30 > 0.2) || /exit [1-9]/.test(r.status || ''))));
  const counts = groups.map(g => [g.title, g.rows.length]);
  const statusCell = r => {
    if (r.status === 'failing') return `<span class="tag tag-outline" title="${esc(r.error || '')}">failing</span>`;
    if (r.status && r.status !== 'connected' && r.status !== 'active') return `<span class="sub-n">${esc(r.status)}</span>`;
    if (['hook', 'launchd', 'n8n'].includes(r.kind)) return `<span class="sub-n">${esc(r.status || '')}</span>`;
    return r.d30 ? `<span class="tag tag-accent">used</span>` : `<span class="tag tag-neutral">never used</span>`;
  };
  const sec = g => {
    const rows = g.rows.filter(keep).sort((a, b) => (b.d30 || 0) - (a.d30 || 0) || String(a.name).localeCompare(b.name));
    if (!rows.length) return '';
    return `<div style="display:flex;flex-direction:column;gap:var(--space-2)">
      <div style="display:flex;align-items:baseline;gap:8px"><span class="kicker-row">${esc(g.title)}</span><span class="sub-n">${rows.length}${rows.length !== g.rows.length ? ' of ' + g.rows.length : ''}</span>${g.note ? `<span class="sub-n" style="margin-left:auto">${esc(g.note)}</span>` : ''}</div>
      <table class="table" style="width:100%;font-size:12px"><thead><tr><th style="text-align:left">Name</th><th style="text-align:left">Source</th><th style="text-align:right">Today</th><th style="text-align:right">7d</th><th style="text-align:right">30d</th><th style="text-align:left">Last used</th><th style="text-align:left">Who</th><th style="text-align:left">Status</th></tr></thead>
      <tbody>${rows.map(r => `<tr${r.id ? ` class="row" ${selAttr('a', r.id)}` : ''}><td style="font-weight:500">${esc(r.name)}</td><td class="sub-n">${esc(r.source || '')}${r.tools ? ' · ' + r.tools + ' tools' : ''}${r.cadence ? ' · ' + esc(r.cadence) : ''}</td>
        <td class="num" style="text-align:right">${r.d1 || ''}</td><td class="num" style="text-align:right">${r.d7 || ''}</td><td class="num" style="text-align:right">${r.d30 || ''}</td>
        <td class="sub-n">${r.last ? ago(r.last) : r.last_write ? 'written ' + ago(r.last_write) : ''}</td>
        <td class="sub-n">${esc(Object.keys(r.agents || {}).map(id => { const i = M.aIdx.get(id); return i == null ? id : M.A[i].name; }).slice(0, 3).join(', '))}</td>
        <td>${statusCell(r)}</td></tr>`).join('')}</tbody></table></div>`;
  };
  return `<div class="pad" style="display:flex;flex-direction:column;gap:var(--space-8)" data-act="clear">
    <div style="display:flex;flex-direction:column;gap:var(--space-3)" data-act="noop">
      <div style="display:flex;align-items:center;gap:var(--space-4)"><div class="seg seg-sm">${[['all', 'Everything'], ['used', 'Used (30d)'], ['unused', 'Never used'], ['problems', 'Problems']].map(([k, l]) => `<label class="seg-opt"><input type="radio" name="invf" data-act="invf" data-v="${k}" ${f === k ? 'checked' : ''}>${l}</label>`).join('')}</div>
        <span class="sub-n">${counts.map(([t, n]) => n + ' ' + t.toLowerCase()).join(' · ')}</span></div>
      ${(D.health || []).length ? `<div class="card elev-sm" style="gap:var(--space-2)"><span class="card-kicker">Health</span>${healthRows(D.health)}</div>` : ''}
    </div>
    ${groups.map(sec).join('') || '<div class="empty">Nothing matches.</div>'}
  </div>`;
}

/* ---------- Recent runs drawer ---------- */
function drawer(M) {
  const { A, R, g } = M;
  const L = lighting(M);
  const name = id => { const i = M.aIdx.get(id); return i == null ? id : A[i].name; };
  const rname = id => { const i = M.rIdx.get(id); return i == null ? id : R[i].name; };
  const hourAgo = Date.now() / 1000 - 3600;
  const lastHour = M.st.runs_last_hour ?? g.runs.filter(r => r.t >= hourAgo).length;
  const liveSel = L.sel && L.sel.kind === 'a' && L.sel.id.startsWith('live:') ? L.sel.id.slice(5) : null;
  const match = r => !L.sel ? true : liveSel ? r.s === liveSel : L.sel.kind === 'a' ? (r.a === L.sel.id || L.cosOpen) : r.r === L.sel.id;
  const sessSel = S.sel && S.sel.kind === 's' ? S.sel.id : null;
  const list = g.runs.filter(r => (sessSel ? r.s === sessSel : true) && (!S.ws || r.w === S.ws)).slice(0, 120);
  const status = r => r.st === 'failed' ? 'failed' : r.dur > 30000 ? 'slow' : 'ok';
  return `<div class="drawer-head" data-act="drawer">
      <span class="kicker-row">Recent runs</span>
      <span style="font-size:11px;color:var(--color-neutral-600)">${lastHour} in the last hour${sessSel ? ' · filtered to the selected session' : ''}${S.ws ? ' · ' + esc(S.ws) : ''}</span>
      <span style="margin-left:auto;font-size:11px;color:var(--color-accent)">${S.drawer ? 'Collapse' : 'Expand'}</span></div>
    <div class="drawer-body" style="visibility:${S.drawer ? 'visible' : 'hidden'}">
      ${list.map(r => { const st = status(r); return `<div class="run row" ${r.s ? selAttr('s', r.s) : selAttr('a', r.a)} title="${esc((r.src === 'cloud' ? 'cloud · ' : '') + (r.w || '') + ' · ' + (r.n || ''))}" style="opacity:${match(r) && L.matchA(M.aIdx.get(r.a) ?? 0) ? 1 : 0.3}">
        <span class="num" style="color:var(--color-neutral-500)">${since(r.t)}</span>
        <span class="ellip" style="font-weight:500">${esc(name(r.a))}</span>
        <span style="color:var(--color-neutral-600)">${r.p === 'write' ? '⇢' : '→'}</span>
        <span class="ellip">${esc(rname(r.r))}</span>
        <span class="ellip" style="color:var(--color-neutral-400)">${esc(r.declared ? 'run · ' + (r.d || '') : (r.d || r.n || ''))}</span>
        <span class="num" style="color:var(--color-neutral-500)">${dur(r.dur)}</span>
        <span class="tag ${st === 'ok' ? 'tag-neutral' : st === 'failed' ? 'tag-outline' : 'tag-accent'}" style="justify-self:end">${st}</span></div>`; }).join('')}
    </div>`;
}

/* ---------- side panel ---------- */
function hoursBars(arr) {
  const h = arr || Array(24).fill(0), mx = Math.max(1, ...h), cur = new Date().getHours();
  return `<div class="hours">${h.map((v, i) => `<span title="${String(i).padStart(2, '0')}:00 · ${v} calls" style="height:${Math.max(2, Math.round(v / mx * 100))}%;background:${i === cur ? 'var(--color-accent)' : 'var(--color-accent-800)'}"></span>`).join('')}</div>
    <div class="axis"><span>00:00</span><span>12:00</span><span>23:00</span></div>`;
}
function stats3(k) { return `<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:var(--space-3)">${k.map(([a, b]) => `<div class="p-stat"><span class="k">${a}</span><span class="v">${b}</span></div>`).join('')}</div>`; }
function section(key, title, count, right, body) {
  const open = S.secs[key];
  return `<div style="display:flex;flex-direction:column;gap:var(--space-3)">
    <div class="sec-head" data-act="sec" data-v="${key}"><span class="chev">${open ? '▾' : '▸'}</span><span class="kicker-row">${title}</span><span class="sub-n">${count}</span>${right ? `<span class="sub-n" style="margin-left:auto">${right}</span>` : ''}</div>
    ${open ? body : ''}</div>`;
}
function miniSessions(list) {
  return list.slice(0, 12).map(x => { const s = sessView(x); return `<div class="mini row" ${selAttr('s', s.id)}>
    <div style="display:flex;align-items:center;gap:8px"><span class="sdot" style="${sdot(s.status)}"></span><span class="ellip" style="font-size:12px;font-weight:500;flex:1">${esc(s.title)}</span><span style="font-size:10px;color:var(--color-neutral-500)">${statusLabel(s.status)}</span></div>
    <span style="font-size:11px;color:var(--color-neutral-400);max-height:2.8em;overflow:hidden">${esc(s.last)}</span>
    <div style="display:flex;flex-wrap:wrap;gap:4px"><span class="ws">${esc(s.ws)}</span>${s.ctx.slice(0, 2).map(c => `<span class="ws">${esc(c[1])}</span>`).join('')}</div>
    <span class="bar bar-2"><span style="width:${s.pct}%"></span></span>
    <span style="font-size:10px;color:var(--color-neutral-600)">${s.ctxLabel} · ${s.prompts} prompts · ${money(s.cost)}</span></div>`; }).join('');
}
function accessCtl(e) {
  const hidden = !!S.hidden[e.k];
  return `<span style="display:inline-flex;align-items:center;gap:6px;flex:none">
    <span class="tag ${e.perm === 'write' ? 'tag-accent' : 'tag-neutral'}" title="${e.declared ? 'Declared in the routine prompt' : 'Observed in transcripts'}">${e.perm}${e.declared ? '*' : ''}</span>
    <span class="acc" title="Hide or show this link on the page. Claude Code permissions are not changed here.">
      <button data-act="${hidden ? 'show' : 'hide'}" data-v="${esc(e.k)}" class="${hidden ? 'off-on' : ''}">${hidden ? 'Hidden' : 'Hide'}</button></span></span>`;
}
function itemList(items, wl) {
  return (items || []).map(([n, c]) => `<div class="li rule" style="padding:4px 0;font-size:12px"><span class="ellip" style="flex:1">${esc(n)}</span><span class="num sub-n">${c}</span></div>`).join('');
}
function githubExtra(M) {
  const gh = D.gh || {}, rem = gh.remote;
  const commits = (gh.commits || []).slice(0, 8);
  return `${rem ? `<div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">${esc(rem.repo || 'repo')}</span>
      <span class="sub-n">${(rem.size_kb / 1024).toFixed(0)} MB · pushed ${ago(Date.parse(rem.pushed_at) / 1000)} · branches: ${esc(rem.branches.join(', '))}</span>
      ${rem.pulls.slice(0, 5).map(p => `<a class="li rule" href="${esc(p.url)}" target="_blank" rel="noopener" style="text-decoration:none;color:inherit;font-size:12px"><span class="tag ${p.state === 'open' ? 'tag-accent' : 'tag-neutral'}">${p.state === 'open' ? 'open' : p.merged ? 'merged' : 'closed'}</span><span class="ellip" style="flex:1">#${p.n} ${esc(p.title)}</span><span class="sub-n">${esc(p.branch || '')}</span></a>`).join('')}</div>` : '<span class="sub-n">GitHub API not reachable (gh)</span>'}
    <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Recent commits</span>${commits.map(c => `<div class="li rule" style="font-size:12px;padding:4px 0"><span class="tag ${c.src === 'cloud' ? 'tag-accent' : 'tag-neutral'}" title="${c.src === 'cloud' ? 'pushed by a cloud session or routine' : 'pushed from this Mac'}">${c.src === 'cloud' ? (c.routine || 'cloud') : 'local'}</span><span class="ellip" style="flex:1" title="${esc(c.s)}">${esc(c.s)}</span><span class="sub-n">${since(c.t)}</span></div>`).join('')}
      ${gh.last_watcher ? `<span class="sub-n">Last watcher pass ${ago(gh.last_watcher)}</span>` : ''}</div>`;
}
function memoryExtra() {
  return `<div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Brains</span>${(D.mem || []).map(m => `<div class="li rule" style="font-size:12px"><span style="display:flex;flex-direction:column;flex:1;min-width:0"><span style="font-weight:500">${esc(m.ws)}</span><span class="ellip sub-n" title="${esc((m.files || []).slice(0, 6).map(f => f.name).join(', '))}">${esc((m.files || []).slice(0, 3).map(f => f.name).join(', '))}</span></span><span class="num sub-n" style="text-align:right">${m.count} files${m.unindexed ? ' · ' + m.unindexed + ' unindexed' : ''}<br>${m.last ? 'written ' + ago(m.last) : ''}</span></div>`).join('')}</div>`;
}
function connectorsExtra() {
  const g = (D.inv || []).find(x => x.id === 'connectors');
  if (!g) return '';
  const live = g.rows.filter(r => r.status !== 'needs sign-in');
  const signin = g.rows.length - live.length;
  return `<div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">MCP servers</span>${live.map(r => `<div class="li rule" style="font-size:12px;padding:4px 0"><span class="nd-dot" style="background:${r.status === 'failing' ? 'var(--color-accent-300)' : r.d30 ? 'var(--color-accent)' : 'var(--color-neutral-700)'}"></span><span class="ellip" style="flex:1" title="${esc(r.error || r.source)}">${esc(r.name)}</span><span class="sub-n">${r.status === 'failing' ? 'failing' : r.status === 'connected' ? (r.d30 ? r.d30 + ' calls' : 'unused') : esc(r.status)}</span></div>`).join('')}
    ${signin ? `<span class="sub-n">${signin} plugin connectors only offer sign-in. See Inventory.</span>` : ''}</div>`;
}
function panel(M) {
  const { A, R, all } = M;
  const sel = S.sel;
  if (!sel) return overview(M);
  const wl = WIN_SHORT[S.win];
  const liveA = sel.kind === 'a' && sel.id.startsWith('live:') ? sel.id.slice(5) : null;
  if (sel.kind === 's' || liveA) {
    const s0 = M.sessions.find(x => x.id === (liveA || sel.id));
    if (!s0) return overview(M);
    const s = sessView(s0);
    const used = Object.entries(s.res || {}).sort((a, b) => b[1] - a[1]);
    return `<div class="p-wrap">
      <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="card-kicker">Session · ${esc(s.ws)} · ${esc((s.model || '').replace('claude-', ''))}</span>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px"><h4 style="margin:0">${esc(s.title)}</h4><button class="btn btn-ghost" style="font-size:12px" data-act="clear">Close</button></div>
        <p style="margin:0;color:var(--color-neutral-400);font-size:12px;text-wrap:pretty">${esc(s.last)}</p></div>
      ${stats3([['Status', statusLabel(s.status)], ['Cost', money(s.cost)], ['Prompts', s.prompts]])}
      <div style="display:flex;flex-direction:column;gap:4px"><span class="bar bar-3"><span style="width:${s.pct}%"></span></span><span class="card-meta">${s.ctxLabel} · ${ktok(s.tokens)} tokens total · ${s.compacts} compactions · since ${since(s.started)}, last ${ago(s.last_t)}</span></div>
      <div style="display:flex;flex-direction:column;gap:var(--space-3)"><span class="kicker-row">Resources it touched</span>
        ${used.map(([rid, n]) => { const i = M.rIdx.get(rid); return i == null ? '' : `<div class="li rule row" ${selAttr('r', rid)}><span class="chip chip-sm chip-res">${esc(R[i].mono)}</span><span style="flex:1">${esc(R[i].name)}</span><span class="num" style="color:var(--color-neutral-400)">${n}</span></div>`; }).join('') || '<span class="sub-n">none</span>'}
        ${Object.keys(s.skills || {}).length ? `<span class="sub-n">Skills: ${esc(Object.keys(s.skills).join(', '))}</span>` : ''}
        ${Object.keys(s.subagents || {}).length ? `<span class="sub-n">Subagents: ${esc(Object.entries(s.subagents).map(([k, v]) => k + ' ×' + v).join(', '))}</span>` : ''}</div>
      <div style="display:flex;gap:var(--space-2)"><button class="btn btn-primary" style="flex:1" data-act="copy" data-v="${esc(s.resume)}">Copy resume command</button><button class="btn btn-secondary" style="flex:1" data-act="openruns">Runs</button></div>
    </div>`;
  }
  const isA = sel.kind === 'a', i = isA ? M.aIdx.get(sel.id) : M.rIdx.get(sel.id);
  if (i == null) return overview(M);
  if (isA && i === 0) {
    const a = A[0], team = A.slice(1).filter(x => x.kind !== 'live');
    const sessions = M.sessions.filter(M.inWin);
    const totalCalls = M.edges.reduce((s, e) => s + e.calls, 0);
    return `<div class="p-wrap">
      ${head('Chief of staff · ' + a.where, a.name, a.desc)}
      ${stats3([['Team calls', totalCalls], ['Sessions', sessions.length], ['Needs look', A.filter((_, j) => M.needsLook(j)).length]])}
      ${section('team', 'Delegated agents', team.length, 'Calls · ' + wl, team.map(x => { const j = M.aIdx.get(x.id), res = M.edges.filter(e => e.a === j); return `<div class="li rule row" ${selAttr('a', x.id)}><span class="nd-dot" style="background:${M.needsLook(j) ? 'var(--color-accent-300)' : M.liveA(j) ? 'var(--color-accent)' : 'var(--color-neutral-700)'}"></span><span style="display:flex;flex-direction:column;flex:1;min-width:0"><span style="font-size:13px;font-weight:500">${esc(x.name)}</span><span class="ellip" style="font-size:11px;color:var(--color-neutral-500)">${esc(res.map(e => R[e.r].name).join(' · ') || agentMeta(x))}</span></span><span class="num" style="font-size:11px;color:var(--color-neutral-400);white-space:nowrap">${M.callsA(j)}</span></div>`; }).join(''))}
      ${section('sess', 'Sessions across the team', sessions.length, '', miniSessions(sessions))}
      <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Calls today</span>${hoursBars(M.g.hourly[a.id])}</div>
      <div style="display:flex;gap:var(--space-2)"><button class="btn btn-primary" style="flex:1" data-act="openruns">Open logs</button><button class="btn btn-secondary" style="flex:1" data-act="view" data-v="sessions">Sessions</button></div>
    </div>`;
  }
  if (isA) {
    const a = A[i], mine = all.filter(e => e.a === i), sess = M.sessOfA(i).filter(M.inWin), h = a.health || {};
    const status = M.needsLook(i) ? 'Needs look' : M.callsA(i) || h.last ? 'Healthy' : 'Unused';
    const third = a.kind === 'routine' ? ['Last run', h.last ? ago(h.last).replace(' ago', '') : 'not yet'] : a.kind === 'cloud' ? ['Commits', M.callsA(i)] : ['Sessions', sess.length];
    const repo = ((D.gh || {}).remote || {}).repo, repoLink = a.kind === 'routine' && repo ? `https://github.com/${repo}/blob/main/routines/${a.id.slice(8)}.md` : '';
    return `<div class="p-wrap">
      ${head((a.kind === 'routine' ? 'Routine' : 'Agent') + ' · ' + a.where, a.name, a.desc + (a.kind === 'routine' ? ' ' + agentMeta(a) + '.' : ''))}
      ${stats3([['Status', status], [a.kind === 'routine' ? 'Runs' : 'Calls', M.callsA(i)], third])}
      ${section('links', a.kind === 'routine' ? 'Resources its prompt declares' : 'Resources it calls', mine.length, 'Seen', mine.map(e => `<div class="li rule"><span data-act="sel" data-k="r" data-id="${esc(R[e.r].id)}" style="display:flex;flex-direction:column;flex:1;min-width:0;cursor:pointer"><span style="font-size:13px;font-weight:500">${esc(R[e.r].name)}</span><span class="ellip" style="font-size:11px;color:var(--color-neutral-500)" title="${esc((e.items || []).map(x => x[0] + ' ' + x[1]).join(', '))}">${a.kind === 'routine' ? e.calls + ' runs' : e.calls + ' calls'} ${wl}${e.items && !e.declared ? ' · ' + esc(e.items.slice(0, 4).map(x => x[0]).join(', ')) : ''}</span></span>${accessCtl(e)}</div>`).join('') || '<span class="sub-n">No calls ' + WIN_LABEL[S.win] + '.</span>')}
      ${a.kind === 'routine' && (h.missed_today || []).length ? `<span class="sub-n" style="color:var(--color-accent-300)">Missed today: ${h.missed_today.map(x => x + ':00').join(', ')}</span>` : ''}
      ${sess.length ? section('sess', 'Sessions', sess.length, '', miniSessions(sess)) : ''}
      <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Calls today</span>${hoursBars(M.g.hourly[a.id])}</div>
      <div style="display:flex;gap:var(--space-2)"><button class="btn btn-primary" style="flex:1" data-act="openruns">Open logs</button>${repoLink ? `<a class="btn btn-secondary" style="flex:1;text-align:center;text-decoration:none" href="${repoLink}" target="_blank" rel="noopener">Open prompt</a>` : `<button class="btn btn-secondary" style="flex:1" data-act="view" data-v="matrix">Matrix</button>`}</div>
    </div>`;
  }
  const r = R[i], mine = all.filter(e => e.r === i), shown = mine.filter(e => !S.hidden[e.k]);
  return `<div class="p-wrap">
    ${head('Resource · ' + r.where, r.name, r.desc + ' ' + r.sub + '.')}
    ${stats3([['Agents', shown.length], ['Calls', shown.reduce((s, e) => s + e.calls, 0)], ['Write', shown.filter(e => e.perm === 'write').length]])}
    ${section('links', 'Agents with access', mine.length, 'Seen', mine.map(e => `<div class="li rule"><span data-act="sel" data-k="a" data-id="${esc(A[e.a].id)}" style="display:flex;flex-direction:column;flex:1;min-width:0;cursor:pointer"><span style="font-size:13px;font-weight:500">${esc(A[e.a].name)}</span><span class="ellip" style="font-size:11px;color:var(--color-neutral-500)">${A[e.a].kind === 'routine' ? 'declared · ' + e.calls + ' runs' : e.calls + ' calls'} ${wl}</span></span>${accessCtl(e)}</div>`).join('') || '<span class="sub-n">No calls ' + WIN_LABEL[S.win] + '.</span>')}
    ${(() => { const agg = {}; mine.filter(e => !e.declared).forEach(e => (e.items || []).forEach(([n, c]) => { agg[n] = (agg[n] || 0) + c; })); const list = Object.entries(agg).sort((a, b) => b[1] - a[1]); return list.length ? section('items', 'What was used (30 days)', list.length, 'Calls', itemList(list.slice(0, 25))) : ''; })()}
    ${r.id === 'github' ? githubExtra(M) : r.id === 'memory' ? memoryExtra() : r.id === 'connectors' ? connectorsExtra() : ''}
    <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Calls today</span>${hoursBars(M.g.hourly[r.id])}</div>
    <div style="display:flex;gap:var(--space-2)"><button class="btn btn-primary" style="flex:1" data-act="openruns">Open logs</button><button class="btn btn-secondary" style="flex:1" data-act="unhideall">Show all links</button></div>
  </div>`;
}
function healthRows(list) {
  return list.map(x => { const ref = x.ref || ''; const k = ref.startsWith('routine:') || ref === 'cos' || ref.startsWith('sub:') ? 'a' : ref ? 'r' : '';
    return `<div class="li rule ${k ? 'row' : ''}" ${k ? selAttr(k, ref) : ''} style="font-size:12px;align-items:flex-start"><span class="nd-dot" style="margin-top:5px;background:${x.level === 'bad' ? 'var(--color-accent-300)' : x.level === 'warn' ? 'var(--color-accent-500)' : 'var(--color-neutral-600)'}"></span><span style="flex:1;color:${x.level === 'info' ? 'var(--color-neutral-400)' : 'var(--color-text)'}">${esc(x.text)}</span></div>`; }).join('');
}
function agentMeta(a) {
  const h = a.health || {};
  if (a.kind === 'routine') return (EXPECT_LABEL[a.id.slice(8)] || '') + ' · ' + h.runs7 + ' runs in 7 days · last ' + ago(h.last) + (h.stale ? ' · overdue' : '');
  return h.last ? 'last active ' + ago(h.last) : 'never called';
}
function head(kicker, name, desc) {
  return `<div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="card-kicker">${esc(kicker)}</span>
    <div style="display:flex;align-items:center;justify-content:space-between;gap:8px"><h4 style="margin:0">${esc(name)}</h4><button class="btn btn-ghost" style="font-size:12px" data-act="clear">Close</button></div>
    <p style="margin:0;color:var(--color-neutral-400);font-size:12px;text-wrap:pretty">${esc(desc)}</p></div>`;
}
function overview(M) {
  const { A, R, edges } = M;
  const look = A.map((_, i) => i).filter(i => M.needsLook(i));
  const failedWin = A.reduce((s, a) => s + ((a.health || {})['f' + S.win.slice(1)] || 0), 0);
  const probs = (D.health || []).filter(x => x.level !== 'info');
  const maxC = Math.max(1, ...A.map((_, i) => M.callsA(i)));
  const rows = A.map((a, i) => ({ a, i, c: M.callsA(i) })).sort((x, y) => y.c - x.c);
  const topRes = R.map((r, i) => ({ r, c: M.callsR(i) })).sort((x, y) => y.c - x.c).slice(0, 5);
  return `<div class="p-wrap">
    <div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="card-kicker">Overview</span><h4 style="margin:0">Your mesh ${WIN_LABEL[S.win]}</h4>
      <p style="margin:0;color:var(--color-neutral-400);font-size:12px;text-wrap:pretty">Select any agent or resource to see its connections, access and spend. COS runs every Claude Code session (${A.filter(x => x.kind === 'live').length} open now, listed first) and delegates to the other ${A.filter(x => x.kind !== 'live').length - 1} agents.</p></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:var(--space-3)">
      <div class="card elev-sm" style="background:var(--color-bg)"><span class="card-kicker">Health</span><span style="font-size:22px;font-family:var(--font-heading);font-weight:500">${probs.length ? probs.length + ' issue' + (probs.length > 1 ? 's' : '') : 'All clear'}</span><span class="card-meta">${failedWin} failed calls ${WIN_LABEL[S.win]}</span></div>
      <div class="card elev-sm" style="background:var(--color-bg)"><span class="card-kicker">Links</span><span style="font-size:22px;font-family:var(--font-heading);font-weight:500">${edges.length}</span><span class="card-meta">${edges.filter(e => e.perm === 'write').length} with write access</span></div>
    </div>
    ${(D.health || []).length ? `<div style="display:flex;flex-direction:column;gap:var(--space-2)"><span class="kicker-row">Needs a look</span>${healthRows(D.health.slice(0, 8))}</div>` : ''}
    <div style="display:flex;flex-direction:column;gap:var(--space-3)"><span class="kicker-row">Activity by agent</span>
      ${rows.map(r => `<div class="row" ${selAttr('a', r.a.id)} style="display:grid;grid-template-columns:120px 1fr 48px;align-items:center;gap:var(--space-3);font-size:12px">
        <span class="ellip" style="display:flex;align-items:center;gap:6px"><span class="nd-dot" style="background:${M.needsLook(r.i) ? 'var(--color-accent-300)' : 'var(--color-accent)'}"></span>${esc(r.a.name)}</span>
        <span class="bar bar-4"><span style="width:${Math.round(r.c / maxC * 100)}%"></span></span>
        <span class="num" style="text-align:right;color:var(--color-neutral-400)">${r.c}</span></div>`).join('')}</div>
    <div style="display:flex;flex-direction:column;gap:var(--space-3)"><span class="kicker-row">Most-called resources</span>
      ${topRes.map(t => `<div class="row" ${selAttr('r', t.r.id)} style="display:flex;align-items:center;gap:var(--space-3);font-size:12px"><span class="chip chip-sm chip-res">${esc(t.r.mono)}</span><span style="flex:1">${esc(t.r.name)}</span><span class="num" style="color:var(--color-neutral-400)">${t.c}</span></div>`).join('')}</div>
  </div>`;
}

/* ---------- events ---------- */
function toast(msg) { const t = document.createElement('div'); t.className = 'toast'; t.textContent = msg; document.body.appendChild(t); setTimeout(() => t.remove(), 1600); }
function setView(v) { S.view = v; localStorage.setItem(LS + 'view', JSON.stringify(v)); history.replaceState(null, '', '#' + v); render(); }
document.addEventListener('click', ev => {
  const el = ev.target.closest('[data-act]');
  if (!el) return;
  const act = el.dataset.act, v = el.dataset.v;
  if (act === 'noop' && el === ev.target) return;
  if (act === 'noop') return;
  ev.preventDefault();
  switch (act) {
    case 'sel': { const k = el.dataset.k, id = el.dataset.id; S.sel = S.sel && S.sel.kind === k && S.sel.id === id ? null : { kind: k, id }; break; }
    case 'clear': S.sel = null; break;
    case 'collapse': S.collapsed = !S.collapsed; if (!S.collapsed) S.open = {}; localStorage.setItem(LS + 'open', '{}'); break;
    case 'tog': { const a = D.g.agents.find(x => x.id === el.dataset.id); if (a) { S.collapsed = false; S.open[a.id] = !groupOpen(a); localStorage.setItem(LS + 'open', JSON.stringify(S.open)); } break; }
    case 'drawer': S.drawer = !S.drawer; break;
    case 'openruns': S.drawer = true; break;
    case 'sec': S.secs[v] = !S.secs[v]; break;
    case 'hops': S.hops = +v; break;
    case 'view': setView(v); return;
    case 'hide': S.hidden[v] = true; localStorage.setItem(LS + 'hidden', JSON.stringify(S.hidden)); break;
    case 'show': delete S.hidden[v]; localStorage.setItem(LS + 'hidden', JSON.stringify(S.hidden)); break;
    case 'unhideall': S.hidden = {}; localStorage.setItem(LS + 'hidden', '{}'); break;
    case 'copy': navigator.clipboard.writeText(v).then(() => toast('Copied: ' + v), () => toast(v)); return;
    case 'sort': S.sort = v; break;
    case 'invf': S.invFilter = v; break;
    case 'note': S.note = v; localStorage.setItem(LS + 'note', JSON.stringify(v)); break;
    case 'regt': S.regType = v === S.regType ? '' : v; break;
    case 'regs': S.regStatus = v === S.regStatus ? '' : v; break;
    case 'refresh': el.textContent = 'Refreshing…'; (REMOTE ? Promise.resolve('this page updates on its own: the Mac pushes after every Claude turn, GitHub every push and hourly') : fetch('api/refresh').then(r => r.ok ? r.text() : 'unavailable (start serve.sh)')).then(t => { toast('Refresh: ' + t); el.textContent = 'Refresh'; load(); }, () => { toast('Refresh needs serve.sh'); el.textContent = 'Refresh'; }); return;
  }
  render();
});
document.getElementById('views').addEventListener('change', e => setView(e.target.value));
document.getElementById('wins').addEventListener('change', e => { S.win = e.target.value; localStorage.setItem(LS + 'win', JSON.stringify(S.win)); render(); });
document.getElementById('q').addEventListener('input', e => { S.q = e.target.value; render(); });
document.getElementById('ws').addEventListener('change', e => { S.ws = e.target.value; localStorage.setItem(LS + 'ws', JSON.stringify(S.ws)); render(); });
let hovT = null;
document.getElementById('stage').addEventListener('mouseover', e => {
  if (S.view !== 'graph') return;
  const n = e.target.closest('[data-hov]'); const key = n ? n.dataset.hov : null;
  const cur = S.hov ? S.hov.kind + ':' + S.hov.id : null;
  if (key === cur) return;
  clearTimeout(hovT);
  hovT = setTimeout(() => { S.hov = key ? { kind: key.slice(0, 1), id: key.slice(2) } : null; render(); }, key ? 0 : 60);
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { S.sel = null; render(); } });
window.addEventListener('resize', () => { clearTimeout(window.__rz); window.__rz = setTimeout(render, 120); });
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== S.view) { S.view = v; render(); } });
load();
setInterval(load, 30000);
})();
