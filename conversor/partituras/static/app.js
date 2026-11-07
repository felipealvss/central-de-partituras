'use strict';
/* Central de Partituras — interface.
   Textos vindos do usuário (títulos, nomes de arquivo) entram sempre por textContent, nunca por innerHTML. */

const $ = (s, r = document) => r.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';

function limpos(lista) { return lista.flat(Infinity).filter(x => x !== null && x !== undefined && x !== false); }
function el(tag, attrs = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'style') e.style.cssText = v;
    else if (v === true) e.setAttribute(k, '');
    else e.setAttribute(k, v);
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    e.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return e;
}
function svg(tag, attrs = {}, ...filhos) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
  for (const f of filhos.flat()) if (f) e.append(f instanceof Node ? f : document.createTextNode(String(f)));
  return e;
}

/* ------------------------------------------------------------------ estado e API */
const est = {
  musicas: [], selecionada: null, filtro: 'todas', busca: '', vista: 'musicas',
  fila: { atual: null, fila: [] }, motores: {}, revisoes: null, entradaQtd: -1, saidaPadrao: '',
  entrada: { fotos: [], grupos: [], limiar: 90 }, grupos: null, selecaoExport: new Set(),
  conferencias: {}, tabela: {}, pendente: false, correcoes: {},
};

async function api(metodo, url, corpo) {
  const op = { method: metodo, headers: {}, credentials: 'same-origin' };
  if (metodo !== 'GET') op.headers['X-Central'] = '1';
  if (corpo !== undefined) { op.headers['Content-Type'] = 'application/json'; op.body = JSON.stringify(corpo); }
  const r = await fetch(url, op);
  let dados = null;
  try { dados = await r.json(); } catch { /* sem corpo */ }
  if (!r.ok) {
    const e = new Error((dados && dados.erro) || `Erro ${r.status}`);
    e.status = r.status; e.dados = dados;
    throw e;
  }
  return dados;
}

function aviso(texto, tipo = 'info', ms = 6000) {
  const a = el('div', { class: `aviso ${tipo}`, role: tipo === 'erro' ? 'alert' : 'status' }, texto);
  $('#avisos').append(a);
  setTimeout(() => a.remove(), ms);
}
function falhou(e) { aviso(e.message || String(e), 'erro', 9000); }

const enc = encodeURIComponent;
const musicaSel = () => est.musicas.find(m => m.id === est.selecionada) || null;
const ocupada = m => ['na_fila', 'convertendo'].includes(m.estado) ||
  (est.fila.atual && est.fila.atual.musica === m.id) || est.fila.fila.some(j => j.musica === m.id);

function hora(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}
function soHora(iso) { return iso ? new Date(iso).toLocaleTimeString('pt-BR') : ''; }
function nomeArquivo(caminho) { return (caminho || '').split('/').pop(); }
function curto(caminho) { return est.casa && caminho && caminho.startsWith(est.casa) ? '~' + caminho.slice(est.casa.length) : caminho; }

/* ------------------------------------------------------------------ status: ícone + rótulo, nunca só cor */
const ESTADOS = {
  nova: ['Nova', 'circulo'], na_fila: ['Na fila', 'relogio'], convertendo: ['Convertendo', 'gira'],
  rascunho: ['Rascunho', 'documento'], rascunho_alertas: ['A revisar', 'aviso'], revisada: ['Revisada', 'certo'],
  erro: ['Erro', 'erro'], cancelada: ['Cancelada', 'pausa'], interrompida: ['Interrompida', 'pausa'],
};
function icone(nome) {
  const s = svg('svg', { viewBox: '0 0 16 16', 'aria-hidden': 'true' });
  const t = 'var(--tinta-2)';
  const add = (tag, a) => s.append(svg(tag, a));
  switch (nome) {
    case 'circulo': add('circle', { cx: 8, cy: 8, r: 6, fill: 'none', stroke: t, 'stroke-width': 1.6 }); break;
    case 'relogio':
      add('circle', { cx: 8, cy: 8, r: 6.2, fill: 'none', stroke: t, 'stroke-width': 1.5 });
      add('path', { d: 'M8 4.5V8l2.5 1.6', fill: 'none', stroke: t, 'stroke-width': 1.5, 'stroke-linecap': 'round' }); break;
    case 'gira':
      add('path', { d: 'M8 2a6 6 0 1 1-6 6', fill: 'none', stroke: 'var(--destaque)', 'stroke-width': 2, 'stroke-linecap': 'round', class: 'gira' }); break;
    case 'documento':
      add('path', { d: 'M4 1.5h5.5L12.5 4.5v10h-8.5z', fill: 'none', stroke: t, 'stroke-width': 1.4, 'stroke-linejoin': 'round' });
      add('path', { d: 'M6 8h4.5M6 10.5h4.5', stroke: t, 'stroke-width': 1.2 }); break;
    case 'aviso':
      add('path', { d: 'M8 1.6 15 14.2H1z', fill: 'var(--aviso)', stroke: 'var(--tinta)', 'stroke-width': 1, 'stroke-linejoin': 'round' });
      add('path', { d: 'M8 6v4', stroke: '#0b0b0b', 'stroke-width': 1.6, 'stroke-linecap': 'round' });
      add('circle', { cx: 8, cy: 12.1, r: 0.9, fill: '#0b0b0b' }); break;
    case 'certo':
      add('circle', { cx: 8, cy: 8, r: 7, fill: 'var(--bom)' });
      add('path', { d: 'M4.6 8.2l2.2 2.2 4.4-4.8', fill: 'none', stroke: '#fff', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }); break;
    case 'erro':
      add('circle', { cx: 8, cy: 8, r: 7, fill: 'var(--critico)' });
      add('path', { d: 'M5.4 5.4l5.2 5.2M10.6 5.4l-5.2 5.2', stroke: '#fff', 'stroke-width': 1.8, 'stroke-linecap': 'round' }); break;
    case 'pausa':
      add('circle', { cx: 8, cy: 8, r: 6.2, fill: 'none', stroke: 'var(--apagado)', 'stroke-width': 1.5 });
      add('path', { d: 'M6.5 5.5v5M9.5 5.5v5', stroke: 'var(--apagado)', 'stroke-width': 1.6 }); break;
  }
  return s;
}
function status(estado, grande = false) {
  const [rotulo, ic] = ESTADOS[estado] || [estado, 'circulo'];
  return el('span', { class: `status${grande ? ' grande' : ''}` }, icone(ic), rotulo);
}

/* ------------------------------------------------------------------ carga de dados */
async function carregarMusicas() {
  const d = await api('GET', '/api/musicas');
  est.musicas = d.musicas;
  est.saidaPadrao = d.saida_padrao;
  est.casa = d.casa || '';
  if (!est.selecionada && est.musicas.length) est.selecionada = est.musicas[0].id;
  renderLista(); renderKPIs(); renderEditor();
}
async function carregarEntrada() {
  const d = await api('GET', `/api/entrada?limiar=${est.entrada.limiar}`);
  const antes = est.entrada.fotos.map(f => f.arquivo).join('|');
  est.entrada = d;
  const depois = d.fotos.map(f => f.arquivo).join('|');
  if (!est.grupos || antes !== depois) montarGrupos();
  $('#cont-entrada').textContent = d.fotos.length || '';
  renderKPIs();
  if (est.vista === 'entrada') renderEntrada();
}
function montarGrupos() {
  const titulos = new Map((est.grupos || []).map(g => [g.fotos[0], g.titulo]));
  est.grupos = est.entrada.grupos.map(fs => ({ titulo: titulos.get(fs[0]) || '', fotos: fs.slice() }));
}

/* ------------------------------------------------------------------ topo: blocos de números e filtros */
function blocoNumero(rotulo, valor, detalhe) {
  return el('div', { class: 'bloco-numero' }, el('div', { class: 'rotulo', text: rotulo }),
    el('div', { class: 'valor', text: valor }), detalhe ? el('div', { class: 'detalhe' }, detalhe) : null);
}
function renderKPIs() {
  const ms = est.musicas;
  const conta = f => ms.filter(f).length;
  $('#kpis').replaceChildren(...limpos([
    blocoNumero('Músicas', ms.length),
    blocoNumero('Fotos na caixa de entrada', est.entrada.fotos.length),
    blocoNumero('Na fila', (est.fila.atual ? 1 : 0) + est.fila.fila.length),
    blocoNumero('A revisar', conta(m => ['rascunho', 'rascunho_alertas'].includes(m.estado))),
    blocoNumero('Revisadas', conta(m => m.estado === 'revisada')),
  ]));
}
const FILTROS = [
  ['todas', 'Todas', () => true],
  ['novas', 'Novas', m => m.estado === 'nova'],
  ['fila', 'Na fila', m => ['na_fila', 'convertendo'].includes(m.estado)],
  ['revisar', 'A revisar', m => ['rascunho', 'rascunho_alertas'].includes(m.estado)],
  ['revisadas', 'Revisadas', m => m.estado === 'revisada'],
  ['erro', 'Com erro', m => ['erro', 'cancelada', 'interrompida'].includes(m.estado)],
];
function renderFiltros() {
  $('#filtros').replaceChildren(...FILTROS.map(([id, rotulo, f]) => el('button', {
    class: 'chip', 'aria-pressed': String(est.filtro === id),
    onclick: () => { est.filtro = id; renderFiltros(); renderLista(); },
  }, `${rotulo} ${est.musicas.filter(f).length}`)));
}

/* ------------------------------------------------------------------ lista de músicas */
function renderLista() {
  renderFiltros();
  const filtro = FILTROS.find(f => f[0] === est.filtro)[2];
  const busca = est.busca.trim().toLowerCase();
  const ms = est.musicas.filter(filtro).filter(m => !busca || `${m.titulo} ${m.instrumento}`.toLowerCase().includes(busca));
  const lista = $('#lista');
  if (!ms.length) {
    lista.replaceChildren(el('li', { class: 'vazio' }, est.musicas.length ? 'Nenhuma música neste filtro.' :
      'Nenhuma música ainda. Importe fotos e crie músicas na Caixa de entrada.'));
  } else {
    lista.replaceChildren(...ms.map(m => {
      const marcado = est.selecaoExport.has(m.id);
      return el('li', {
        class: 'item', tabindex: 0, 'aria-current': String(m.id === est.selecionada),
        onclick: () => selecionar(m.id), onkeydown: e => { if (e.key === 'Enter') selecionar(m.id); },
      },
      el('input', {
        type: 'checkbox', checked: marcado, title: 'Selecionar para exportar', 'aria-label': `Selecionar ${m.titulo} para exportar`,
        onclick: e => e.stopPropagation(),
        onchange: e => { e.target.checked ? est.selecaoExport.add(m.id) : est.selecaoExport.delete(m.id); atualizarExportSel(); },
      }),
      el('div', {}, el('div', { class: 'titulo', text: m.titulo }),
        el('div', { class: 'sub', text: [m.instrumento, `${m.paginas.length} página(s)`].filter(Boolean).join(' · ') }),
        status(m.estado)));
    }));
  }
  atualizarExportSel();
}
function atualizarExportSel() {
  const n = est.selecaoExport.size;
  const b = $('#bt-exportar-sel');
  b.disabled = n === 0;
  b.textContent = n ? `Exportar ${n} selecionada(s) (.zip)` : 'Exportar selecionadas (.zip)';
}
function selecionar(id) {
  est.selecionada = id;
  mostrarVista('musicas');
  renderLista(); renderEditor(true);
}

/* ------------------------------------------------------------------ edição com controle de revisão */
async function salvar(m, mudancas) {
  try {
    const nova = await api('PATCH', `/api/musicas/${enc(m.id)}`, { revisao: m.revisao, mudancas });
    trocarMusica(nova);
    return nova;
  } catch (e) {
    if (e.status === 409 && e.dados && e.dados.musica) {
      trocarMusica(e.dados.musica);
      aviso('A música mudou enquanto você editava; recarreguei a versão atual. Refaça a alteração.', 'erro');
    } else falhou(e);
    return null;
  }
}
function trocarMusica(m) {
  const i = est.musicas.findIndex(x => x.id === m.id);
  if (i >= 0) est.musicas[i] = m; else est.musicas.push(m);
  if (est.revisoes) est.revisoes[m.id] = m.revisao;
  renderLista(); renderKPIs(); renderEditor(true);
}

/* ------------------------------------------------------------------ editor */
function editando() {
  const a = document.activeElement;
  return a && a.matches('input:not([type=checkbox]):not([type=radio]):not([type=range]), select, textarea') &&
    a.closest('#editor, #vista-entrada');
}
function renderEditor(forcar = false) {
  if (!forcar && editando()) { est.pendente = true; return; }
  est.pendente = false;
  const ed = $('#editor');
  const m = musicaSel();
  if (!m) {
    ed.replaceChildren(el('div', { class: 'vazio' }, el('h2', { text: 'Bem-vindo à Central de Partituras' }),
      el('p', {}, 'Importe as fotos das partituras (botão “Importar” ou arraste para esta janela). Elas vão para a Caixa de entrada, onde você agrupa as fotos por música.')));
    return;
  }
  const rolagem = ed.scrollTop;
  ed.replaceChildren(...limpos([cabecalho(m), blocoFinal(m), blocoPaginas(m), blocoDados(m), blocoConversao(m),
    blocoRelatorio(m), blocoRevisaoClaude(m), blocoHistorico(m)]));
  ed.scrollTop = rolagem;
}

function campoTexto(m, chave, rotulo, attrs = {}) {
  return el('div', {}, el('label', { class: 'rotulo', for: `c-${chave}`, text: rotulo }),
    el('input', {
      class: 'campo', id: `c-${chave}`, value: m[chave] ?? '', ...attrs,
      onchange: e => {
        const v = e.target.value;
        salvar(m, { [chave]: attrs.type === 'number' ? (v === '' ? null : Number(v)) : v });
      },
    }));
}

function botoesArquivo(m, publicados) {
  const mscz = publicados && publicados['.mscz'];
  const pdf = publicados && publicados['.pdf'];
  if (!mscz && !pdf) return [];
  const abrir = (alvo, arquivo) => api('POST', '/api/sistema/abrir', { musica: m.id, alvo, arquivo })
    .then(() => aviso(alvo === 'musescore' ? 'Abrindo no MuseScore…' : 'Abrindo…')).catch(falhou);
  return [
    mscz ? el('button', { class: 'botao primario', onclick: () => abrir('musescore', mscz) }, 'Abrir no MuseScore') : null,
    pdf ? el('button', { class: 'botao', onclick: () => abrir('pdf', pdf) }, 'Ver PDF') : null,
    el('button', { class: 'botao fantasma', onclick: () => abrir('pasta', mscz || pdf) }, 'Mostrar na pasta'),
  ];
}

function cabecalho(m) {
  return el('div', { class: 'editor-cab' },
    el('div', { class: 'titulo-musica' },
      el('input', { class: 'campo', value: m.titulo, 'aria-label': 'Título da música', onchange: e => salvar(m, { titulo: e.target.value }) }),
      el('div', { class: 'apagado pequeno', text: [m.instrumento, m.compositor].filter(Boolean).join(' · ') || 'Preencha instrumento e compositor abaixo' })),
    status(m.estado, true),
    el('div', { class: 'barra-acoes' },
      el('button', { class: 'botao primario', disabled: !m.paginas.length || ocupada(m), onclick: () => converter(m) },
        ocupada(m) ? 'Na fila…' : '▶ Converter'),
      el('button', { class: 'botao', onclick: () => dialogoExportar([m.id]) }, 'Exportar .zip'),
      el('button', { class: 'botao fantasma perigo', onclick: () => excluir(m) }, 'Excluir')));
}

function blocoFinal(m) {
  const fin = m.final && m.final.publicados;
  if (!fin || !Object.keys(fin).length) return null;
  return el('section', { class: 'bloco final' },
    el('h3', {}, status('revisada'), 'Arquivo final', el('span', { class: 'apagado', text: m.final.origem || '' })),
    el('p', { class: 'apagado pequeno', text: nomeArquivo(fin['.mscz'] || fin['.pdf']) }),
    el('div', { class: 'barra-acoes' }, botoesArquivo(m, fin)));
}

/* ---- páginas: arrastar para ordenar, Alt+←/→, girar, remover, ampliar */
function urlPagina(m, p, lado) { return `/api/imagem/musica/${enc(m.id)}/${enc(p.arquivo)}?lado=${lado}&g=${p.giro || 0}`; }
function blocoPaginas(m) {
  let arrastada = null;
  const reordenar = (de, para) => {
    if (de === para) return;
    const ps = m.paginas.slice();
    const [x] = ps.splice(de, 1);
    ps.splice(para, 0, x);
    salvar(m, { paginas: ps.map(p => ({ arquivo: p.arquivo, giro: p.giro })) });
  };
  const figuras = m.paginas.map((p, i) => {
    const fig = el('figure', {
      class: 'pagina', draggable: 'true', tabindex: 0,
      'aria-label': `Página ${i + 1}: ${p.arquivo}. Alt+setas para mudar a ordem.`,
      ondragstart: e => { arrastada = i; fig.classList.add('arrastando'); e.dataTransfer.effectAllowed = 'move'; },
      ondragend: () => fig.classList.remove('arrastando'),
      ondragover: e => {
        e.preventDefault();
        const r = fig.getBoundingClientRect();
        const antes = e.clientX < r.left + r.width / 2;
        fig.classList.toggle('alvo-antes', antes); fig.classList.toggle('alvo-depois', !antes);
      },
      ondragleave: () => fig.classList.remove('alvo-antes', 'alvo-depois'),
      ondrop: e => {
        e.preventDefault();
        const antes = fig.classList.contains('alvo-antes');
        fig.classList.remove('alvo-antes', 'alvo-depois');
        if (arrastada === null) return;
        let destino = antes ? i : i + 1;
        if (arrastada < destino) destino -= 1;
        reordenar(arrastada, destino);
      },
      onkeydown: e => {
        if (e.altKey && e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); reordenar(i, i - 1); }
        if (e.altKey && e.key === 'ArrowRight' && i < m.paginas.length - 1) { e.preventDefault(); reordenar(i, i + 1); }
        if (e.key === 'Enter') ampliar(m, i);
      },
    },
    el('span', { class: 'numero', text: i + 1 }),
    el('img', { src: urlPagina(m, p, 300), alt: `Página ${i + 1}`, loading: 'lazy', ondblclick: () => ampliar(m, i) }),
    el('figcaption', { title: p.arquivo, text: p.tipo === 'pdf' ? `${p.arquivo} (PDF)` : soHora(p.hora) || p.arquivo }),
    el('div', { class: 'ferramentas' },
      el('button', { title: 'Girar 90°', 'aria-label': `Girar página ${i + 1}`, onclick: () => {
        const ps = m.paginas.map(x => ({ arquivo: x.arquivo, giro: x.giro || 0 }));
        ps[i].giro = (ps[i].giro + 90) % 360;
        salvar(m, { paginas: ps });
      } }, '↻'),
      el('button', { title: 'Ampliar', 'aria-label': `Ampliar página ${i + 1}`, onclick: () => ampliar(m, i) }, '⤢'),
      el('button', { title: 'Tirar da música (volta para a caixa de entrada)', 'aria-label': `Tirar página ${i + 1}`,
        onclick: () => api('DELETE', `/api/musicas/${enc(m.id)}/paginas/${enc(p.arquivo)}`)
          .then(nova => { trocarMusica(nova); carregarEntrada(); aviso('Foto devolvida à caixa de entrada.'); }).catch(falhou) }, '✕')));
    return fig;
  });
  return el('section', { class: 'bloco' },
    el('h3', {}, 'Páginas', el('span', { class: 'apagado', text: 'arraste para ordenar · Alt+← / Alt+→ pelo teclado · duplo clique amplia' })),
    el('div', { class: 'paginas' }, figuras.length ? figuras : el('p', { class: 'apagado', text: 'Sem páginas.' })),
    el('div', { class: 'barra-acoes', style: 'margin-top:12px' },
      el('button', { class: 'botao', onclick: () => dialogoAdicionarDaEntrada(m) }, '+ Adicionar da caixa de entrada'),
      el('button', { class: 'botao fantasma', onclick: () => escolherArquivos(m.id) }, '+ Importar fotos para esta música')));
}

function blocoDados(m) {
  return el('section', { class: 'bloco' }, el('h3', { text: 'Dados da música' }),
    el('div', { class: 'grade-campos' },
      campoTexto(m, 'instrumento', 'Instrumento ou parte', { placeholder: 'Ex.: Trombone 3 / Tuba' }),
      campoTexto(m, 'compositor', 'Compositor / arranjo', { placeholder: 'Ex.: Joel Lindsey / arr. B. Knight' }),
      campoTexto(m, 'ultimo_compasso', 'Último número de compasso impresso', { type: 'number', min: 1, placeholder: 'Ex.: 165 (confere o total)' }),
      el('div', {}, el('label', { class: 'rotulo', for: 'c-clave', text: 'Clave (para as guias de altura)' }),
        el('select', { class: 'campo', id: 'c-clave', onchange: e => salvar(m, { clave: e.target.value }) },
          el('option', { value: 'fa', selected: m.clave === 'fa' }, 'Clave de fá'),
          el('option', { value: 'sol', selected: m.clave === 'sol' }, 'Clave de sol')))));
}

const MOTORES = [
  ['homr', 'homr', 'Recomendado para fotos de celular. Acerta as notas; não traz dinâmicas nem textos.'],
  ['audiveris', 'Audiveris', 'Para scans limpos. Lê dinâmicas e textos; em fotos, perde semibreves graves.'],
  ['ambos', 'Os dois', 'Converte com os dois motores para comparar os relatórios. Leva o dobro do tempo.'],
];
function blocoConversao(m) {
  const disp = est.motores || {};
  const pasta = m.saida && m.saida.pasta;
  return el('section', { class: 'bloco' }, el('h3', { text: 'Conversão' }),
    el('div', { class: 'opcoes-motor', role: 'radiogroup', 'aria-label': 'Motor de reconhecimento' },
      MOTORES.map(([id, nome, desc]) => {
        const faltando = id === 'ambos' ? !(disp.homr && disp.audiveris) : !disp[id];
        return el('label', { class: 'opcao-motor' },
          el('input', { type: 'radio', name: 'motor', value: id, checked: m.motor === id, disabled: faltando,
            onchange: () => salvar(m, { motor: id }) }),
          el('strong', { text: nome }), id === 'homr' ? el('span', { class: 'apagado pequeno', text: ' — recomendado' }) : null,
          el('div', { class: 'descricao', text: faltando ? 'Não instalado (rode conversor/instalar.sh).' : desc }));
      })),
    el('div', { class: 'grade-campos', style: 'margin-top:14px' },
      el('div', {}, el('label', { class: 'rotulo', text: 'Pasta de saída' }),
        el('div', { class: 'linha-saida' },
          el('input', { class: 'campo', readonly: true, value: curto(pasta) || `${curto(est.saidaPadrao)} (padrão)`, title: pasta || est.saidaPadrao }),
          el('button', { class: 'botao', onclick: () => escolherPasta(m) }, 'Escolher…'),
          pasta ? el('button', { class: 'botao fantasma', onclick: () => salvar(m, { saida: { pasta: null, nome: m.saida.nome } }) }, 'Padrão') : null)),
      el('div', {}, el('label', { class: 'rotulo', for: 'c-nome', text: 'Nome do arquivo (.mscz)' }),
        el('input', { class: 'campo', id: 'c-nome', value: (m.saida && m.saida.nome) || '',
          placeholder: [m.titulo, m.instrumento].filter(Boolean).join(' - '),
          onchange: e => salvar(m, { saida: { pasta: m.saida.pasta, nome: e.target.value || null } }) }))),
    el('div', { class: 'barra-acoes', style: 'margin-top:12px' },
      el('label', {}, el('input', { type: 'checkbox', checked: m.opcoes.pdf,
        onchange: e => salvar(m, { opcoes: { ...m.opcoes, pdf: e.target.checked } }) }), ' Gerar PDF para comparar'),
      el('label', { style: 'margin-left:16px' }, 'Guias de altura: ',
        el('select', { class: 'campo', style: 'width:auto;display:inline-block', onchange: e => salvar(m, { opcoes: { ...m.opcoes, guias: e.target.value || null } }) },
          el('option', { value: '', selected: !m.opcoes.guias }, 'não gerar'),
          el('option', { value: 'fa', selected: m.opcoes.guias === 'fa' }, 'clave de fá (+1 min, usa o Audiveris)'),
          el('option', { value: 'sol', selected: m.opcoes.guias === 'sol' }, 'clave de sol (+1 min, usa o Audiveris)')))),
    el('p', { class: 'apagado pequeno', text: 'Nunca sobrescreve: se já existir um arquivo com esse nome, salva como “Nome (2)”.' }),
    el('button', { class: 'botao primario', disabled: !m.paginas.length || ocupada(m), onclick: () => converter(m) },
      ocupada(m) ? 'Na fila…' : '▶ Converter agora'));
}

async function converter(m) {
  try {
    await api('POST', `/api/musicas/${enc(m.id)}/converter`, {});
    aviso(`“${m.titulo}” entrou na fila de conversão.`, 'ok');
    await carregarMusicas();
  } catch (e) { falhou(e); }
}
async function escolherPasta(m) {
  try {
    aviso('Abrindo a janela de escolha de pasta… (se não aparecer, procure atrás da Central)');
    const r = await api('POST', '/api/sistema/escolher-pasta', { inicial: (m.saida && m.saida.pasta) || est.saidaPadrao });
    if (r.pasta) salvar(m, { saida: { pasta: r.pasta, nome: m.saida.nome } });
  } catch (e) { falhou(e); }
}
async function excluir(m) {
  if (!confirm(`Mandar “${m.titulo}” (fotos e conversões) para a Lixeira?\nOs arquivos já salvos na pasta de saída não são apagados.`)) return;
  try {
    await api('DELETE', `/api/musicas/${enc(m.id)}`);
    est.selecionada = null;
    aviso('Música enviada para a Lixeira.', 'ok');
    await carregarMusicas();
  } catch (e) { falhou(e); }
}

/* ---- relatório */
function conversoesDoRelatorio(m) {
  const convs = m.conversoes.filter(c => c.estado !== 'legado');
  const ultima = convs[convs.length - 1];
  if (!ultima) return { lista: [], ultima: null };
  if (ultima.lote) {
    const lote = convs.filter(c => c.lote === ultima.lote && c.versoes.length);
    if (lote.length) return { lista: lote, ultima };
  }
  const comVersao = [...convs].reverse().find(c => c.versoes.length);
  return { lista: comVersao ? [comVersao] : [], ultima };
}
function blocoRelatorio(m) {
  const { lista, ultima } = conversoesDoRelatorio(m);
  if (!ultima) return null;
  const bloco = el('section', { class: 'bloco' }, el('h3', { text: 'Relatório de conferência' }));
  if (ultima.estado === 'erro' && ultima.erro) {
    bloco.append(el('div', { class: 'erro-cartao' }, el('strong', { text: 'A última conversão falhou: ' }), ultima.erro));
  }
  if (['na_fila', 'convertendo'].includes(ultima.estado) && !lista.length) {
    bloco.append(el('p', { class: 'apagado', text: 'A conversão está na fila. O relatório aparece aqui quando terminar.' }));
  }
  const grade = el('div', { class: `relatorios${lista.length > 1 ? ' lado-a-lado' : ''}` });
  for (const c of lista) grade.append(relatorioConversao(m, c));
  bloco.append(grade);
  if (lista.length) bloco.append(checklist(m));
  return bloco;
}

function relatorioConversao(m, c) {
  const v = c.versoes[c.versoes.length - 1];
  const chave = `${m.id}/${c.id}/${v.n}`;
  const caixa = el('div', {},
    el('div', { class: 'relatorio-cab' },
      el('strong', { text: c.motor === 'homr' ? 'homr' : 'Audiveris' }),
      el('span', { class: 'apagado pequeno', text: `${hora(v.quando)} · versão ${v.n}` }),
      botoesArquivo(m, v.publicados)));
  const corpo = el('div', {}, el('p', { class: 'apagado', text: 'Carregando relatório…' }));
  caixa.append(corpo);
  const preencher = rel => corpo.replaceChildren(...limpos(conteudoRelatorio(m, c, rel, chave)));
  if (est.conferencias[chave]) preencher(est.conferencias[chave]);
  else api('GET', `/api/musicas/${enc(m.id)}/conversoes/${enc(c.id)}/versoes/${v.n}/conferencia`)
    .then(rel => { est.conferencias[chave] = rel; preencher(rel); })
    .catch(e => corpo.replaceChildren(el('p', { class: 'apagado', text: `Relatório indisponível: ${e.message}` })));
  return caixa;
}

function conteudoRelatorio(m, c, rel, chave) {
  const dif = rel.diferenca;
  const blocos = el('div', { class: 'blocos-relatorio' },
    blocoNumero('Compassos', rel.total, rel.esperado ? el('span', {},
      `de ${rel.esperado} esperados `, dif === 0 ? el('span', { class: 'delta-bom', text: '✓ confere' })
        : el('span', { class: 'delta-ruim', text: dif < 0 ? `▼ faltam ${-dif}` : `▲ sobram ${dif}` })) : 'informe o último compasso'),
    blocoNumero('Trechos de pausa', rel.trechos.length, 'confira os números'),
    blocoNumero('Duração errada', rel.duracao_errada.length, rel.duracao_errada.length ? 'veja o mapa' : 'nenhum compasso'),
    blocoNumero('Prováveis notas perdidas', rel.suspeitos.length, 'compassos vazios'),
    blocoNumero('Ligaduras de valor', rel.ligaduras.length, 'convertidas'));
  const tabelaVisivel = !!est.tabela[chave];
  const alternar = el('button', { class: 'botao mini fantasma', 'aria-pressed': String(tabelaVisivel),
    onclick: () => { est.tabela[chave] = !tabelaVisivel; renderEditor(true); } }, tabelaVisivel ? 'Ver mapa' : 'Ver como tabela');
  const visual = tabelaVisivel ? tabelaRelatorio(rel) : el('div', {}, mapaCompassos(rel), legendaMapa());
  return [blocos,
    el('div', { class: 'relatorio-cab' }, el('strong', { text: 'Mapa de compassos' }),
      el('span', { class: 'apagado pequeno', text: '1 célula = 1 compasso' }), alternar),
    visual, correcaoTrechos(m, c, rel, chave), detalhesRelatorio(rel)];
}

/* ---- mapa de compassos (skill dataviz: marcas finas, problema como marca acima da célula, colchete com rótulo
        de texto para pausas longas, dica por célula com área de toque >= 24 px, teclado e visão em tabela) */
function descreverCompasso(rel, i) {
  const c = rel.compassos[i];
  const t = rel.trechos.find(t => c.n >= t.inicio && c.n <= t.fim);
  if (c.problema === 'duracao') return ['Duração errada', `${c.tempos} de ${c.esperado} tempos`];
  if (c.problema === 'suspeito') return ['Provável nota perdida', 'compasso vazio entre compassos com notas'];
  if (t) return ['Pausa', `trecho ${t.indice} (c. ${t.inicio}–${t.fim}, ${t.lidos} compasso(s))`];
  return [c.tipo === 'notas' ? 'Com notas' : 'Pausa', ''];
}
function mapaCompassos(rel) {
  const caixa = el('div', { class: 'mapa' });
  const vivo = el('div', { class: 'apagado pequeno', 'aria-live': 'polite', style: 'min-height:1.4em' });
  const desenhar = () => {
    const n = rel.compassos.length;
    const W = Math.max(caixa.clientWidth, 320);
    const porLinha = n > 200 ? 100 : Math.max(n, 1);
    const gap = 2, pad = 2;
    const cw = Math.max(2, Math.floor((W - 2 * pad) / porLinha) - gap);
    const faixaColchete = 20, faixaMarca = 12, ch = 18, faixaEixo = 14, entreLinhas = 10;
    const alturaLinha = faixaColchete + faixaMarca + ch + faixaEixo + entreLinhas;
    const linhas = Math.ceil(n / porLinha);
    const s = svg('svg', { viewBox: `0 0 ${W} ${linhas * alturaLinha}`, height: linhas * alturaLinha, tabindex: 0, role: 'img',
      'aria-label': `Mapa de ${n} compassos: ${rel.com_notas} com notas, ${rel.trechos.length} trechos de pausa, ` +
        `${rel.duracao_errada.length} com duração errada, ${rel.suspeitos.length} prováveis notas perdidas. Use as setas para percorrer.` });
    const pos = i => {
      const linha = Math.floor(i / porLinha), col = i % porLinha;
      const topo = linha * alturaLinha;
      return { x: pad + col * (cw + gap), topo, yCelula: topo + faixaColchete + faixaMarca };
    };
    const celulas = [];
    rel.compassos.forEach((c, i) => {
      const p = pos(i);
      const cor = c.problema === 'duracao' ? 'var(--critico)' : c.tipo === 'notas' ? 'var(--apagado)' : 'var(--linha)';
      const r = svg('rect', { x: p.x, y: p.yCelula, width: cw, height: ch, rx: Math.min(2, cw / 2), fill: cor });
      s.append(r);
      celulas.push(r);
      if (c.problema === 'duracao') {
        s.append(svg('text', { x: p.x + cw / 2, y: p.yCelula - 3, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 700, fill: 'var(--critico)' }, '✕'));
      } else if (c.problema === 'suspeito') {
        const cx = p.x + cw / 2, base = p.yCelula - 2;
        s.append(svg('path', { d: `M${cx} ${base - 9}L${cx + 5} ${base}H${cx - 5}Z`, fill: 'var(--aviso)', stroke: 'var(--tinta)', 'stroke-width': 0.9, 'stroke-linejoin': 'round' }));
      }
      if (c.n === 1 || c.n % 10 === 0) {
        s.append(svg('text', { x: p.x + cw / 2, y: p.yCelula + ch + 11, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--apagado)', style: 'font-variant-numeric:tabular-nums' }, c.n));
      }
    });
    // colchetes dos trechos de pausa (um por linha atravessada; rótulo só no primeiro)
    rel.trechos.forEach(t => {
      let i = t.inicio - 1, primeiro = true;
      while (i <= t.fim - 1) {
        const fimLinha = Math.min(t.fim - 1, Math.floor(i / porLinha) * porLinha + porLinha - 1);
        const a = pos(i), b = pos(fimLinha);
        const y = a.topo + faixaColchete - 4, x1 = a.x, x2 = b.x + cw;
        s.append(svg('path', { d: `M${x1} ${y + 4}V${y}H${x2}V${y + 4}`, fill: 'none', stroke: 'var(--tinta-2)', 'stroke-width': 1 }));
        if (primeiro) {
          const largo = x2 - x1;
          const rotulo = largo > 64 ? `trecho ${t.indice} · ${t.lidos}` : largo > 22 ? `${t.lidos}` : '';
          if (rotulo) s.append(svg('text', { x: (x1 + x2) / 2, y: y - 3, 'text-anchor': 'middle', 'font-size': 10.5, fill: 'var(--tinta-2)', style: 'font-variant-numeric:tabular-nums' }, rotulo));
        }
        primeiro = false;
        i = fimLinha + 1;
      }
    });
    // áreas de toque maiores que a marca (faixa da marca + célula = 30 px)
    let atual = -1;
    const dica = $('#dica');
    const mostrar = (i, x, y) => {
      if (atual >= 0) celulas[atual].removeAttribute('stroke');
      atual = i;
      celulas[i].setAttribute('stroke', 'var(--tinta)');
      celulas[i].setAttribute('stroke-width', 1.5);
      const [titulo, detalhe] = descreverCompasso(rel, i);
      dica.replaceChildren(el('strong', { text: `c. ${rel.compassos[i].n}` }), `${titulo}${detalhe ? ` · ${detalhe}` : ''}`);
      dica.hidden = false;
      dica.style.left = `${Math.min(x + 14, window.innerWidth - 300)}px`;
      dica.style.top = `${y + 14}px`;
      vivo.textContent = `Compasso ${rel.compassos[i].n}: ${titulo}${detalhe ? `, ${detalhe}` : ''}`;
    };
    const esconder = () => { dica.hidden = true; if (atual >= 0) celulas[atual].removeAttribute('stroke'); };
    rel.compassos.forEach((c, i) => {
      const p = pos(i);
      const alvo = svg('rect', { x: p.x - gap / 2, y: p.yCelula - faixaMarca, width: cw + gap, height: faixaMarca + ch, fill: 'transparent' });
      alvo.addEventListener('pointermove', e => mostrar(i, e.clientX, e.clientY));
      alvo.addEventListener('pointerleave', esconder);
      s.append(alvo);
    });
    s.addEventListener('keydown', e => {
      const passos = { ArrowRight: 1, ArrowLeft: -1, PageDown: 10, PageUp: -10 };
      let i = atual < 0 ? 0 : atual;
      if (e.key in passos) i = Math.max(0, Math.min(n - 1, i + passos[e.key]));
      else if (e.key === 'Home') i = 0;
      else if (e.key === 'End') i = n - 1;
      else return;
      e.preventDefault();
      const r = celulas[i].getBoundingClientRect();
      mostrar(i, r.left, r.bottom);
    });
    s.addEventListener('blur', esconder);
    caixa.replaceChildren(s, vivo);
  };
  requestAnimationFrame(desenhar);
  let largura = 0;
  new ResizeObserver(() => { if (Math.abs(caixa.clientWidth - largura) > 8) { largura = caixa.clientWidth; desenhar(); } }).observe(caixa);
  return caixa;
}
function legendaMapa() {
  const amostra = (fill, extra) => { const s = svg('svg', { viewBox: '0 0 18 14', 'aria-hidden': 'true' }); s.append(svg('rect', { x: 4, y: 3, width: 10, height: 10, rx: 2, fill })); if (extra) s.append(extra); return s; };
  const marca = desenho => { const s = svg('svg', { viewBox: '0 0 18 14', 'aria-hidden': 'true' }); s.append(desenho); return s; };
  return el('div', { class: 'legenda' },
    el('span', {}, amostra('var(--apagado)'), 'com notas'),
    el('span', {}, amostra('var(--linha)'), 'pausa'),
    el('span', {}, marca(svg('text', { x: 9, y: 11, 'text-anchor': 'middle', 'font-size': 12, 'font-weight': 700, fill: 'var(--critico)' }, '✕')), 'duração errada'),
    el('span', {}, marca(svg('path', { d: 'M9 2L14 12H4Z', fill: 'var(--aviso)', stroke: 'var(--tinta)', 'stroke-width': 0.9 })), 'provável nota perdida'),
    el('span', {}, marca(svg('path', { d: 'M2 12V6H16V12', fill: 'none', stroke: 'var(--tinta-2)', 'stroke-width': 1.2 })), 'trecho de pausa (nº de compassos lidos)'));
}
function tabelaRelatorio(rel) {
  const linhas = [];
  rel.trechos.forEach(t => linhas.push([`${t.inicio}–${t.fim}`, `Trecho de pausa ${t.indice}`, `${t.lidos} compasso(s) lidos`]));
  rel.duracao_errada.forEach(c => linhas.push([`${c.n}`, 'Duração errada', `${c.tempos} de ${c.esperado} tempos`]));
  rel.suspeitos.forEach(n => linhas.push([`${n}`, 'Provável nota perdida', 'compasso vazio']));
  linhas.sort((a, b) => parseInt(a[0], 10) - parseInt(b[0], 10));
  return el('table', { class: 'tabela' },
    el('caption', { class: 'apagado pequeno', style: 'text-align:left', text: `${rel.total} compassos, ${rel.com_notas} com notas` }),
    el('thead', {}, el('tr', {}, el('th', { text: 'Compasso(s)' }), el('th', { text: 'Situação' }), el('th', { text: 'Detalhe' }))),
    el('tbody', {}, linhas.map(l => el('tr', {}, el('td', { class: 'num', text: l[0] }), el('td', { text: l[1] }), el('td', { text: l[2] })))));
}

/* ---- correção dos trechos de pausa: refaz só o acabamento (segundos) */
function correcaoTrechos(m, c, rel, chave) {
  if (!rel.trechos.length) return null;
  const valores = est.correcoes[chave] || (est.correcoes[chave] = Object.fromEntries(rel.trechos.map(t => [t.indice, t.lidos])));
  const lidosMotor = Object.fromEntries((rel.correcoes || []).map(x => [x.indice, x.lidos]));
  const saldo = el('span', { class: 'saldo' });
  const atualizarSaldo = () => {
    const novoTotal = rel.total + rel.trechos.reduce((s, t) => s + (Number(valores[t.indice]) || 0) - t.lidos, 0);
    if (rel.esperado) {
      const d = novoTotal - rel.esperado;
      saldo.className = `saldo ${d === 0 ? 'delta-bom' : 'delta-ruim'}`;
      saldo.textContent = d === 0 ? `Total ${novoTotal}: confere com o último compasso ✓` : `Total ${novoTotal}: ${d < 0 ? `faltam ${-d}` : `sobram ${d}`} compasso(s)`;
    } else {
      saldo.className = 'saldo';
      saldo.textContent = `Total ${novoTotal} compassos (preencha o último compasso impresso para conferir)`;
    }
  };
  atualizarSaldo();
  const ocupado = ocupada(m);
  return el('div', {},
    el('h4', { style: 'margin:16px 0 4px', text: 'Corrigir trechos de pausa' }),
    el('p', { class: 'apagado pequeno', text: 'Confira na partitura impressa quantos compassos cada trecho tem (os números de dois dígitos costumam sair errados) e refaça o acabamento: leva segundos, sem reconhecer de novo.' }),
    el('div', { class: 'trechos' }, rel.trechos.map(t => {
      const linha = el('label', { class: 'trecho' },
        el('span', {}, el('strong', { text: `Trecho ${t.indice}` }), ` · c. ${t.inicio}–${t.fim}`,
          lidosMotor[t.indice] !== undefined ? el('span', { class: 'apagado pequeno', text: ` (motor leu ${lidosMotor[t.indice]})` }) : null),
        el('input', { class: 'campo num', type: 'number', min: 1, max: 999, value: valores[t.indice], 'aria-label': `Compassos do trecho ${t.indice}`,
          oninput: e => { valores[t.indice] = e.target.value; linha.classList.toggle('mudou', Number(e.target.value) !== t.lidos); atualizarSaldo(); } }));
      if (Number(valores[t.indice]) !== t.lidos) linha.classList.add('mudou');
      return linha;
    })),
    el('div', { class: 'barra-acoes' }, saldo,
      el('button', { class: 'botao primario', disabled: ocupado, onclick: async () => {
        try {
          await api('POST', `/api/musicas/${enc(m.id)}/conversoes/${enc(c.id)}/acabar`, { correcoes: valores });
          delete est.correcoes[chave];
          aviso('Refazendo o acabamento com as pausas corrigidas…', 'ok');
          carregarMusicas();
        } catch (e) { falhou(e); }
      } }, ocupado ? 'Na fila…' : 'Refazer acabamento')));
}
function detalhesRelatorio(rel) {
  const partes = [];
  if (rel.ligaduras.length) partes.push(el('details', { class: 'mais' }, el('summary', { text: `Ligaduras de valor reconhecidas (${rel.ligaduras.length})` }),
    el('ul', {}, rel.ligaduras.map(t => el('li', { text: t })))));
  if (rel.textos_ocr.length) partes.push(el('details', { class: 'mais' }, el('summary', { text: 'Textos de cabeçalho lidos pelo OCR (fora da partitura)' }),
    el('p', { class: 'pequeno', text: rel.textos_ocr.join(' | ') })));
  if (rel.motor === 'homr') partes.push(el('p', { class: 'apagado pequeno', text: 'O homr não traz dinâmicas, textos (rit., a tempo) nem fermatas, e só parte dos acentos: acrescente no MuseScore.' }));
  return el('div', {}, partes);
}

const ITENS_CHECKLIST = [
  ['pausas', 'Trechos de pausa conferidos com os números impressos'],
  ['ligaduras', 'Ligaduras e acidentes de notas ligadas conferidos'],
  ['dinamicas', 'Dinâmicas, andamentos, rit./a tempo e fermatas acrescentados'],
  ['ouvida', 'Ouvi a música no MuseScore'],
];
function checklist(m) {
  const tudo = ITENS_CHECKLIST.every(([k]) => m.checklist[k]);
  return el('div', {}, el('h4', { style: 'margin:18px 0 4px', text: 'Revisão no MuseScore' }),
    el('div', { class: 'checklist' }, ITENS_CHECKLIST.map(([k, rotulo]) => el('label', {},
      el('input', { type: 'checkbox', checked: !!m.checklist[k], onchange: e => salvar(m, { checklist: { ...m.checklist, [k]: e.target.checked } }) }), rotulo))),
    m.revisada
      ? el('button', { class: 'botao', onclick: () => salvar(m, { revisada: false }) }, 'Desmarcar “Revisada”')
      : el('button', { class: 'botao primario', disabled: !tudo, title: tudo ? '' : 'Marque os itens acima primeiro', onclick: () => salvar(m, { revisada: true }) }, '✓ Marcar como revisada'));
}

/* ---- revisão com o Claude */
function blocoRevisaoClaude(m) {
  const ultima = (m.revisoes || [])[(m.revisoes || []).length - 1];
  const naFila = (est.fila.atual && est.fila.atual.musica === m.id && est.fila.atual.tipo === 'revisao') ||
    est.fila.fila.some(j => j.musica === m.id && j.tipo === 'revisao');
  const corpo = [el('p', { class: 'apagado pequeno', text: 'Monta um pacote com as fotos, guias de altura, o rascunho e um pedido pronto. Você cola o pedido no Claude Code, que revisa compasso a compasso — o processo que gerou a versão revisada de My Savior and My Son.' })];
  if (ultima && ultima.ok) {
    corpo.push(el('p', {}, el('strong', { text: 'Pacote pronto ' }), el('span', { class: 'apagado pequeno', text: hora(ultima.quando) })),
      el('div', { class: 'barra-acoes' },
        el('button', { class: 'botao primario', onclick: () => navigator.clipboard.writeText(ultima.pedido)
          .then(() => aviso('Pedido copiado. Cole no Claude Code aberto na pasta image-to-music.', 'ok')).catch(falhou) }, 'Copiar pedido'),
        el('button', { class: 'botao', onclick: () => api('POST', `/api/musicas/${enc(m.id)}/abrir-revisao`).catch(falhou) }, 'Abrir pasta do pacote')));
  } else if (ultima && !ultima.ok) {
    corpo.push(el('div', { class: 'erro-cartao', text: `O último pacote falhou: ${ultima.erro || 'erro desconhecido'}` }));
  }
  corpo.push(el('div', { class: 'barra-acoes', style: 'margin-top:10px' },
    el('button', { class: 'botao', disabled: naFila || !m.paginas.length, onclick: () => api('POST', `/api/musicas/${enc(m.id)}/revisao`)
      .then(() => { aviso('Preparando o pacote de revisão (≈1 min)…', 'ok'); carregarMusicas(); }).catch(falhou) },
    naFila ? 'Preparando…' : (ultima ? 'Preparar novo pacote' : 'Preparar pacote de revisão'))));
  return el('section', { class: 'bloco' }, el('h3', { text: 'Revisão com o Claude' }), corpo);
}

/* ---- histórico */
function blocoHistorico(m) {
  if (!m.conversoes.length) return null;
  const linhas = [...m.conversoes].reverse().map(c => {
    const v = c.versoes[c.versoes.length - 1];
    const situacao = c.estado === 'ok' ? (v && v.resumo && v.resumo.alertas ? 'rascunho_alertas' : 'rascunho') : c.estado;
    return el('tr', {},
      el('td', { text: hora(c.quando) }),
      el('td', { text: c.motor === 'homr' ? 'homr' : 'Audiveris' }),
      el('td', {}, c.estado === 'legado' ? el('span', { class: 'apagado', text: c.nota || 'antiga' }) : status(situacao)),
      el('td', { class: 'num', text: c.versoes.length || '—' }),
      el('td', { class: 'num', text: v && v.resumo ? `${v.resumo.total}${v.resumo.esperado ? ` / ${v.resumo.esperado}` : ''}` : '—' }),
      el('td', {}, v ? botoesArquivo(m, v.publicados).slice(0, 2) : null));
  });
  return el('section', { class: 'bloco' }, el('h3', { text: 'Histórico de conversões' }),
    el('table', { class: 'tabela' },
      el('thead', {}, el('tr', {}, ['Quando', 'Motor', 'Situação', 'Versões', 'Compassos', 'Arquivos'].map(t => el('th', { text: t })))),
      el('tbody', {}, linhas)));
}

/* ------------------------------------------------------------------ caixa de entrada */
function renderEntrada(forcar = false) {
  if (!forcar && editando()) { est.pendente = true; return; }
  const v = $('#vista-entrada');
  const fotos = new Map(est.entrada.fotos.map(f => [f.arquivo, f]));
  const grupos = (est.grupos || []).filter(g => g.fotos.length);
  const cab = el('div', { class: 'entrada-cab' },
    el('h2', {}, 'Caixa de entrada ', el('span', { class: 'apagado', style: 'font-size:14px;font-weight:400', text: `${fotos.size} foto(s)` })),
    el('label', { class: 'limiar' }, 'Separar grupos quando o intervalo entre fotos passar de',
      el('input', { type: 'range', min: 10, max: 900, step: 10, value: est.entrada.limiar, 'aria-label': 'Intervalo em segundos',
        oninput: e => { e.target.nextSibling.textContent = `${e.target.value} s`; },
        onchange: e => { est.entrada.limiar = Number(e.target.value); est.grupos = null; carregarEntrada(); } }),
      el('span', { class: 'num', text: `${est.entrada.limiar} s` })),
    el('button', { class: 'botao fantasma', onclick: () => api('POST', '/api/sistema/abrir-pasta', { qual: 'entrada' }).catch(falhou) }, 'Abrir pasta'),
    el('button', { class: 'botao primario', disabled: !grupos.length, onclick: () => criarGrupos(grupos) }, `Criar ${grupos.length} música(s)`));
  if (!fotos.size) {
    v.replaceChildren(cab, el('div', { class: 'vazio' },
      el('h3', { text: 'Nenhuma foto esperando' }),
      el('p', {}, 'Arraste fotos ou PDFs para esta janela, use “Importar”, ou copie arquivos para a pasta entrada/. ',
        'As fotos são agrupadas pela hora em que foram tiradas: cada grupo vira uma música.')));
    return;
  }
  let arrastada = null;
  const lista = grupos.map((g, gi) => {
    const infos = g.fotos.map(a => fotos.get(a)).filter(Boolean);
    const intervalo = infos.length ? `${soHora(infos[0].hora)}${infos.length > 1 ? `–${soHora(infos[infos.length - 1].hora)}` : ''}` : '';
    const card = el('section', { class: 'grupo',
      ondragover: e => { e.preventDefault(); card.classList.add('alvo'); },
      ondragleave: () => card.classList.remove('alvo'),
      ondrop: e => {
        e.preventDefault(); card.classList.remove('alvo');
        if (!arrastada) return;
        est.grupos.forEach(x => { x.fotos = x.fotos.filter(f => f !== arrastada); });
        g.fotos.push(arrastada);
        g.fotos.sort((a, b) => (fotos.get(a).hora || '').localeCompare(fotos.get(b).hora || ''));
        arrastada = null;
        renderEntrada(true);
      } },
    el('div', { class: 'grupo-cab' },
      el('input', { class: 'campo', value: g.titulo, placeholder: `Título da música ${gi + 1}`, 'aria-label': `Título do grupo ${gi + 1}`,
        oninput: e => { g.titulo = e.target.value; } }),
      el('span', { class: 'apagado', text: `${g.fotos.length} foto(s) · ${intervalo}` }),
      el('div', { class: 'barra-acoes' },
        gi < grupos.length - 1 ? el('button', { class: 'botao mini fantasma', onclick: () => {
          const prox = grupos[gi + 1];
          g.fotos.push(...prox.fotos); prox.fotos = [];
          renderEntrada(true);
        } }, 'Juntar com o próximo') : null,
        est.musicas.length ? el('select', { class: 'campo', style: 'width:auto', 'aria-label': 'Adicionar a uma música existente',
          onchange: e => { if (e.target.value) adicionarAMusica(e.target.value, g.fotos.slice()); } },
          el('option', { value: '' }, 'Adicionar a uma música…'),
          est.musicas.map(m => el('option', { value: m.id, text: m.titulo }))) : null,
        el('button', { class: 'botao primario mini', onclick: () => criarGrupos([g]) }, 'Criar música'))),
    el('div', { class: 'fotos-grupo' }, g.fotos.map((a, fi) => {
      const f = fotos.get(a);
      if (!f) return null;
      return el('figure', { class: 'foto', draggable: 'true', tabindex: 0, title: a,
        ondragstart: e => { arrastada = a; e.dataTransfer.effectAllowed = 'move'; } },
      el('img', { src: `/api/imagem/entrada/${enc(a)}?lado=240&g=${f.giro || 0}`, alt: a, loading: 'lazy' }),
      el('figcaption', { text: f.tipo === 'pdf' ? `PDF · ${f.paginas || '?'} pág.` : soHora(f.hora) }),
      el('div', { class: 'ferramentas' },
        el('button', { title: 'Girar 90°', 'aria-label': `Girar ${a}`, onclick: () => api('PATCH', `/api/entrada/${enc(a)}`, { giro: ((f.giro || 0) + 90) % 360 })
          .then(() => { f.giro = ((f.giro || 0) + 90) % 360; renderEntrada(true); }).catch(falhou) }, '↻'),
        fi > 0 ? el('button', { title: 'Começar um novo grupo nesta foto', 'aria-label': `Novo grupo a partir de ${a}`, onclick: () => {
          const resto = g.fotos.splice(fi);
          est.grupos.splice(est.grupos.indexOf(g) + 1, 0, { titulo: '', fotos: resto });
          renderEntrada(true);
        } }, '✂') : null,
        el('button', { title: 'Mandar para a Lixeira', 'aria-label': `Descartar ${a}`, onclick: () => {
          if (!confirm(`Mandar “${a}” para a Lixeira?`)) return;
          api('DELETE', `/api/entrada/${enc(a)}`).then(carregarEntrada).catch(falhou);
        } }, '🗑')));
    })));
    return card;
  });
  v.replaceChildren(cab, el('p', { class: 'apagado pequeno', text: 'Arraste fotos entre os grupos, use ✂ para separar e “Juntar com o próximo” para unir. A ordem das páginas pode ser ajustada depois, dentro da música.' }),
    el('div', { class: 'grupos' }, lista));
}
async function criarGrupos(grupos) {
  const sem = grupos.filter(g => !g.titulo.trim());
  if (sem.length && !confirm(`${sem.length} grupo(s) sem título vão se chamar “Música sem título”. Continuar?`)) return;
  try {
    const r = await api('POST', '/api/entrada/criar', { grupos: grupos.map(g => ({ titulo: g.titulo, fotos: g.fotos })) });
    aviso(`${r.musicas.length} música(s) criada(s).`, 'ok');
    est.grupos = null;
    await carregarEntrada();
    await carregarMusicas();
    if (r.musicas.length) selecionar(r.musicas[0].id);
  } catch (e) { falhou(e); }
}
async function adicionarAMusica(mid, fotos) {
  try {
    const m = await api('POST', `/api/musicas/${enc(mid)}/paginas`, { fotos });
    trocarMusica(m);
    aviso(`${fotos.length} foto(s) adicionada(s) a “${m.titulo}”.`, 'ok');
    est.grupos = null;
    await carregarEntrada();
  } catch (e) { falhou(e); }
}
function dialogoAdicionarDaEntrada(m) {
  const marcadas = new Set();
  const fotos = est.entrada.fotos;
  abrirDialogo('Adicionar da caixa de entrada', fotos.length
    ? el('div', { class: 'fotos-grupo' }, fotos.map(f => el('label', { class: 'foto' },
      el('img', { src: `/api/imagem/entrada/${enc(f.arquivo)}?lado=240&g=${f.giro || 0}`, alt: f.arquivo }),
      el('figcaption', {}, el('input', { type: 'checkbox', onchange: e => e.target.checked ? marcadas.add(f.arquivo) : marcadas.delete(f.arquivo) }), ` ${soHora(f.hora)}`))))
    : el('p', { class: 'apagado', text: 'A caixa de entrada está vazia. Importe fotos primeiro.' }),
  [el('button', { class: 'botao primario', onclick: () => { if (marcadas.size) adicionarAMusica(m.id, [...marcadas]); fecharDialogo(); } }, 'Adicionar')]);
}

/* ------------------------------------------------------------------ importar arquivos (envio cru, um por vez) */
function escolherArquivos(musica = null) {
  const input = $('#arquivos');
  input.onchange = () => { importar([...input.files], musica); input.value = ''; };
  input.click();
}
function enviarUm(arquivo, aoProgredir) {
  return new Promise((ok, erro) => {
    const x = new XMLHttpRequest();
    x.open('PUT', `/api/entrada/${enc(arquivo.name)}`);
    x.setRequestHeader('X-Central', '1');
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    x.upload.onprogress = e => e.lengthComputable && aoProgredir(e.loaded / e.total);
    x.onload = () => {
      let d = null;
      try { d = JSON.parse(x.responseText); } catch { /* */ }
      x.status < 300 ? ok(d) : erro(new Error((d && d.erro) || `Erro ${x.status}`));
    };
    x.onerror = () => erro(new Error('Falha de rede ao enviar.'));
    x.send(arquivo);
  });
}
async function importar(arquivos, musica = null) {
  const validos = arquivos.filter(a => /\.(heic|heif|jpe?g|png|tiff?|webp|bmp|pdf)$/i.test(a.name));
  if (!validos.length) { aviso('Nenhum arquivo de foto ou PDF.', 'erro'); return; }
  const novos = [], repetidas = [];
  const progresso = el('div', { class: 'aviso' }, 'Enviando…');
  $('#avisos').append(progresso);
  for (const [i, a] of validos.entries()) {
    try {
      const r = await enviarUm(a, p => { progresso.textContent = `Enviando ${i + 1} de ${validos.length}: ${a.name} (${Math.round(p * 100)}%)`; });
      if (r.duplicada) repetidas.push(`${a.name} (já está em ${r.onde})`); else novos.push(r.arquivo);
    } catch (e) { falhou(e); }
  }
  progresso.remove();
  if (repetidas.length) aviso(`Já importadas antes, ignoradas: ${repetidas.join(', ')}`, 'erro', 10000);
  if (novos.length) aviso(`${novos.length} arquivo(s) importado(s).`, 'ok');
  if (musica && novos.length) await adicionarAMusica(musica, novos);
  else { est.grupos = null; await carregarEntrada(); if (novos.length) mostrarVista('entrada'); }
}

/* ------------------------------------------------------------------ fila (rodapé) */
function renderFila() {
  const f = $('#fila');
  const a = est.fila.atual;
  const partes = [];
  if (a) {
    const p = a.progresso || {};
    const det = p.i && p.n;
    const tempo = `${Math.floor(a.segundos / 60)}:${String(a.segundos % 60).padStart(2, '0')}`;
    const rotulo = a.tipo === 'revisao' ? 'Preparando revisão de' : a.tipo === 'acabar' ? 'Refazendo acabamento de' : 'Convertendo';
    partes.push(status('convertendo'),
      el('span', {}, `${rotulo} `, el('strong', { text: a.titulo }), ` · ${a.motor} · ${p.msg || ''} · `, el('span', { class: 'num', text: tempo })),
      el('div', { class: `progresso${det ? '' : ' indeterminado'}`, role: 'progressbar', 'aria-label': 'Progresso' },
        el('div', { style: `width:${det ? Math.round((p.i - 0.5) / p.n * 100) : 30}%` })),
      el('button', { class: 'botao mini', onclick: () => api('DELETE', `/api/fila/${enc(a.id)}`).then(() => aviso('Cancelando…')).catch(falhou) }, 'Cancelar'));
  } else {
    partes.push(el('span', { class: 'apagado', text: 'Fila vazia. As conversões aparecem aqui com o progresso.' }));
  }
  if (est.fila.fila.length) {
    partes.push(el('span', { class: 'proximos' }, `⏳ ${est.fila.fila.length} na fila: `,
      est.fila.fila.map((j, i) => el('span', {}, i ? ', ' : '', j.titulo, ' ',
        el('button', { class: 'botao mini fantasma', title: `Tirar “${j.titulo}” da fila`, 'aria-label': `Tirar ${j.titulo} da fila`,
          onclick: () => api('DELETE', `/api/fila/${enc(j.id)}`).catch(falhou) }, '✕')))));
  }
  f.replaceChildren(...limpos(partes));
}

/* ------------------------------------------------------------------ diálogos */
function abrirDialogo(titulo, corpo, botoes = []) {
  const d = $('#dialogo');
  d.replaceChildren(
    el('div', { class: 'dialogo-cab' }, el('h3', { text: titulo }), el('button', { class: 'botao fantasma', 'aria-label': 'Fechar', onclick: fecharDialogo }, '✕')),
    el('div', { class: 'dialogo-corpo' }, corpo),
    el('div', { class: 'dialogo-pe' }, el('button', { class: 'botao', onclick: fecharDialogo }, 'Fechar'), botoes));
  if (!d.open) d.showModal();
}
function fecharDialogo() { const d = $('#dialogo'); if (d.open) d.close(); }

function ampliar(m, i) {
  const p = m.paginas[i];
  abrirDialogo(`Página ${i + 1} de ${m.paginas.length} — ${p.arquivo}`,
    el('img', { class: 'ampliada', src: urlPagina(m, p, 2000), alt: `Página ${i + 1}` }),
    [i > 0 ? el('button', { class: 'botao', onclick: () => ampliar(m, i - 1) }, '← Anterior') : null,
      i < m.paginas.length - 1 ? el('button', { class: 'botao', onclick: () => ampliar(m, i + 1) }, 'Próxima →') : null]);
}

const OPCOES_ZIP = [
  ['fotos', 'Fotos originais, em ordem (pagina-01, pagina-02…)', true],
  ['relatorio', 'Relatório de conferência', true],
  ['musicxml', 'MusicXML (abre em qualquer editor de partitura)', true],
  ['transcricao', 'Transcrição assistida (se houver)', true],
  ['guias', 'Guias de altura (se houver)', false],
  ['logs', 'Registros técnicos dos motores', false],
];
function dialogoExportar(ids) {
  const incluir = Object.fromEntries(OPCOES_ZIP.map(([k, , v]) => [k, v]));
  const nomes = ids.map(id => (est.musicas.find(m => m.id === id) || {}).titulo).filter(Boolean);
  abrirDialogo('Exportar .zip', el('div', {},
    el('p', {}, 'Um único arquivo com tudo de ', el('strong', { text: nomes.length === 1 ? nomes[0] : `${nomes.length} músicas` }),
      ': o .mscz e o PDF (o arquivo revisado, se houver), e mais:'),
    el('div', { class: 'checklist' }, OPCOES_ZIP.map(([k, rotulo, v]) => el('label', {},
      el('input', { type: 'checkbox', checked: v, onchange: e => { incluir[k] = e.target.checked; } }), rotulo))),
    el('p', { class: 'apagado pequeno', text: 'O pacote é salvo na pasta exportados/, sem sobrescrever pacotes anteriores.' })),
  [el('button', { class: 'botao primario', onclick: async () => {
    try {
      const r = await api('POST', '/api/exportar', { musicas: ids, incluir });
      fecharDialogo();
      aviso(`Pacote salvo: ${r.nome}`, 'ok', 10000);
    } catch (e) { falhou(e); }
  } }, 'Exportar')]);
}

/* ---- ajuda: o MANUAL.md, renderizado com marcação mínima (escapada) */
function markdown(texto) {
  const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = s => esc(s).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  const out = [];
  let lista = null, tabela = null, codigo = null;
  const fechar = () => {
    if (lista) { out.push(`<${lista.tipo}>${lista.itens.map(i => `<li>${i}</li>`).join('')}</${lista.tipo}>`); lista = null; }
    if (tabela) { out.push(`<table>${tabela.map((l, i) => `<tr>${l.map(c => i ? `<td>${c}</td>` : `<th>${c}</th>`).join('')}</tr>`).join('')}</table>`); tabela = null; }
  };
  for (const linha of texto.split('\n')) {
    if (linha.startsWith('```')) {
      if (codigo) { out.push(`<pre><code>${esc(codigo.join('\n'))}</code></pre>`); codigo = null; } else { fechar(); codigo = []; }
      continue;
    }
    if (codigo) { codigo.push(linha); continue; }
    let m;
    if ((m = linha.match(/^(#{1,4})\s+(.*)/))) { fechar(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); }
    else if ((m = linha.match(/^\s*[-*]\s+(.*)/))) { if (!lista || lista.tipo !== 'ul') { fechar(); lista = { tipo: 'ul', itens: [] }; } lista.itens.push(inline(m[1])); }
    else if ((m = linha.match(/^\s*\d+[.)]\s+(.*)/))) { if (!lista || lista.tipo !== 'ol') { fechar(); lista = { tipo: 'ol', itens: [] }; } lista.itens.push(inline(m[1])); }
    else if (linha.trim().startsWith('|')) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(linha)) continue;
      if (!tabela) { fechar(); tabela = []; }
      tabela.push(linha.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim())));
    }
    else if (!linha.trim()) fechar();
    else { fechar(); out.push(`<p>${inline(linha)}</p>`); }
  }
  fechar();
  return out.join('\n');
}
async function ajuda() {
  try {
    const r = await api('GET', '/api/manual');
    const corpo = el('div', { class: 'manual' });
    corpo.innerHTML = markdown(r.texto); // texto do manual local, escapado pelo renderizador acima
    abrirDialogo('Ajuda — manual de uso', corpo);
  } catch (e) { falhou(e); }
}

/* ------------------------------------------------------------------ navegação, tema, arrastar arquivos */
function mostrarVista(v) {
  est.vista = v;
  for (const b of document.querySelectorAll('.abas button')) b.setAttribute('aria-selected', String(b.dataset.vista === v));
  $('#vista-musicas').hidden = v !== 'musicas';
  $('#vista-entrada').hidden = v !== 'entrada';
  if (v === 'entrada') renderEntrada(true);
}
function aplicarTema(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
function trocarTema() {
  const escuroAgora = getComputedStyle(document.documentElement).colorScheme.includes('dark');
  const novo = escuroAgora ? 'light' : 'dark';
  aplicarTema(novo);
  try { localStorage.setItem('tema', novo); } catch { /* sem armazenamento: só nesta sessão */ }
}

function iniciarArrastar() {
  let profundidade = 0;
  const temArquivos = e => [...(e.dataTransfer && e.dataTransfer.types || [])].includes('Files');
  window.addEventListener('dragenter', e => { if (temArquivos(e)) { profundidade++; $('#soltar').hidden = false; } });
  window.addEventListener('dragleave', e => { if (temArquivos(e) && --profundidade <= 0) { profundidade = 0; $('#soltar').hidden = true; } });
  window.addEventListener('dragover', e => { if (temArquivos(e)) e.preventDefault(); });
  window.addEventListener('drop', e => {
    if (!temArquivos(e)) return;
    e.preventDefault(); profundidade = 0; $('#soltar').hidden = true;
    const destino = est.vista === 'musicas' && e.target.closest && e.target.closest('.paginas') ? est.selecionada : null;
    importar([...e.dataTransfer.files], destino);
  });
}

/* ------------------------------------------------------------------ ciclo de atualização */
let sessaoPerdida = false;
async function ciclo() {
  try {
    const e = await api('GET', '/api/estado');
    est.fila = e.fila;
    est.motores = e.motores;
    const mudou = JSON.stringify(e.revisoes) !== JSON.stringify(est.revisoes);
    est.revisoes = e.revisoes;
    if (e.entrada !== est.entradaQtd) { est.entradaQtd = e.entrada; await carregarEntrada(); }
    if (mudou) await carregarMusicas();
    renderFila(); renderKPIs();
    sessaoPerdida = false;
  } catch (err) {
    if (!sessaoPerdida) {
      sessaoPerdida = true;
      aviso(err.status === 403 ? 'Sessão encerrada. Feche esta janela e abra a Central pelo atalho.' :
        'A Central não está respondendo. Se ela foi fechada, abra de novo pelo atalho.', 'erro', 15000);
    }
  }
  setTimeout(ciclo, 2000);
}

document.addEventListener('focusout', () => setTimeout(() => {
  if (est.pendente && !editando()) { renderEditor(true); if (est.vista === 'entrada') renderEntrada(true); }
}, 50));

async function iniciar() {
  try { aplicarTema(localStorage.getItem('tema')); } catch { /* sem armazenamento */ }
  const bt = $('#bt-tema');
  const lua = svg('svg', { viewBox: '0 0 16 16', width: 16, height: 16, 'aria-hidden': 'true' },
    svg('path', { d: 'M13.5 10.2A6 6 0 0 1 5.8 2.5 6 6 0 1 0 13.5 10.2z', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.5, 'stroke-linejoin': 'round' }));
  bt.replaceChildren(lua);
  bt.onclick = trocarTema;
  $('#bt-ajuda').onclick = ajuda;
  $('#bt-importar').onclick = () => escolherArquivos(null);
  $('#bt-exportar-sel').onclick = () => dialogoExportar([...est.selecaoExport]);
  $('#busca').oninput = e => { est.busca = e.target.value; renderLista(); };
  for (const b of document.querySelectorAll('.abas button')) b.onclick = () => mostrarVista(b.dataset.vista);
  iniciarArrastar();
  try {
    await Promise.all([carregarMusicas(), carregarEntrada()]);
  } catch (e) { falhou(e); }
  renderFila();
  if (location.hash === '#entrada') mostrarVista('entrada');
  ciclo();
}
iniciar();
