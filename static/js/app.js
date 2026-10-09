/* KS CENTRAL — comportamento da interface (sem scripts inline; compatível com CSP restritiva).
 * Sidebar, busca global (Ctrl+K), atalhos, toasts, máscaras BRL/CPF/CNPJ/CEP, consulta CNPJ/CEP,
 * dropdowns, modais de confirmação, linhas clicáveis, tema e gráficos (Chart.js). */
(function () {
  "use strict";
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || ($("[name=csrfmiddlewaretoken]") || {}).value || "";
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } },
  };

  /* ---------------- Toasts ---------------- */
  function toast(msg, nivel, desfazerUrl) {
    let box = $(".toasts");
    if (!box) { box = document.createElement("div"); box.className = "toasts"; box.setAttribute("aria-live", "polite"); document.body.appendChild(box); }
    const t = document.createElement("div");
    t.className = "toast " + (nivel || "info");
    t.setAttribute("role", "status");
    const span = document.createElement("span"); span.textContent = msg; t.appendChild(span);
    if (desfazerUrl) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = "Desfazer";
      b.addEventListener("click", () => post(desfazerUrl).then(() => location.reload()));
      t.appendChild(b);
    }
    box.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }
  window.ksToast = toast;
  function post(url, dados) {
    return fetch(url, { method: "POST", headers: { "X-CSRFToken": csrf(), "X-Requested-With": "fetch" }, body: dados || new FormData() });
  }
  $$("[data-toast]").forEach((el) => { toast(el.dataset.toast, el.dataset.nivel, el.dataset.desfazer); el.remove(); });

  /* ---------------- Tema ---------------- */
  const raiz = document.documentElement;
  $$("[data-alternar-tema]").forEach((b) => b.addEventListener("click", () => {
    const novo = raiz.dataset.theme === "dark" ? "light" : "dark";
    raiz.dataset.theme = novo;
    store.set("ks-tema", novo);
    post(b.dataset.alternarTema, (() => { const f = new FormData(); f.append("tema", novo === "dark" ? "escuro" : "claro"); return f; })());
  }));

  /* ---------------- Sidebar ---------------- */
  const shell = $(".shell");
  if (shell && store.get("ks-sidebar") === "recolhida" && window.innerWidth > 767) shell.classList.add("recolhida");
  $$("[data-recolher-sidebar]").forEach((b) => b.addEventListener("click", () => {
    shell.classList.toggle("recolhida");
    store.set("ks-sidebar", shell.classList.contains("recolhida") ? "recolhida" : "aberta");
  }));
  $$("[data-abrir-menu]").forEach((b) => b.addEventListener("click", () => shell.classList.toggle("drawer-aberto")));
  document.addEventListener("click", (e) => {
    if (shell && shell.classList.contains("drawer-aberto") && !e.target.closest(".sidebar") && !e.target.closest("[data-abrir-menu]")) shell.classList.remove("drawer-aberto");
  });

  /* ---------------- Dropdowns ---------------- */
  document.addEventListener("click", (e) => {
    const gat = e.target.closest("[data-dropdown]");
    $$(".dropdown-menu").forEach((m) => { if (!gat || m !== gat.parentElement.querySelector(".dropdown-menu")) m.classList.add("hidden"); });
    if (gat) { e.preventDefault(); gat.parentElement.querySelector(".dropdown-menu").classList.toggle("hidden"); }
  });

  /* ---------------- Linhas clicáveis ---------------- */
  document.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-href]");
    if (tr && !e.target.closest("a,button,input,label,select")) {
      if (e.ctrlKey || e.metaKey) window.open(tr.dataset.href, "_blank"); else location.href = tr.dataset.href;
    }
  });

  /* ---------------- Modal de confirmação ---------------- */
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (!f.dataset.confirmar || f.dataset.confirmado) return;
    e.preventDefault();
    abrirConfirmacao(f);
  });
  function abrirConfirmacao(form) {
    const fundo = document.createElement("div"); fundo.className = "modal-fundo";
    const m = document.createElement("div"); m.className = "modal"; m.setAttribute("role", "dialog"); m.setAttribute("aria-modal", "true");
    const h = document.createElement("h3"); h.textContent = form.dataset.confirmarTitulo || "Confirmar ação"; m.appendChild(h);
    const p = document.createElement("p"); p.className = "muted"; p.textContent = form.dataset.confirmar; m.appendChild(p);
    let campo = null;
    const exigir = form.dataset.confirmarDigitar;
    if (exigir) {
      const l = document.createElement("label"); l.className = "small"; l.textContent = `Digite ${exigir} para confirmar:`; m.appendChild(l);
      campo = document.createElement("input"); campo.className = "input mono"; campo.autocomplete = "off"; m.appendChild(campo);
    }
    const acoes = document.createElement("div"); acoes.className = "form-acoes";
    const c = document.createElement("button"); c.type = "button"; c.className = "btn"; c.textContent = "Cancelar";
    const ok = document.createElement("button"); ok.type = "button"; ok.className = form.dataset.confirmarPerigo === "0" ? "btn btn-primario" : "btn btn-perigo";
    ok.textContent = form.dataset.confirmarBotao || "Confirmar";
    if (exigir) { ok.disabled = true; campo.addEventListener("input", () => { ok.disabled = campo.value.trim() !== exigir; }); }
    acoes.append(c, ok); m.appendChild(acoes);
    const fechar = () => { fundo.remove(); m.remove(); };
    c.addEventListener("click", fechar); fundo.addEventListener("click", fechar);
    ok.addEventListener("click", () => { form.dataset.confirmado = "1"; fechar(); form.requestSubmit ? form.requestSubmit() : form.submit(); });
    document.body.append(fundo, m);
    (campo || ok).focus();
  }

  /* ---------------- Busca global (Ctrl+K) ---------------- */
  let buscaAberta = null;
  function abrirBusca() {
    if (buscaAberta) return;
    const url = document.body.dataset.urlBusca;
    if (!url) return;
    const fundo = document.createElement("div"); fundo.className = "modal-fundo";
    const m = document.createElement("div"); m.className = "busca-modal"; m.setAttribute("role", "dialog");
    const inp = document.createElement("input"); inp.placeholder = "Buscar notas, contratos, clientes, tarefas…"; inp.setAttribute("aria-label", "Busca global");
    const res = document.createElement("div"); res.className = "busca-resultados";
    m.append(inp, res); document.body.append(fundo, m); inp.focus();
    let timer = null, sel = -1;
    const fechar = () => { fundo.remove(); m.remove(); buscaAberta = null; };
    buscaAberta = fechar;
    fundo.addEventListener("click", fechar);
    inp.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => fetch(url + "?q=" + encodeURIComponent(inp.value), { headers: { "HX-Request": "true" } })
        .then((r) => r.text()).then((html) => { res.innerHTML = html; sel = -1; }), 200);
    });
    inp.addEventListener("keydown", (e) => {
      const links = $$("a", res);
      if (e.key === "Escape") fechar();
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault(); if (!links.length) return;
        sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + links.length) % links.length;
        links.forEach((a, i) => a.classList.toggle("sel", i === sel));
      } else if (e.key === "Enter" && links[Math.max(sel, 0)]) location.href = links[Math.max(sel, 0)].href;
    });
  }
  $$("[data-abrir-busca]").forEach((b) => b.addEventListener("click", abrirBusca));

  /* ---------------- Atalhos ---------------- */
  let prefixoG = false;
  document.addEventListener("keydown", (e) => {
    const alvo = e.target;
    const digitando = alvo.closest && alvo.closest("input,textarea,select,[contenteditable]");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); abrirBusca(); return; }
    if (e.key === "Escape") { if (buscaAberta) buscaAberta(); $$(".dropdown-menu").forEach((m) => m.classList.add("hidden")); return; }
    if (digitando || e.ctrlKey || e.metaKey || e.altKey) return;
    if (prefixoG) {
      prefixoG = false;
      const destino = { c: "urlContratos", f: "urlFiscal", p: "urlPainel", t: "urlTarefas", r: "urlFinanceiro" }[e.key.toLowerCase()];
      if (destino && document.body.dataset[destino]) location.href = document.body.dataset[destino];
      return;
    }
    if (e.key === "g" || e.key === "G") { prefixoG = true; setTimeout(() => { prefixoG = false; }, 1200); return; }
    if (e.key === "n" || e.key === "N") { const b = $("#botao-novo"); if (b) { e.preventDefault(); b.click(); } return; }
    if (e.key === "?") { const m = $("#atalhos"); if (m) m.classList.toggle("hidden"); }
  });
  $$("[data-fechar]").forEach((b) => b.addEventListener("click", () => $(b.dataset.fechar).classList.add("hidden")));

  /* ---------------- Máscaras ---------------- */
  const digitos = (v) => (v || "").replace(/\D/g, "");
  function mascaraDoc(v) {
    const d = digitos(v).slice(0, 14);
    if (d.length <= 11) return d.replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d)/, "$1.$2").replace(/(\d{3})(\d{1,2})$/, "$1-$2");
    return d.replace(/^(\d{2})(\d)/, "$1.$2").replace(/^(\d{2})\.(\d{3})(\d)/, "$1.$2.$3").replace(/\.(\d{3})(\d)/, ".$1/$2").replace(/(\d{4})(\d)/, "$1-$2");
  }
  function mascaraMoney(v) {
    if (!v) return "";
    // aceita colar "1.234,56", "1234.56" ou "1234,5"
    let s = String(v).trim().replace(/[^\d,.-]/g, "");
    if (s.includes(",")) s = s.replace(/\./g, "").replace(",", ".");
    const n = Number(s);
    if (isNaN(n)) return v;
    return n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: Math.max(2, (s.split(".")[1] || "").length > 2 ? 4 : 2) });
  }
  function aplicarMascaras(raizEl) {
    $$("[data-mask=doc]", raizEl).forEach((i) => { i.value = mascaraDoc(i.value); i.addEventListener("input", () => { i.value = mascaraDoc(i.value); }); });
    $$("[data-mask=cep]", raizEl).forEach((i) => i.addEventListener("input", () => { i.value = digitos(i.value).slice(0, 8).replace(/(\d{5})(\d)/, "$1-$2"); }));
    $$("[data-mask=money]", raizEl).forEach((i) => { if (i.value) i.value = mascaraMoney(i.value); i.addEventListener("blur", () => { i.value = mascaraMoney(i.value); }); });
  }
  aplicarMascaras(document);
  document.body.addEventListener("htmx:afterSwap", (e) => { aplicarMascaras(e.target); desenharGraficos(e.target); });

  /* ---------------- Consulta CNPJ e CEP ---------------- */
  function preencher(form, dados, prefixo) {
    Object.entries(dados).forEach(([k, v]) => {
      if (v && typeof v === "object") return preencher(form, v, prefixo);
      const el = form.querySelector(`[name="${(prefixo || "") + k}"]`);
      if (!el || v === null || v === undefined || v === "") return;
      if (el.type === "checkbox") el.checked = !!v; else el.value = v;
      el.dispatchEvent(new Event("input"));
    });
  }
  document.addEventListener("focusout", (e) => {
    const i = e.target;
    if (!i.matches || !i.form) return;
    if (i.matches("[data-consulta-cnpj]") && digitos(i.value).length === 14) {
      const status = i.form.querySelector("[data-status-consulta]");
      if (status) status.textContent = "Consultando CNPJ…";
      fetch(i.dataset.consultaCnpj + "?cnpj=" + digitos(i.value)).then((r) => r.json()).then((d) => {
        if (d.erro) { if (status) status.textContent = d.erro; toast(d.erro, "warning"); return; }
        preencher(i.form, d);
        if (status) status.textContent = d.situacao ? `Situação na Receita: ${d.situacao}` : "";
        toast("Dados preenchidos a partir da Receita Federal.", "success");
      }).catch(() => { if (status) status.textContent = ""; });
    }
    if (i.matches("[data-consulta-cep]") && digitos(i.value).length === 8) {
      fetch(i.dataset.consultaCep + "?cep=" + digitos(i.value)).then((r) => r.json()).then((d) => { if (!d.erro) preencher(i.form, d); });
    }
  });

  /* ---------------- Gráficos (Chart.js) ---------------- */
  function desenharGraficos(raizEl) {
    if (!window.Chart) return;
    const css = getComputedStyle(document.documentElement);
    const cor = (n) => css.getPropertyValue(n).trim();
    Chart.defaults.font.family = cor("--font-ui");
    Chart.defaults.color = cor("--muted");
    $$("canvas[data-grafico]", raizEl).forEach((c) => {
      if (c._chart) return;
      const cfg = JSON.parse(document.getElementById(c.dataset.grafico).textContent);
      const paleta = [cor("--primary"), cor("--accent"), cor("--gold"), cor("--navy-600"), cor("--success"), cor("--danger")];
      (cfg.data.datasets || []).forEach((ds, i) => {
        const base = ds.cor ? cor(ds.cor) || ds.cor : paleta[i % paleta.length];
        ds.backgroundColor = ds.backgroundColor || (cfg.type === "line" ? base + "22" : base);
        ds.borderColor = ds.borderColor || base;
        ds.borderRadius = cfg.type === "bar" ? 6 : undefined;
        delete ds.cor;
      });
      cfg.options = Object.assign({ responsive: true, maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10, usePointStyle: true } } },
        scales: cfg.type === "doughnut" ? {} : { y: { grid: { color: cor("--line") }, ticks: { callback: (v) => cfg.moeda ? "R$ " + Number(v).toLocaleString("pt-BR") : v } }, x: { grid: { display: false } } } }, cfg.options || {});
      c._chart = new Chart(c, cfg);
    });
  }
  window.addEventListener("load", () => desenharGraficos(document));

  /* ---------------- Utilidades ---------------- */
  $$("[data-copiar]").forEach((b) => b.addEventListener("click", () => {
    navigator.clipboard.writeText(b.dataset.copiar).then(() => toast("Copiado.", "success"));
  }));
  $$("[data-auto-submit]").forEach((el) => el.addEventListener("change", () => el.form.requestSubmit()));
  document.body.addEventListener("htmx:configRequest", (e) => { e.detail.headers["X-CSRFToken"] = csrf(); });
})();
