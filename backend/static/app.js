const resultsEl = document.getElementById("results");
const similarPanelEl = document.getElementById("similarPanel");
const industrySelect = document.getElementById("industry");

const AVATAR_PALETTE = [
  ["#6366f1", "#a5b4fc"], // indigo
  ["#ec4899", "#f9a8d4"], // pink
  ["#0ea5e9", "#7dd3fc"], // sky
  ["#10b981", "#6ee7b7"], // emerald
  ["#f59e0b", "#fcd34d"], // amber
  ["#8b5cf6", "#c4b5fd"], // violet
  ["#ef4444", "#fca5a5"], // red
  ["#14b8a6", "#5eead4"], // teal
];

function hashString(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i);
    hash |= 0;
  }
  return Math.abs(hash);
}

function avatarHtml(name, code) {
  const [from, to] = AVATAR_PALETTE[hashString(code) % AVATAR_PALETTE.length];
  const initials = name.slice(0, 2);
  return `
    <div class="shrink-0 w-12 h-12 rounded-2xl flex items-center justify-center text-white font-bold text-sm shadow-sm"
      style="background: linear-gradient(135deg, ${from}, ${to});">
      ${initials}
    </div>`;
}

function industryChip(industry) {
  if (!industry) return "";
  const hue = hashString(industry) % 360;
  const label = industry.length > 12 ? industry.slice(0, 12) + "…" : industry;
  return `<span class="text-[11px] font-medium px-2 py-0.5 rounded-full whitespace-nowrap max-w-full overflow-hidden text-ellipsis"
    style="background: hsl(${hue} 85% 95%); color: hsl(${hue} 60% 35%);">${label}</span>`;
}

function changeBadge(changeRate) {
  if (changeRate === null || changeRate === undefined) {
    return `<span class="text-xs text-slate-400">-</span>`;
  }
  const up = changeRate > 0;
  const flat = changeRate === 0;
  const color = flat ? "text-slate-400" : up ? "text-rose-600" : "text-blue-600";
  const arrow = flat ? "" : up ? "▲" : "▼";
  return `<span class="text-xs font-semibold ${color}">${arrow} ${Math.abs(changeRate).toFixed(2)}%</span>`;
}

async function loadIndustries() {
  const res = await fetch("/api/industries");
  const industries = await res.json();
  for (const ind of industries) {
    const opt = document.createElement("option");
    opt.value = ind;
    opt.textContent = ind;
    industrySelect.appendChild(opt);
  }
}

function stockCard(stock) {
  const div = document.createElement("div");
  div.className =
    "bg-white rounded-2xl shadow-sm border border-slate-100 p-4 hover:shadow-md hover:border-indigo-100 transition";
  div.innerHTML = `
    <div class="flex gap-3">
      ${avatarHtml(stock.name, stock.code)}
      <div class="flex-1 min-w-0">
        <div class="flex items-baseline gap-1.5">
          <span class="font-semibold text-slate-800 truncate">${stock.name}</span>
          <span class="text-xs text-slate-400 shrink-0">${stock.code}</span>
        </div>
        <div class="mt-1.5 flex items-center gap-1.5 flex-wrap">
          <span class="text-[11px] text-slate-400 whitespace-nowrap">${stock.market}</span>
          ${industryChip(stock.industry)}
        </div>
        <div class="flex items-center justify-between mt-3 pt-3 border-t border-slate-50">
          <div>
            <div class="text-sm font-semibold text-slate-800">${stock.close_price ? stock.close_price.toLocaleString() + "원" : "-"}</div>
            <div class="mt-0.5">${changeBadge(stock.change_rate)}</div>
          </div>
          <button class="shrink-0 bg-slate-50 hover:bg-indigo-50 hover:text-indigo-600 text-slate-600 text-xs font-medium px-3 py-2 rounded-xl border border-slate-200 transition">
            유사 종목
          </button>
        </div>
      </div>
    </div>
  `;
  div.querySelector("button").addEventListener("click", () => showSimilar(stock.code));
  return div;
}

async function search() {
  const q = document.getElementById("q").value.trim();
  const minPrice = document.getElementById("minPrice").value;
  const maxPrice = document.getElementById("maxPrice").value;
  const industry = industrySelect.value;

  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (minPrice) params.set("min_price", minPrice);
  if (maxPrice) params.set("max_price", maxPrice);
  if (industry) params.set("industry", industry);
  params.set("limit", "8");

  resultsEl.innerHTML = `<div class="text-sm text-slate-400 px-1">검색 중...</div>`;
  similarPanelEl.innerHTML = "";

  const res = await fetch(`/api/search?${params.toString()}`);
  const stocks = await res.json();

  resultsEl.innerHTML = "";
  if (stocks.length === 0) {
    resultsEl.innerHTML = `<div class="text-sm text-slate-400 px-1">조건에 맞는 종목이 없습니다.</div>`;
    return;
  }
  for (const stock of stocks) {
    resultsEl.appendChild(stockCard(stock));
  }
}

function peerRow(peer) {
  return `
    <div class="border-b border-slate-100 last:border-0 py-2.5">
      <div class="flex gap-3">
        ${avatarHtml(peer.name, peer.code)}
        <div class="flex-1 min-w-0">
          <div class="flex items-baseline gap-1.5">
            <span class="text-sm font-medium text-slate-800 truncate">${peer.name}</span>
            <span class="text-slate-400 text-xs shrink-0">${peer.code}</span>
          </div>
          <div class="flex items-center justify-between gap-2 mt-1">
            ${industryChip(peer.industry)}
            <div class="text-right shrink-0">
              <div class="text-sm text-slate-700">${peer.close_price ? peer.close_price.toLocaleString() + "원" : "-"}</div>
              ${changeBadge(peer.change_rate)}
            </div>
          </div>
        </div>
      </div>
    </div>`;
}

async function showSimilar(code) {
  similarPanelEl.innerHTML = `<div class="text-sm text-slate-400 px-1">불러오는 중...</div>`;
  const res = await fetch(`/api/similar/${code}`);
  if (!res.ok) {
    similarPanelEl.innerHTML = `<div class="text-sm text-red-500 px-1">종목 정보를 불러올 수 없습니다.</div>`;
    return;
  }
  const data = await res.json();
  const { stock, similar } = data;

  const wrap = document.createElement("div");
  wrap.className = "bg-white rounded-2xl shadow-sm border border-slate-100 p-5";
  wrap.innerHTML = `
    <div class="flex items-center justify-between mb-3 gap-3 flex-wrap">
      <div class="flex items-center gap-3">
        ${avatarHtml(stock.name, stock.code)}
        <div>
          <h2 class="font-bold text-slate-800">${stock.name} <span class="text-slate-400 text-xs font-normal">${stock.code}</span></h2>
          <p class="text-xs text-slate-400">과(와) 같은 분야의 종목 ${similar.length}개</p>
        </div>
      </div>
      <button id="unlockBtn" class="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-600 hover:to-orange-600 text-white text-sm font-semibold px-4 py-2 rounded-xl shadow-sm">
        🚀 동반 상승 통계 · 업종 추이 보기
      </button>
    </div>
    <div>
      ${
        similar.length === 0
          ? `<div class="text-sm text-slate-400 py-2">같은 분야의 다른 종목을 찾지 못했습니다.</div>`
          : similar.map(peerRow).join("")
      }
    </div>
  `;
  similarPanelEl.innerHTML = "";
  similarPanelEl.appendChild(wrap);

  document.getElementById("unlockBtn").addEventListener("click", () => {
    window.location.href = `/static/result.html?code=${stock.code}`;
  });
  similarPanelEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.getElementById("searchBtn").addEventListener("click", search);
document.getElementById("q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") search();
});

loadIndustries();
search();
