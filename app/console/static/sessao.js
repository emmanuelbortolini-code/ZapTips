// Modo sessao da aba Envio (Fase 5d-D) - primeiro JS do projeto.
// Cosmetico, nunca fonte de verdade: toda mutacao real (marcar enviada,
// pular, iniciar/pausar/retomar/encerrar sessao) e um POST de formulario
// nativo, igual ao resto do console. Este script so controla o
// contador visual e um atalho de teclado - se ele falhar ou for
// desabilitado no navegador, a pagina continua 100% operavel (os
// botoes sao renderizados HABILITADOS pelo servidor; e este script que
// os desabilita durante a contagem).
(function () {
  "use strict";

  var root = document.getElementById("sessao-root");
  if (!root) return; // pagina sem parada em foco (resumo ou tela de iniciar) - nada a fazer.

  var intervaloSegundos = parseInt(root.dataset.intervaloSegundos, 10) || 0;
  var contagemEl = document.getElementById("sessao-contagem");
  var pularBtn = document.getElementById("sessao-pular-intervalo");

  // So um timestamp epoch em sessionStorage - nada de telefone, nome,
  // corpo de mensagem ou message_id sai do Postgres pro navegador.
  // Sobrevive a um F5 no meio da contagem; nunca usado como fonte da
  // parada/posicao em si (isso sempre vem renderizado pelo servidor).
  var STORAGE_KEY = "zaptips_sessao_deadline";

  function botoesEnviar() {
    return Array.prototype.slice.call(root.querySelectorAll("form[action*='/enviada'] button[type='submit']"));
  }

  function setDeadline(deadlineMs) {
    try {
      sessionStorage.setItem(STORAGE_KEY, String(deadlineMs));
    } catch (e) {
      // sessionStorage indisponivel (modo privado etc.) - degrada sem
      // persistir a contagem entre reloads, sem quebrar a pagina.
    }
  }

  function lerDeadline() {
    try {
      var valor = sessionStorage.getItem(STORAGE_KEY);
      return valor ? parseInt(valor, 10) : null;
    } catch (e) {
      return null;
    }
  }

  function liberar() {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // ignora - mesma degradacao de setDeadline.
    }
    if (contagemEl) contagemEl.textContent = "";
    botoesEnviar().forEach(function (btn) {
      btn.disabled = false;
    });
  }

  function atualizar() {
    var deadline = lerDeadline();
    if (deadline === null) return;
    var restanteMs = deadline - Date.now();
    if (restanteMs <= 0) {
      liberar();
      return;
    }
    if (contagemEl) contagemEl.textContent = "libera em " + Math.ceil(restanteMs / 1000) + "s";
    botoesEnviar().forEach(function (btn) {
      btn.disabled = true;
    });
  }

  if (intervaloSegundos > 0) {
    if (lerDeadline() === null) {
      setDeadline(Date.now() + intervaloSegundos * 1000);
    }
    atualizar();
    setInterval(atualizar, 500);
  }

  if (pularBtn) {
    // Nunca desabilita "Pular" nem o link do WhatsApp - so o intervalo
    // de "marcar como enviada" e protegido por esta contagem.
    pularBtn.addEventListener("click", liberar);
  }

  document.addEventListener("keydown", function (evento) {
    if (evento.key !== "Enter") return;
    var alvo = evento.target;
    var tag = alvo && alvo.tagName ? alvo.tagName.toLowerCase() : "";
    // Nunca roubar Enter de dentro do campo de motivo do "Pular" - os
    // dois formularios estao no mesmo card.
    if (tag === "input" || tag === "textarea") return;

    var botoes = botoesEnviar();
    if (botoes.length === 0 || botoes[0].disabled) return;
    var form = botoes[0].form;
    if (form.requestSubmit) {
      form.requestSubmit(botoes[0]);
    } else {
      botoes[0].click();
    }
  });
})();
