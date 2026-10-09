/* KS CENTRAL — wizard genérico de formulários em passos.
   Marcação: form[data-wizard] > [data-passo="n"] (seções) + [data-ir-passo="n"] (stepper)
   + [data-wizard-anterior] / [data-wizard-proximo] / [data-wizard-salvar].
   Campos condicionais: [data-mostrar-se="campo=valor|valor2"]. Sem JS, todas as seções aparecem. */
(function () {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  function valorCampo(form, nome) {
    const els = form.elements[nome];
    if (!els) return "";
    if (els instanceof RadioNodeList) return els.value;
    if (els.type === "checkbox") return els.checked ? "on" : "";
    return els.value;
  }

  function condicionais(form) {
    $$("[data-mostrar-se]", form).forEach((el) => {
      const [campo, valores] = el.dataset.mostrarSe.split("=");
      const ok = valores.split("|").includes(valorCampo(form, campo));
      el.hidden = !ok;
    });
  }

  function iniciar(form) {
    const passos = $$("[data-passo]", form);
    const botoes = $$("[data-ir-passo]", form);
    const total = passos.length;
    let atual = Math.min(Math.max(parseInt(form.dataset.passoInicial || "1", 10), 1), total);
    const anterior = $("[data-wizard-anterior]", form);
    const proximo = $("[data-wizard-proximo]", form);
    const salvar = $("[data-wizard-salvar]", form);
    const texto = $("[data-wizard-progresso]", form);

    function mostrar(n, foco) {
      atual = n;
      passos.forEach((p) => { p.hidden = Number(p.dataset.passo) !== n; });
      botoes.forEach((b) => {
        const i = Number(b.dataset.irPasso);
        b.classList.toggle("ativo", i === n);
        b.classList.toggle("feito", i < n && !b.classList.contains("erro"));
        b.setAttribute("aria-current", i === n ? "step" : "false");
      });
      if (anterior) anterior.hidden = n === 1;
      if (proximo) proximo.hidden = n === total;
      if (salvar) salvar.hidden = n !== total;
      if (texto) texto.textContent = `Passo ${n} de ${total}`;
      if (foco) {
        const alvo = $("[data-passo='" + n + "'] h2", form);
        if (alvo) { alvo.setAttribute("tabindex", "-1"); alvo.focus({ preventScroll: true }); }
        form.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }

    function valido(n) {
      const campos = $$("input, select, textarea", $("[data-passo='" + n + "']", form)).filter((c) => !c.disabled && !c.closest("[hidden]:not([data-passo])"));
      for (const c of campos) {
        if (!c.checkValidity()) { c.reportValidity(); return false; }
      }
      return true;
    }

    form.addEventListener("submit", (e) => {
      for (let n = 1; n <= total; n++) {
        if (!valido(n)) { e.preventDefault(); mostrar(n, true); valido(n); return; }
      }
    });
    if (anterior) anterior.addEventListener("click", () => mostrar(Math.max(1, atual - 1), true));
    if (proximo) proximo.addEventListener("click", () => { if (valido(atual)) mostrar(Math.min(total, atual + 1), true); });
    botoes.forEach((b) => b.addEventListener("click", (e) => {
      e.preventDefault();
      const alvo = Number(b.dataset.irPasso);
      if (alvo <= atual || valido(atual)) mostrar(alvo, true);
    }));
    form.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName === "INPUT" && atual < total) {
        e.preventDefault();
        if (valido(atual)) mostrar(atual + 1, true);
      }
    });
    form.addEventListener("change", () => condicionais(form));
    condicionais(form);
    form.classList.add("wizard-ativo");
    mostrar(atual, false);
  }

  /* ---------- Placeholders em textareas ---------- */
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-inserir]");
    if (!b) return;
    e.preventDefault();
    const alvo = document.getElementById(b.dataset.alvo);
    if (!alvo) return;
    const ini = alvo.selectionStart ?? alvo.value.length;
    const fim = alvo.selectionEnd ?? alvo.value.length;
    alvo.value = alvo.value.slice(0, ini) + b.dataset.inserir + alvo.value.slice(fim);
    alvo.focus();
    alvo.selectionStart = alvo.selectionEnd = ini + b.dataset.inserir.length;
    alvo.dispatchEvent(new Event("change", { bubbles: true }));
  });

  /* ---------- Agenda de faturamento: pré-preenchimento pelo contrato ---------- */
  function moeda(v) {
    const n = Number(v);
    return Number.isFinite(n) && v !== "" ? n.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "";
  }
  function dataBr(iso) { return iso ? iso.split("-").reverse().join("/") : "—"; }

  function agenda(form) {
    const fonte = document.getElementById("dados-contratos");
    const sel = form.elements.contrato;
    if (!fonte || !sel) return;
    const dados = JSON.parse(fonte.textContent);
    const ctx = $("[data-contexto-contrato]");
    const empenho = form.elements.empenho;

    function aplicar(preencher) {
      const c = dados[sel.value];
      if (ctx) {
        ctx.hidden = !c;
        if (c) {
          $("[data-ctx=cliente]", ctx).textContent = c.cliente;
          $("[data-ctx=numero]", ctx).textContent = c.numero;
          $("[data-ctx=mensal]", ctx).textContent = c.valor ? "R$ " + moeda(c.valor) : "não informado";
          $("[data-ctx=saldo]", ctx).textContent = "R$ " + moeda(c.saldo);
          $("[data-ctx=vigencia]", ctx).textContent = dataBr(c.inicio) + " → " + dataBr(c.fim);
        }
      }
      if (empenho) {
        Array.from(empenho.options).forEach((o) => {
          if (!o.value) return;
          o.hidden = !!c && !c.empenhos.includes(o.value);
        });
        if (empenho.selectedOptions[0] && empenho.selectedOptions[0].hidden) empenho.value = "";
      }
      if (!c || !preencher) return;
      const set = (nome, valor) => { const el = form.elements[nome]; if (el && valor !== undefined && valor !== null && valor !== "") el.value = valor; };
      set("valor", moeda(c.valor));
      set("dia_emissao", c.dia);
      set("prazo_dias", c.prazo);
      if (!form.elements.inicio.value) set("inicio", c.inicio);
      const disc = form.elements.discriminacao;
      if (disc && !disc.value.trim() && c.discriminacao) disc.value = c.discriminacao;
      form.dispatchEvent(new Event("change", { bubbles: true }));
    }
    sel.addEventListener("change", () => aplicar(true));
    aplicar(false);
  }

  document.addEventListener("DOMContentLoaded", () => {
    $$("form[data-wizard]").forEach(iniciar);
    $$("form[data-agenda]").forEach(agenda);
  });
})();
