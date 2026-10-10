"use strict";
// Auditoria de balancetes — interface. Os números vêm sempre do banco (via /api); nada é calculado no navegador
// além de somas de exibição.

const BRL = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const BRL0 = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
const NUM = new Intl.NumberFormat("pt-BR");
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mesCurto = (ym) => { const [a, m] = ym.split("-"); return `${MESES[+m - 1]}/${a.slice(2)}`; };
const dataBR = (iso) => iso ? iso.slice(0, 10).split("-").reverse().join("/") : "";
const compacto = (v) => Math.abs(v) >= 1e6 ? `R$ ${(v / 1e6).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} mi`
  : Math.abs(v) >= 1e3 ? `R$ ${(v / 1e3).toLocaleString("pt-BR", { maximumFractionDigits: 0 })} mil` : BRL0.format(v);

async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* corpo não é JSON */ }
    throw new Error(msg);
  }
  return r.json();
}

// ---------------------------------------------------------------- cores (tokens CSS)
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const serie = (i) => css(`--s${i}`);
function baseChart() {
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css("--tinta-3");
  Chart.defaults.borderColor = css("--grade");
  Object.assign(Chart.defaults.plugins.tooltip, {
    backgroundColor: css("--cartao"), titleColor: css("--tinta"), bodyColor: css("--tinta-2"),
    borderColor: css("--borda"), borderWidth: 1, padding: 10, boxPadding: 4, usePointStyle: true,
  });
  Chart.defaults.plugins.legend.display = false;
}
const graficos = {};
function grafico(id, cfg) {
  graficos[id]?.destroy();
  graficos[id] = new Chart(document.getElementById(id), cfg);
  return graficos[id];
}
const eixoReais = { grid: { color: () => css("--grade") }, border: { display: false },
  ticks: { callback: (v) => compacto(v), maxTicksLimit: 6 } };
const eixoCat = { grid: { display: false }, border: { color: () => css("--eixo") } };
const barra = { borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start", maxBarThickness: 26 };

// ---------------------------------------------------------------- abas
const carregadas = new Set();
function abrirAba(nome) {
  document.querySelectorAll(".abas button").forEach((b) => b.classList.toggle("ativa", b.dataset.aba === nome));
  document.querySelectorAll(".aba").forEach((s) => s.classList.toggle("ativa", s.id === nome));
  try { localStorage.setItem("aba", nome); } catch { /* sem armazenamento */ }
  if (!carregadas.has(nome)) {
    carregadas.add(nome);
    Promise.resolve(CARGA[nome]?.()).catch((err) => {
      carregadas.delete(nome);
      const sec = document.getElementById(nome);
      sec.querySelector(".erro-aba")?.remove();
      sec.insertAdjacentHTML("afterbegin", `<div class="aviso erro-aba"><div><strong>Não foi possível carregar esta aba.</strong>
        O servidor respondeu: "${esc(err.message)}". Se o site foi atualizado, feche a janela do site e abra de novo
        pelo <em>iniciar_site.bat</em>; depois recarregue esta página (F5).</div></div>`);
    });
  }
}
document.querySelectorAll(".abas button").forEach((b) => b.addEventListener("click", () => abrirAba(b.dataset.aba)));

// ---------------------------------------------------------------- painel
async function carregarPainel() {
  const d = await api("/api/painel");
  const k = d.kpi;
  $("#clube").textContent = d.clube;
  $("#periodo").textContent = `${dataBR(k.inicio)} a ${dataBR(k.fim)}`;
  const selo = $("#selo span");
  selo.textContent = `${d.docs.conciliados} de ${d.docs.arquivos} meses conferidos com o banco`;
  const kpis = [
    ["Entradas", BRL0.format(k.entradas), "receitas no extrato"],
    ["Saídas", BRL0.format(k.saidas), "pagamentos no extrato"],
    ["Resultado", BRL0.format(k.resultado), "entradas − saídas", k.resultado < 0],
    ["Gastos com eventos", BRL0.format(k.eventos || 0), `${((k.eventos || 0) / k.saidas * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })}% das saídas`],
    ["Lançamentos", NUM.format(k.lancamentos), `${d.docs.paginas_ocr} páginas lidas por OCR`],
  ];
  $("#kpis").innerHTML = kpis.map(([r, v, det, neg]) =>
    `<div class="kpi${neg ? " neg" : ""}"><div class="rot">${r}</div><div class="val">${v}</div><div class="det">${esc(det)}</div></div>`).join("");

  const meses = d.mensal.map((m) => mesCurto(m.mes));
  $("#leg-mensal").innerHTML = `<span><i style="background:${serie(1)}"></i>Entradas</span><span><i style="background:${serie(2)}"></i>Saídas</span>`;
  grafico("g-mensal", {
    type: "bar",
    data: { labels: meses, datasets: [
      { label: "Entradas", data: d.mensal.map((m) => m.entradas), backgroundColor: serie(1), ...barra },
      { label: "Saídas", data: d.mensal.map((m) => m.saidas), backgroundColor: serie(2), ...barra },
    ] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      datasets: { bar: { categoryPercentage: 0.7, barPercentage: 0.92 } },
      scales: { x: eixoCat, y: eixoReais },
      plugins: { tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${BRL0.format(c.raw)}`,
        footer: (it) => `Resultado: ${BRL0.format(d.mensal[it[0].dataIndex].resultado)}` } } } },
  });

  grafico("g-grupos", {
    type: "bar",
    data: { labels: d.grupos.map((g) => g.grupo), datasets: [{ data: d.grupos.map((g) => g.total), backgroundColor: serie(1),
      borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "start", maxBarThickness: 26 }] },
    options: { indexAxis: "y", maintainAspectRatio: false,
      scales: { x: eixoReais, y: { ...eixoCat, ticks: { color: css("--tinta-2") } } },
      plugins: { tooltip: { callbacks: { label: (c) => ` ${BRL0.format(c.raw)} · ${NUM.format(d.grupos[c.dataIndex].n)} pagamentos` } } } },
  });

  const alertas = await api("/api/alertas");
  const sic = alertas.find((a) => a.titulo.includes("Sicredi"));
  if (sic) {
    const av = $("#aviso-sicredi");
    av.hidden = false;
    av.innerHTML = `<svg class="ic" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1 15 14H1zM7.3 6v4h1.4V6zm0 5v1.5h1.4V11z"/></svg>
      <div><strong>Atenção ao ler os números de 2026</strong>
      Desde jan/2026 o clube tem contas no Sicredi (registradas no balancete). ${compacto(sic.valor)} foram transferidos
      para elas, e as cobranças de mensalidade deixam de entrar no Santander em mai/2026. Os extratos do Sicredi não estão
      nos balancetes, então o que entra e sai dessas contas não aparece aqui. <a href="#" data-ir="alertas">Ver pontos de atenção</a></div>`;
    av.querySelector("[data-ir]").addEventListener("click", (e) => { e.preventDefault(); abrirAba("alertas"); });
  }
  const ev = await api("/api/eventos/gastos");
  eventosMes("g-eventos-mes", ev, d.mensal.map((m) => m.mes));
}

function eventosMes(id, ev, meses) {
  // até 4 categorias com cor própria; o resto vira "Outras" (nunca gerar hue além da paleta)
  const top = ev.por_categoria.slice(0, 4).map((c) => c.categoria);
  const grupos = [...top, "Outras"];
  const cores = [serie(1), serie(2), serie(3), serie(4), css("--tinta-3")];
  const ds = grupos.map((g, i) => ({
    label: g, backgroundColor: cores[i], borderColor: css("--cartao"), borderWidth: { top: 2 }, borderSkipped: "start", maxBarThickness: 30,
    data: meses.map((m) => ev.por_mes.filter((x) => x.mes === m && (g === "Outras" ? !top.includes(x.categoria) : x.categoria === g))
      .reduce((s, x) => s + x.total, 0)),
  }));
  grafico(id, {
    type: "bar", data: { labels: meses.map(mesCurto), datasets: ds },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { x: { ...eixoCat, stacked: true }, y: { ...eixoReais, stacked: true } },
      plugins: { legend: { display: true, position: "top", align: "start", labels: { boxWidth: 10, boxHeight: 10, color: css("--tinta-2") } },
        tooltip: { filter: (c) => c.raw > 0, callbacks: { label: (c) => ` ${c.dataset.label}: ${BRL0.format(c.raw)}`,
          footer: (it) => `Total: ${BRL0.format(it.reduce((s, c) => s + c.raw, 0))}` } } } },
  });
}

// ---------------------------------------------------------------- eventos
async function carregarEventos() {
  const ev = await api("/api/eventos/gastos");
  grafico("g-ev-cat", {
    type: "bar",
    data: { labels: ev.por_categoria.map((c) => c.categoria), datasets: [{ data: ev.por_categoria.map((c) => c.total),
      backgroundColor: serie(1), borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "start", maxBarThickness: 24 }] },
    options: { indexAxis: "y", maintainAspectRatio: false, scales: { x: eixoReais, y: { ...eixoCat, ticks: { color: css("--tinta-2") } } },
      plugins: { tooltip: { callbacks: { label: (c) => { const x = ev.por_categoria[c.dataIndex];
        return ` ${BRL0.format(x.total)} · ${x.pagamentos} pagamentos · ${x.recebedores} fornecedores`; } } } } },
  });
  const var_ = (a, b) => (a && b) ? `${((b / a - 1) * 100).toLocaleString("pt-BR", { maximumFractionDigits: 0, signDisplay: "always" })}%` : "—";
  $("#t-comparativo").innerHTML = `<thead><tr><th>Categoria</th><th class="num">1º sem. 2025</th><th class="num">1º sem. 2026</th><th class="num">Variação</th></tr></thead><tbody>` +
    ev.comparativo.map((c) => `<tr><td>${esc(c.categoria)}</td><td class="num">${c.s1_2025 ? BRL0.format(c.s1_2025) : "—"}</td>
      <td class="num">${c.s1_2026 ? BRL0.format(c.s1_2026) : "—"}</td><td class="num">${var_(c.s1_2025, c.s1_2026)}</td></tr>`).join("") + "</tbody>";
  $("#t-top-ev").innerHTML = `<thead><tr><th>Fornecedor</th><th>Categoria</th><th class="num">Pagamentos</th><th class="num">Total</th>
      <th class="num">Ticket médio</th><th>Período</th></tr></thead><tbody>` +
    ev.top.map((t) => `<tr class="clicavel" data-q="${esc(t.recebedor)}"><td>${esc(t.recebedor)}</td><td><span class="pilula">${esc(t.categoria)}</span></td>
      <td class="num">${t.pagamentos}</td><td class="num">${BRL0.format(t.total)}</td><td class="num">${BRL0.format(t.ticket_medio)}</td>
      <td class="muted">${dataBR(t.primeiro)} a ${dataBR(t.ultimo)}</td></tr>`).join("") + "</tbody>";
  $("#t-top-ev").querySelectorAll("tr[data-q]").forEach((tr) => tr.addEventListener("click", () => {
    const f = $("#f-filtros"); f.reset(); f.q.value = tr.dataset.q; f.direcao.value = "S";
    abrirAba("transacoes"); buscarTx(0);
  }));
  listarEventos();
}

async function listarEventos() {
  const evs = await api("/api/eventos");
  $("#t-eventos").innerHTML = evs.length ? `<thead><tr><th>Evento</th><th>Data</th><th>Tipo</th><th></th></tr></thead><tbody>` +
    evs.map((e) => `<tr class="clicavel" data-id="${e.id}"><td>${esc(e.nome)}${e.link_instagram ? ` <a href="${esc(e.link_instagram)}" target="_blank" rel="noopener">post</a>` : ""}</td>
      <td class="num">${dataBR(e.data_inicio)}${e.data_fim && e.data_fim !== e.data_inicio ? " a " + dataBR(e.data_fim) : ""}</td>
      <td><span class="pilula">${esc(e.tipo || "")}</span></td><td><button data-apagar="${e.id}" aria-label="Apagar evento">✕</button></td></tr>`).join("") + "</tbody>"
    : `<tbody><tr><td class="muted">Nenhum evento cadastrado ainda.</td></tr></tbody>`;
  $("#t-eventos").querySelectorAll("tr[data-id]").forEach((tr) => tr.addEventListener("click", (e) => {
    if (e.target.dataset.apagar || e.target.tagName === "A") return;
    $("#t-eventos").querySelectorAll("tr").forEach((x) => x.classList.remove("sel"));
    tr.classList.add("sel"); cruzar(tr.dataset.id);
  }));
  $("#t-eventos").querySelectorAll("[data-apagar]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Apagar este evento?")) return;
    await api(`/api/eventos/${b.dataset.apagar}`, { method: "DELETE" }); listarEventos();
  }));
}

let eventoAtual = null;
async function cruzar(id) {
  eventoAtual = id;
  const d = await api(`/api/eventos/${id}/cruzamento?antes=${$("#cz-antes").value}&depois=${$("#cz-depois").value}`);
  $("#cz-titulo").textContent = `Cruzamento: ${d.evento.nome}`;
  $("#cz-sub").textContent = `Gastos com categorias de eventos entre ${d.janela.antes} dias antes e ${d.janela.depois} dias depois de ${dataBR(d.evento.data_inicio)}`;
  $("#cz-total").innerHTML = `${BRL.format(d.total_gastos)}<small>${d.gastos.length} pagamentos na janela</small>`;
  $("#t-cruzamento").innerHTML = `<thead><tr><th>Data</th><th>Fornecedor</th><th>Categoria</th><th class="num">Valor</th></tr></thead><tbody>` +
    d.gastos.map((g) => `<tr class="clicavel" data-tx="${g.id}"><td class="num">${dataBR(g.data_mov)}</td><td>${esc(g.recebedor)}</td>
      <td><span class="pilula">${esc(g.categoria)}</span></td><td class="num">${BRL.format(-g.valor)}</td></tr>`).join("") + "</tbody>";
  ligarPdf($("#t-cruzamento"));
}
["#cz-antes", "#cz-depois"].forEach((s) => $(s).addEventListener("change", () => eventoAtual && cruzar(eventoAtual)));

$("#f-evento").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const corpo = Object.fromEntries([...f.entries()].filter(([, v]) => v !== ""));
  if (corpo.publico_estimado) corpo.publico_estimado = +corpo.publico_estimado;
  try { await api("/api/eventos", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) }); }
  catch (err) { alert("Não foi possível salvar: " + err.message); return; }
  e.target.reset(); listarEventos();
});

// ---------------------------------------------------------------- transações
let txOffset = 0;
const TX_LIM = 200;
async function carregarTransacoes() {
  const op = await api("/api/opcoes");
  const f = $("#f-filtros");
  f.tipo.innerHTML += op.tipos.map((t) => `<option>${esc(t)}</option>`).join("");
  f.categoria.innerHTML += op.categorias.map((c) => `<option>${esc(c.nome)}</option>`).join("") + "<option>Sem categoria</option>";
  buscarTx(0);
}
function paramsTx() {
  return new URLSearchParams([...new FormData($("#f-filtros")).entries()].filter(([, v]) => v !== ""));
}
async function buscarTx(offset) {
  txOffset = Math.max(0, offset);
  const p = paramsTx();
  $("#b-xlsx").href = "/api/transacoes.xlsx?" + p;
  p.set("limite", TX_LIM); p.set("offset", txOffset);
  const d = await api("/api/transacoes?" + p);
  $("#tx-resumo").textContent = `${NUM.format(d.total.n)} lançamentos · saldo líquido ${BRL.format(d.total.soma || 0)}`;
  $("#t-tx").innerHTML = `<thead><tr><th>Data</th><th>Tipo</th><th>Contraparte</th><th>Categoria</th><th class="num">Valor</th><th>Histórico</th><th>Fonte</th></tr></thead><tbody>` +
    d.linhas.map((t) => `<tr class="clicavel" data-tx="${t.id}"><td class="num">${dataBR(t.data_mov)}</td><td><span class="pilula">${esc(t.tipo)}</span></td>
      <td>${esc(t.contraparte || "")}</td><td>${esc(t.categoria || "")}</td>
      <td class="num ${t.valor < 0 ? "neg" : "pos"}">${BRL.format(t.valor)}</td><td class="muted">${esc(t.descricao)}</td>
      <td class="muted">p. ${t.pagina}${t.origem === "ocr" ? " · OCR" : ""}</td></tr>`).join("") + "</tbody>";
  ligarPdf($("#t-tx"));
  const pag = Math.floor(txOffset / TX_LIM) + 1, tot = Math.max(1, Math.ceil(d.total.n / TX_LIM));
  $("#tx-pag").textContent = `página ${pag} de ${tot}`;
  $("#tx-ant").disabled = pag <= 1; $("#tx-prox").disabled = pag >= tot;
}
$("#f-filtros").addEventListener("submit", (e) => { e.preventDefault(); buscarTx(0); });
$("#tx-ant").addEventListener("click", () => buscarTx(txOffset - TX_LIM));
$("#tx-prox").addEventListener("click", () => buscarTx(txOffset + TX_LIM));

// ---------------------------------------------------------------- movimentos selecionados (8 strings)
async function carregarMovimentos() {
  const meses = (await api("/api/balancete?natureza=receita")).meses;
  $("#f-mov").mes.innerHTML += meses.map((m) => { const mm = m.slice(5) + "/" + m.slice(0, 4); return `<option value="${mm}">${mm}</option>`; }).join("");
  buscarMov();
}
async function buscarMov() {
  const p = new URLSearchParams([...new FormData($("#f-mov")).entries()].filter(([, v]) => v !== ""));
  const d = await api("/api/movimentos?" + p);
  $("#t-mov-resumo").innerHTML = `<thead><tr><th>String</th><th class="num">Lançamentos</th><th class="num">Total</th><th class="num">Internos</th></tr></thead><tbody>` +
    d.resumo.map((r) => `<tr><td>${esc(r.string)}</td><td class="num">${NUM.format(r.n)}</td>
      <td class="num ${r.total < 0 ? "neg" : "pos"}">${BRL.format(r.total)}</td><td class="num">${r.internos || "—"}</td></tr>`).join("") + "</tbody>";
  $("#mov-total").textContent = `${NUM.format(d.total.n)} movimentos · soma ${BRL.format(d.total.soma || 0)} · mostrando os ${d.linhas.length} mais recentes`;
  $("#t-mov").innerHTML = `<thead><tr><th>Relatório</th><th class="num">Pág.</th><th>Mês/ano</th><th>Data</th><th>String</th>
    <th class="num">Valor</th><th>Favorecido</th><th>Variante do banco</th></tr></thead><tbody>` +
    d.linhas.map((t) => `<tr class="clicavel" data-tx="${t.id}"><td class="muted">${esc(t.relatorio)}</td><td class="num">${t.pagina}</td>
      <td class="num">${esc(t.mes_ano)}</td><td class="num">${dataBR(t.data_mov)}</td><td><span class="pilula">${esc(t.string)}</span>${t.interno ? ' <span class="pilula">interno</span>' : ""}</td>
      <td class="num ${t.valor < 0 ? "neg" : "pos"}">${BRL.format(t.valor)}</td>
      <td>${esc(t.favorecido || "")}${t.papel === "pagador" ? ' <span class="muted">(pagador)</span>' : ""}</td>
      <td class="muted">${t.variante === "principal" ? "" : esc(t.variante)}</td></tr>`).join("") + "</tbody>";
  ligarPdf($("#t-mov"));
}
$("#f-mov").addEventListener("submit", (e) => { e.preventDefault(); buscarMov(); });

// ---------------------------------------------------------------- balancete (contas da lista)
async function carregarBalancete() {
  const f = $("#f-bal");
  const periodo = new URLSearchParams([["ini", f.ini.value], ["fim", f.fim.value]].filter(([, v]) => v));
  const d = await api(`/api/balancete?natureza=${f.natureza.value}&coluna=${f.coluna.value}&${periodo}`);
  // preenche os seletores de mês uma vez (mantendo a escolha atual)
  if (f.ini.options.length === 1) {
    const opts = d.todos_meses.map((m) => `<option value="${m}">${m.slice(5)}/${m.slice(0, 4)}</option>`).join("");
    f.ini.insertAdjacentHTML("beforeend", opts);
    f.fim.insertAdjacentHTML("beforeend", opts);
  }
  $("#b-bal-xlsx").href = "/api/relatorios/balancete_selecionado.xlsx" + (periodo.toString() ? "?" + periodo : "");
  const fmt = (m) => `${m.slice(5)}/${m.slice(0, 4)}`;
  const txtPeriodo = !d.ini && !d.fim ? "todos os meses"
    : d.ini && d.fim && d.ini === d.fim ? fmt(d.ini)
    : `${d.ini ? fmt(d.ini) : "início"} a ${d.fim ? fmt(d.fim) : "fim"}`;
  $("#bal-nota").textContent = `Contas do Balancete Analítico (contabilidade), separadas dos movimentos bancários. ` +
    `Conferência contábil: ${d.conferencia.ok} de ${d.conferencia.meses} meses com débitos = créditos e totais de grupo batendo.`;
  const nome = { credito: "Crédito", debito: "Débito", saldo_atual: "Saldo atual" }[d.coluna] +
    (d.natureza === "receita" ? " das contas de receita" : " das contas de despesa");
  $("#t-bal").innerHTML = `<thead><tr><th>Código</th><th>String (conta)</th>${d.meses.map((m) => `<th class="num">${mesCurto(m)}</th>`).join("")}
    <th class="num">Total do período</th></tr></thead><tbody>` +
    d.linhas.map((l) => `<tr data-busca="${esc(l.codigo + " " + l.string + " " + (l.grupo || ""))}"${l.tipo === "grupo" ? ' style="font-weight:600"' : ""}><td class="muted">${esc(l.codigo)}</td>
      <td>${l.tipo === "grupo" ? "" : "&nbsp;&nbsp;"}${esc(l.string)}</td>
      ${d.meses.map((m) => { const v = l.valores[m]; return `<td class="num">${v ? NUM.format(Math.round(v)) : '<span class="muted">—</span>'}</td>`; }).join("")}
      <td class="num">${l.total ? BRL0.format(l.total) : "—"}</td></tr>`).join("") + `</tbody>`;
  $("#t-bal").caption?.remove();
  const cap = $("#t-bal").createCaption();
  cap.className = "muted"; cap.style.textAlign = "left"; cap.style.padding = "0 0 8px";
  cap.dataset.base = `${nome} por mês (R$) · período: ${txtPeriodo}. Grupos em negrito; "—" = conta sem movimento no mês.`;
  cap.textContent = cap.dataset.base;
  filtrarBalancete();
}
$("#f-bal").coluna.addEventListener("change", () => abrirDeNovo("balancete"));
$("#f-bal").natureza.addEventListener("change", () => abrirDeNovo("balancete"));
function abrirDeNovo(nome) { carregadas.delete(nome); document.getElementById(nome).querySelector(".erro-aba")?.remove(); abrirAba(nome); }
const semAcento = (t) => String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
function filtrarBalancete() {
  const q = semAcento($("#f-bal").q.value.trim());
  let visiveis = 0;
  document.querySelectorAll("#t-bal tbody tr").forEach((tr) => {
    const ok = !q || semAcento(tr.dataset.busca || "").includes(q);
    tr.hidden = !ok; visiveis += ok;
  });
  const cap = $("#t-bal").caption;
  if (cap) cap.dataset.extra = q ? ` · ${visiveis} conta(s) encontrada(s)` : "";
  if (cap) cap.textContent = cap.dataset.base + (cap.dataset.extra || "");
}
$("#f-bal").q.addEventListener("input", filtrarBalancete);
$("#f-bal").addEventListener("submit", (e) => { e.preventDefault(); abrirDeNovo("balancete"); });
$("#f-bal").ini.addEventListener("change", () => abrirDeNovo("balancete"));
$("#f-bal").fim.addEventListener("change", () => abrirDeNovo("balancete"));
$("#bal-limpar").addEventListener("click", () => {
  const f = $("#f-bal"); f.ini.value = ""; f.fim.value = ""; f.q.value = ""; abrirDeNovo("balancete");
});

// ---------------------------------------------------------------- PDF com a linha destacada
function ligarPdf(tabela) {
  tabela.querySelectorAll("tr[data-tx]").forEach((tr) => tr.addEventListener("click", () => abrirPdf(tr.dataset.tx)));
}
async function abrirPdf(txId) {
  const t = await api(`/api/transacoes/${txId}`);
  $("#d-titulo").textContent = `${t.arquivo} · página ${t.pagina}`;
  $("#d-info").innerHTML = `${dataBR(t.data_mov)} · <strong>${BRL.format(t.valor)}</strong> · ${esc(t.descricao)}
    ${t.origem === "ocr" ? " · <em>lido por OCR</em>" : ""}`;
  $("#d-img").src = `/api/documentos/${t.documento_id}/pagina/${t.pagina}.png?y=${t.linha_y}`;
  $("#d-pdf").showModal();
}
$("#d-fechar").addEventListener("click", () => $("#d-pdf").close());

// ---------------------------------------------------------------- alertas
async function carregarAlertas() {
  const al = await api("/api/alertas");
  const icone = `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1 15 14H1zM7.3 6v4h1.4V6zm0 5v1.5h1.4V11z"/></svg>`;
  const rot = { alto: "Prioridade alta", medio: "Prioridade média", baixo: "Prioridade baixa" };
  $("#lista-alertas").innerHTML = al.map((a, i) => `<div class="alerta">
    <div class="cab"><div><span class="nivel ${a.nivel}">${icone}${rot[a.nivel]}</span><h3>${esc(a.titulo)}</h3></div>
      ${a.valor != null ? `<div class="valor">${BRL0.format(a.valor)}${a.n != null ? ` <small class="muted">· ${NUM.format(a.n)} ${a.unidade || "lançamentos"}</small>` : ""}</div>` : ""}</div>
    <p>${esc(a.texto)}</p>
    <details><summary>Ver detalhes (${a.itens.length})</summary><div class="tabela-wrap"><table id="al-${i}"></table></div></details></div>`).join("");
  al.forEach((a, i) => {
    if (!a.itens.length) return;
    const cols = Object.keys(a.itens[0]).filter((c) => !["id", "documento_id", "pagina", "id_2"].includes(c));
    const fmt = (c, v) => typeof v === "number" && /valor|total|cobranca/.test(c) ? `<td class="num">${BRL.format(v)}</td>`
      : /data/.test(c) ? `<td class="num">${dataBR(v)}</td>` : `<td>${esc(v)}</td>`;
    $(`#al-${i}`).innerHTML = `<thead><tr>${cols.map((c) => `<th>${esc(c.replace(/_/g, " "))}</th>`).join("")}</tr></thead><tbody>` +
      a.itens.map((x) => `<tr ${x.id || x.id_1 ? `class="clicavel" data-tx="${x.id || x.id_1}"` : ""}>${cols.map((c) => fmt(c, x[c])).join("")}</tr>`).join("") + "</tbody>";
    ligarPdf($(`#al-${i}`));
  });
}

// ---------------------------------------------------------------- documentos
async function carregarDocumentos() {
  const docs = await api("/api/documentos");
  const ok = `<span class="nivel" style="color:var(--bom)">✓ conferido</span>`;
  const rev = `<span class="nivel alto">! revisar</span>`;
  $("#t-docs").innerHTML = `<thead><tr><th>Mês</th><th>Arquivo</th><th class="num">Páginas</th><th class="num">Pág. de extrato</th>
    <th class="num">Pág. OCR</th><th class="num">Lançamentos</th><th class="num">Repetidos</th><th>Contas</th><th>Conferência</th><th>Carregado em</th></tr></thead><tbody>` +
    docs.map((d) => `<tr><td class="num">${mesCurto(d.competencia)}</td><td>${esc(d.arquivo)}</td><td class="num">${d.paginas}</td>
      <td class="num">${d.paginas_extrato}</td><td class="num">${d.paginas_ocr || "—"}</td><td class="num">${NUM.format(d.lancamentos)}</td>
      <td class="num">${d.duplicados || "—"}</td><td class="muted">${esc(d.contas || "")}</td>
      <td>${d.conciliado ? ok : rev} <span class="muted">${d.conferencias_ok}/${d.conferencias}</span></td>
      <td class="muted">${dataBR(d.carregado_em)}</td></tr>`).join("") + "</tbody>";
}

// ---------------------------------------------------------------- chat
const SUGESTOES = [
  "Quanto foi gasto com buffet em 2025, mês a mês?",
  "Quais os 10 maiores fornecedores de eventos?",
  "Compare os gastos com bebidas entre o 1º semestre de 2025 e de 2026",
  "Quanto o clube pagou ao maior fornecedor de buffet por mês?",
  "Quais pagamentos acima de R$ 20 mil não têm categoria?",
];
function carregarChat() {
  $("#sugestoes").innerHTML = SUGESTOES.map((s) => `<button type="button">${esc(s)}</button>`).join("");
  $("#sugestoes").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => perguntar(b.textContent)));
}
async function perguntar(texto) {
  const conv = $("#conversa");
  conv.insertAdjacentHTML("beforeend", `<div class="msg-user">${esc(texto)}</div>`);
  const bot = document.createElement("div");
  bot.className = "msg-bot"; bot.innerHTML = `<span class="pensando">Gerando a consulta e calculando no banco…</span>`;
  conv.appendChild(bot); conv.scrollTop = conv.scrollHeight;
  const btn = $("#f-chat button"); btn.disabled = true;
  try {
    const r = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pergunta: texto }) });
    const tabela = r.colunas.length ? `<div class="tabela-wrap"><table><thead><tr>${r.colunas.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>` +
      r.linhas.slice(0, 100).map((l) => `<tr>${l.map((v) => typeof v === "number" ? `<td class="num">${v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}</td>` : `<td>${esc(v)}</td>`).join("")}</tr>`).join("") +
      `</tbody></table></div>` : "";
    bot.innerHTML = r.erro ? `<div class="erro">Não consegui responder: ${esc(r.erro)}</div><details><summary>SQL tentado</summary><pre>${esc(r.sql)}</pre></details>`
      : `<div class="resp">${esc(r.resposta || "")}</div>${tabela}
        <details><summary>Como foi calculado (SQL)</summary><p class="muted">${esc(r.explicacao || "")}</p><pre>${esc(r.sql)}</pre></details>
        <div class="acoes"><a class="botao" href="/api/chat/${r.id}.xlsx">Baixar Excel</a><a class="botao" href="/api/chat/${r.id}.txt">Baixar texto</a>
        <span class="muted">${r.linhas.length} linhas · ${esc(r.modelo)}${r.verificada ? " · ✓ números da resposta conferidos com a tabela" : ""}</span></div>`;
  } catch (err) {
    bot.innerHTML = `<div class="erro">Erro: ${esc(err.message)}</div>`;
  } finally { btn.disabled = false; conv.scrollTop = conv.scrollHeight; }
}
$("#f-chat").addEventListener("submit", (e) => {
  e.preventDefault(); const i = e.target.pergunta; const t = i.value.trim(); if (t) { i.value = ""; perguntar(t); }
});

// ---------------------------------------------------------------- início
const CARGA = { painel: carregarPainel, eventos: carregarEventos, transacoes: carregarTransacoes,
  movimentos: carregarMovimentos, balancete: carregarBalancete,
  alertas: carregarAlertas, documentos: carregarDocumentos, chat: carregarChat };
baseChart();
let inicial = "painel";
try { inicial = localStorage.getItem("aba") || "painel"; } catch { /* sem armazenamento */ }
if (inicial !== "painel") carregarPainelSelo();
abrirAba(inicial);
async function carregarPainelSelo() {
  const d = await api("/api/painel");
  $("#selo span").textContent = `${d.docs.conciliados} de ${d.docs.arquivos} meses conferidos com o banco`;
}
