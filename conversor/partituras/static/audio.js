/* Central de Partituras — modo de áudio: importar (arquivo ou link), blocos do editor, relatório com linha do
   tempo e escuta A/B por trecho, ajustes que refazem só a transcrição. Usa os utilitários do app.js (el, svg,
   api, est, aviso…), sempre dentro de funções: este arquivo é carregado antes dele. */
'use strict';

const AUDIO_EXT = /\.(mp3|wav|flac|ogg|oga|opus|m4a|aac|webm|mka|mp4|aif|aiff|wma)$/i;
function eAudio(nome) { return AUDIO_EXT.test(nome || ''); }
function mmss(s) { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function instrumentoLembrado() {
  try { const v = localStorage.getItem('central-instrumento'); if (v) return v; } catch { /* sem armazenamento */ }
  return est.instrumentoPadrao || 'sax-tenor';
}
function nomeInstrumento(id) { return ((est.instrumentos || []).find(i => i.id === id) || {}).nome || id || ''; }
function seletorInstrumento(valor, aoMudar, attrs = {}) {
  return el('select', { class: 'campo', ...attrs, onchange: e => aoMudar(e.target.value) },
    (est.instrumentos || []).map(i => el('option', { value: i.id, selected: i.id === valor }, i.nome)));
}

/* ------------------------------------------------------------------ importar */
function dialogoImportarAudio(arquivo = null) {
  const disp = est.audio || {};
  let escolhido = arquivo;
  const nomeArq = el('span', { class: 'apagado', text: arquivo ? arquivo.name : 'nenhum arquivo escolhido' });
  const titulo = el('input', { class: 'campo', id: 'ia-titulo', value: arquivo ? arquivo.name.replace(AUDIO_EXT, '') : '', placeholder: 'Título da música' });
  const semLink = disp.link === false;
  const link = el('input', { class: 'campo', id: 'ia-link', type: 'url', placeholder: 'https://www.youtube.com/watch?v=…', disabled: semLink });
  let instrumento = instrumentoLembrado();
  const converter = el('input', { type: 'checkbox', checked: true });
  const entrada = $('#arquivos-audio');
  const escolher = el('button', { class: 'botao', type: 'button', onclick: () => {
    entrada.onchange = () => {
      const f = entrada.files[0]; entrada.value = '';
      if (!f) return;
      escolhido = f; nomeArq.textContent = f.name; link.value = '';
      if (!titulo.value) titulo.value = f.name.replace(AUDIO_EXT, '');
    };
    entrada.click();
  } }, 'Escolher arquivo…');
  const corpo = el('div', { class: 'importar-audio' },
    disp.pronto === false ? el('div', { class: 'aviso-cartao' }, el('span', { 'aria-hidden': 'true', text: '▲ ' }),
      `O modo de áudio ainda não está instalado: falta ${(disp.falta || []).join('; ')}. Você pode importar agora e converter depois.`) : null,
    el('div', { class: 'linha-saida' }, escolher, nomeArq),
    el('label', { class: 'rotulo', for: 'ia-link', text: 'ou cole um link (um vídeo só, sem playlists)' }), link,
    semLink && disp.pronto ? el('p', { class: 'apagado pequeno', text: 'Importar por link precisa do yt-dlp e do Node.js: rode conversor/instalar.sh --audio de novo.' }) : null,
    el('p', { class: 'apagado pequeno', text: 'Os Termos do YouTube não permitem baixar fora dos recursos do próprio site: usar o link fica por sua conta. Um arquivo seu (gravação, compra sem perdas) dá resultado melhor.' }),
    el('div', { class: 'grade-campos' },
      el('div', {}, el('label', { class: 'rotulo', for: 'ia-titulo', text: 'Título' }), titulo),
      el('div', {}, el('label', { class: 'rotulo', for: 'ia-inst', text: 'Instrumento a transcrever' }),
        seletorInstrumento(instrumento, v => { instrumento = v; }, { id: 'ia-inst' }))),
    el('label', {}, converter, ' Separar e transcrever em seguida (a separação leva cerca de 3× a duração da música)'));
  abrirDialogo('Importar áudio', corpo, [
    el('button', { class: 'botao primario', onclick: async () => {
      try { localStorage.setItem('central-instrumento', instrumento); } catch { /* */ }
      const url = link.value.trim();
      if (!escolhido && !url) { aviso('Escolha um arquivo de áudio ou cole um link.', 'erro'); return; }
      fecharDialogo();
      try {
        const r = url && !escolhido
          ? await api('POST', '/api/audio/link', { url, titulo: titulo.value.trim(), instrumento, converter: converter.checked })
          : await enviarAudio(escolhido, { titulo: titulo.value.trim(), instrumento, converter: converter.checked ? '1' : '0' });
        if (r.aviso) aviso(r.aviso, 'erro', 10000);
        else aviso(url && !escolhido ? 'Baixando o áudio do link…' : `“${r.musica.titulo}” importada${converter.checked ? ' e na fila' : ''}.`, 'ok');
        est.selecionada = r.musica.id;
        mostrarVista('musicas');
        await carregarMusicas();
      } catch (e) { falhou(e); }
    } }, 'Importar'),
  ]);
}
function enviarAudio(arquivo, params) {
  return new Promise((ok, erro) => {
    const progresso = el('div', { class: 'aviso' }, 'Enviando o áudio…');
    $('#avisos').append(progresso);
    const x = new XMLHttpRequest();
    x.open('PUT', `/api/audio/arquivo/${enc(arquivo.name)}?${new URLSearchParams(params)}`);
    x.setRequestHeader('X-Central', '1');
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    x.upload.onprogress = e => { if (e.lengthComputable) progresso.textContent = `Enviando ${arquivo.name} (${Math.round(e.loaded / e.total * 100)}%)`; };
    x.onload = () => {
      progresso.remove();
      let d = null;
      try { d = JSON.parse(x.responseText); } catch { /* */ }
      if (x.status === 409 && d && d.onde) { est.selecionada = d.onde; carregarMusicas(); }
      x.status < 300 ? ok(d) : erro(new Error((d && d.erro) || `Erro ${x.status}`));
    };
    x.onerror = () => { progresso.remove(); erro(new Error('Falha de rede ao enviar.')); };
    x.send(arquivo);
  });
}

/* ------------------------------------------------------------------ player (um só, fora do editor) */
const player = { a: null, b: null, fim: null, rotulo: null, barra: null };
function garantirPlayer() {
  if (player.barra) return;
  player.a = new Audio(); player.b = new Audio();
  for (const x of [player.a, player.b]) x.preload = 'none';
  player.rotulo = el('span', { class: 'pequeno' });
  player.barra = el('div', { class: 'player-audio', hidden: true, role: 'region', 'aria-label': 'Reprodução' },
    el('span', { 'aria-hidden': 'true', text: '♫ ' }), player.rotulo,
    el('button', { class: 'botao mini', onclick: pararAudio }, 'Parar'));
  document.body.append(player.barra);
  player.a.addEventListener('timeupdate', () => {
    if (player.fim != null && player.a.currentTime >= player.fim) pararAudio();
    else player.rotulo.dataset.t = mmss(player.a.currentTime);
  });
  player.a.addEventListener('ended', pararAudio);
}
function pararAudio() {
  if (!player.barra) return;
  player.a.pause(); player.b.pause(); player.fim = null; player.barra.hidden = true;
  document.body.classList.remove('tocando');
}
async function tocarAudio(rotulo, fonteA, fonteB, inicio, fim) {
  garantirPlayer();
  pararAudio();
  player.a.src = fonteA; player.a.volume = fonteB ? 0.55 : 1;
  if (fonteB) { player.b.src = fonteB; player.b.volume = 1; }
  player.fim = fim;
  player.rotulo.textContent = rotulo;
  player.barra.hidden = false;
  document.body.classList.add('tocando');
  const iniciar = x => new Promise((ok, erro) => {
    x.addEventListener('loadedmetadata', () => { x.currentTime = inicio; ok(); }, { once: true });
    x.addEventListener('error', () => erro(new Error('Não consegui carregar o áudio.')), { once: true });
    x.load();
  });
  try {
    await Promise.all(fonteB ? [iniciar(player.a), iniciar(player.b)] : [iniciar(player.a)]);
    await Promise.all(fonteB ? [player.a.play(), player.b.play()] : [player.a.play()]);
  } catch (e) { pararAudio(); falhou(e); }
}

/* ------------------------------------------------------------------ editor */
function blocoAudio(m) {
  const a = m.audio || {};
  const pres = a.presenca || {};
  const origem = a.origem === 'link' ? el('a', { href: a.url, target: '_blank', rel: 'noopener', text: a.url }) : (a.nome_original || 'arquivo');
  const detalhes = [a.codec, a.kbps ? `${a.kbps} kb/s` : null, a.taxa ? `${(a.taxa / 1000).toFixed(1)} kHz` : null, a.duracao ? mmss(a.duracao) : null].filter(Boolean).join(' · ');
  return el('section', { class: 'bloco' }, el('h3', { text: 'Áudio' }),
    el('p', {}, el('strong', { text: a.origem === 'link' ? 'Link: ' : 'Arquivo: ' }), origem),
    a.estado === 'baixando' ? el('p', { class: 'apagado', text: 'Baixando o áudio do link…' }) : null,
    a.estado === 'erro' || a.estado === 'interrompido' ? el('div', { class: 'erro-cartao', text: a.erro || 'O download falhou.' }) : null,
    detalhes ? el('p', { class: 'apagado pequeno', text: detalhes }) : null,
    a.aviso || a.com_perdas ? el('div', { class: 'aviso-cartao' }, el('span', { 'aria-hidden': 'true', text: '▲ ' }),
      a.aviso || 'Áudio com perdas: serve para isolar uma linha em evidência, mas um arquivo sem perdas é sempre melhor.') : null,
    el('div', { class: 'grade-campos', style: 'margin-top:10px' },
      el('div', {}, el('label', { class: 'rotulo', for: 'c-inst-alvo', text: 'Instrumento a transcrever' }),
        seletorInstrumento(m.instrumento_alvo, v => salvar(m, { instrumento_alvo: v }), { id: 'c-inst-alvo' }),
        el('div', { class: 'apagado pequeno', text: 'Define o que separar, onde procurar as notas e como escrever a parte (transposição, clave).' })),
      Object.keys(pres).length ? el('div', {}, el('span', { class: 'rotulo', text: 'Presença na gravação' }),
        el('div', { class: 'pequeno', text: Object.entries(pres).filter(([s]) => s !== 'vocal').map(([s, v]) => `${({ saxophone: 'sax', trumpet: 'trompete', trombone: 'trombone' })[s] || s} ${Math.round(v * 100)}%`).join(' · ') })) : null),
    a.estado === 'pronto' ? el('div', { class: 'barra-acoes', style: 'margin-top:8px' },
      el('button', { class: 'botao', onclick: () => tocarAudio(`${m.titulo} — gravação`, urlAudio(m, a.arquivo ? 'mistura' : 'original'), null, 0, null)
        .catch(() => tocarAudio(`${m.titulo} — gravação`, urlAudio(m, 'original'), null, 0, null)) }, '▶ Ouvir a gravação')) : null);
}
function urlAudio(m, qual) { return `/api/musicas/${enc(m.id)}/audio/${enc(qual)}`; }
function blocoDadosAudio(m) {
  return el('section', { class: 'bloco' }, el('h3', { text: 'Dados da música' }),
    el('div', { class: 'grade-campos' },
      campoTexto(m, 'instrumento', 'Nome da parte'),
      campoTexto(m, 'compositor', 'Compositor / arranjo', { placeholder: 'Ex.: compositor / arr. arranjador' })));
}
function blocoConversaoAudio(m) {
  const pasta = m.saida && m.saida.pasta;
  const disp = est.audio || {};
  const pronto = (m.audio || {}).estado === 'pronto';
  return el('section', { class: 'bloco' }, el('h3', { text: 'Conversão' }),
    disp.pronto === false ? el('div', { class: 'aviso-cartao' }, el('span', { 'aria-hidden': 'true', text: '▲ ' }),
      `O modo de áudio não está instalado: falta ${(disp.falta || []).join('; ')}.`) : null,
    el('p', { class: 'apagado pequeno', text: 'Separa o instrumento (cerca de 3× a duração da música na sua GPU; feito uma vez por música), acha os trechos em que ele toca e transcreve. Ajustes depois refazem só a transcrição, em segundos.' }),
    el('div', { class: 'grade-campos', style: 'margin-top:8px' },
      el('div', { class: 'campo-largo' }, el('label', { class: 'rotulo', text: 'Pasta de saída' }),
        el('div', { class: 'linha-saida' },
          el('input', { class: 'campo', readonly: true, value: curto(pasta) || `${curto(est.saidaPadrao)} (padrão)`, title: pasta || est.saidaPadrao }),
          el('button', { class: 'botao', onclick: () => escolherPasta(m) }, 'Escolher…'),
          pasta ? el('button', { class: 'botao fantasma', onclick: () => salvar(m, { saida: { pasta: null, nome: m.saida.nome } }) }, 'Padrão') : null)),
      el('div', {}, el('label', { class: 'rotulo', for: 'c-nome', text: 'Nome do arquivo (.mscz)' }),
        el('input', { class: 'campo', id: 'c-nome', value: (m.saida && m.saida.nome) || '', placeholder: [m.titulo, m.instrumento].filter(Boolean).join(' - '),
          onchange: e => salvar(m, { saida: { pasta: m.saida.pasta, nome: e.target.value || null } }) }))),
    el('div', { class: 'barra-acoes', style: 'margin-top:12px' },
      el('label', {}, el('input', { type: 'checkbox', checked: m.opcoes.pdf, onchange: e => salvar(m, { opcoes: { ...m.opcoes, pdf: e.target.checked } }) }), ' Gerar PDF')),
    el('p', { class: 'apagado pequeno', text: 'Nunca sobrescreve: se já existir um arquivo com esse nome, salva como “Nome (2)”.' }),
    el('button', { class: 'botao primario', disabled: !pronto || ocupada(m), onclick: () => converter(m) },
      ocupada(m) ? 'Na fila…' : '▶ Separar e transcrever'));
}

/* ------------------------------------------------------------------ relatório */
function relatorioAudio(m, c, rel, chave) {
  const v = c.versoes[c.versoes.length - 1];
  const inst = nomeInstrumento(c.instrumento || rel.instrumento);
  const curto_ = (inst.split(' ')[0] || 'instrumento').toLowerCase();
  const aj = est.ajustes[chave] || (est.ajustes[chave] = {
    trechos: Object.fromEntries(rel.trechos.map(t => [String(t.indice), t.incluido !== false])),
    compasso: (rel.ajustes || {}).compasso || '', rotacao: (rel.ajustes || {}).rotacao ?? '',
    andamento: (rel.ajustes || {}).andamento || 'auto', grade: (rel.ajustes || {}).grade || 4,
  });
  const base = `/api/musicas/${enc(m.id)}/conversoes/${enc(c.id)}/versoes/${v.n}`;
  const stem = ({ 'Sax': 'saxophone', 'Trompete': 'trumpet', 'Trombone': 'trombone' })[inst.split(' ')[0]] || 'saxophone';
  const ouvir = (t, modo) => {
    const ini = Math.max(0, t.inicio - 0.6), fim = t.fim + 0.6;
    const rot = `Trecho ${t.indice} — ${({ original: 'gravação', isolado: `só o ${curto_}`, transcricao: 'transcrição sobre a gravação' })[modo]}`;
    if (modo === 'original') return tocarAudio(rot, urlAudio(m, 'mistura'), null, ini, fim);
    if (modo === 'isolado') return tocarAudio(rot, urlAudio(m, stem), null, ini, fim);
    return tocarAudio(rot, urlAudio(m, 'mistura'), `${base}/sintese.flac`, ini, fim);
  };
  const incluidos = rel.trechos.filter(t => aj.trechos[String(t.indice)] !== false).length;
  const fora = rel.fora_extensao.length;
  const blocos = el('div', { class: 'blocos-relatorio' },
    blocoNumero('Trechos', rel.trechos.length, `${incluidos} na partitura`),
    blocoNumero('Notas', rel.notas, `${rel.baixa_confianca} de baixa confiança`),
    blocoNumero('Andamento', Math.round(rel.bpm), `BPM · compasso ${rel.compasso}`),
    blocoNumero('Tom da parte', rel.tom_escrito || '—', `som real: ${rel.tom_som}`),
    blocoNumero('Fora da extensão', fora, fora ? 'veja abaixo' : 'nenhuma nota'));
  const lista = el('div', { class: 'trechos-audio' }, rel.trechos.map(t => {
    const dentro = aj.trechos[String(t.indice)] !== false;
    return el('div', { class: `trecho-audio${dentro ? '' : ' fora'}` },
      el('label', { class: 'trecho-incluir' }, el('input', { type: 'checkbox', checked: dentro, 'aria-label': `Incluir o trecho ${t.indice} na partitura`,
        onchange: e => { aj.trechos[String(t.indice)] = e.target.checked; e.target.closest('.trecho-audio').classList.toggle('fora', !e.target.checked); } }),
        el('strong', { text: `Trecho ${t.indice}` })),
      el('span', { class: 'pequeno', text: `${mmss(t.inicio)}–${mmss(t.fim)} · ${t.incluido === false ? 'fora desta versão' : `c. ${t.compasso_ini}–${t.compasso_fim} · ${t.notas} notas${t.baixa_confianca ? ` (${t.baixa_confianca} duvidosas)` : ''}`}${t.voz_ativa_pct ? ` · voz junto ${t.voz_ativa_pct}%` : ''}` }),
      el('div', { class: 'barra-acoes' },
        el('button', { class: 'botao mini', onclick: () => ouvir(t, 'original') }, '▶ Gravação'),
        el('button', { class: 'botao mini', onclick: () => ouvir(t, 'isolado') }, `▶ Só o ${curto_}`),
        el('button', { class: 'botao mini primario', disabled: t.incluido === false, title: t.incluido === false ? 'Este trecho ficou fora desta versão' : '',
          onclick: () => ouvir(t, 'transcricao') }, '▶ Transcrição + gravação'),
        el('button', { class: 'botao mini fantasma', onclick: () => abrirDialogo(`Trecho ${t.indice}: curva de altura e notas`,
          el('img', { src: `${base}/trecho-${String(t.indice).padStart(2, '0')}.png`, alt: `Espectrograma do trecho ${t.indice} com a curva de altura e as notas`, style: 'max-width:100%' })) }, 'Ver curva')));
  }));
  const sel = (rotulo, valor, opcoes, chaveAj, conv = x => x) => el('label', { class: 'pequeno' }, rotulo, ' ',
    el('select', { class: 'campo', style: 'width:auto;display:inline-block', onchange: e => { aj[chaveAj] = conv(e.target.value); } },
      opcoes.map(([v_, t_]) => el('option', { value: v_, selected: String(v_) === String(valor) }, t_))));
  const ajustes = el('div', { class: 'ajustes-audio' },
    el('h4', { style: 'margin:16px 0 4px', text: 'Ajustes (refazem só a transcrição, em segundos)' }),
    el('div', { class: 'barra-acoes' },
      sel('Compasso', aj.compasso, [['', `como detectado (${rel.compasso_detectado || rel.compasso})`], [2, '2/4'], [3, '3/4'], [4, '4/4'], [5, '5/4'], [6, '6/4']], 'compasso'),
      sel('1º tempo', aj.rotacao, [['', 'como detectado'], [0, 'deslocar 0'], [1, '+1 tempo'], [2, '+2 tempos'], [3, '+3 tempos']], 'rotacao'),
      sel('Andamento', aj.andamento, [['auto', 'como detectado'], ['dobro', 'dobro (detectou metade)'], ['metade', 'metade (detectou o dobro)']], 'andamento'),
      sel('Menor figura', aj.grade, [[4, 'semicolcheia'], [2, 'colcheia']], 'grade', Number),
      el('button', { class: 'botao primario', disabled: ocupada(m), onclick: async () => {
        const ajustes_ = { trechos: aj.trechos, andamento: aj.andamento, grade: aj.grade };
        if (aj.compasso !== '') ajustes_.compasso = Number(aj.compasso);
        if (aj.rotacao !== '' && aj.rotacao != null) ajustes_.rotacao = Number(aj.rotacao);
        try {
          await api('POST', `/api/musicas/${enc(m.id)}/conversoes/${enc(c.id)}/acabar`, { ajustes: ajustes_ });
          delete est.ajustes[chave];
          aviso('Refazendo a transcrição com os ajustes…', 'ok');
          carregarMusicas();
        } catch (e) { falhou(e); }
      } }, ocupada(m) ? 'Na fila…' : 'Refazer transcrição')));
  const extensao = fora ? el('details', { class: 'mais' }, el('summary', { text: `Notas fora da extensão normal (${fora})` }),
    el('ul', {}, rel.fora_extensao.map(f => el('li', { text: `c. ${f.compasso}: ${f.nome || f.nota}${f.acima ? ' (acima da extensão normal)' : ' (abaixo da extensão)'}` })))) : null;
  return [blocos, linhaDoTempo(rel, aj, t => ouvir(t, t.incluido === false ? 'original' : 'transcricao')), lista, ajustes, extensao,
    el('p', { class: 'apagado pequeno', text: `A transcrição não traz dinâmicas, articulações nem efeitos (bends, quedas, growl): acrescente no MuseScore. Segmentação: ${rel.segmentacao}.` })];
}

/* linha do tempo: a música inteira, um retângulo por trecho (cor = na partitura; contorno = fora) */
function linhaDoTempo(rel, aj, aoEscolher) {
  const dur = Math.max(1, ...rel.trechos.map(t => t.fim)) * 1.02;
  const L = 1000, A = 58;
  const s = svg('svg', { viewBox: `0 0 ${L} ${A}`, class: 'linha-tempo', role: 'img', 'aria-label': `Linha do tempo: ${rel.trechos.length} trechos com o instrumento` });
  s.append(svg('line', { x1: 0, y1: 42, x2: L, y2: 42, stroke: 'var(--linha)', 'stroke-width': 2 }));
  for (let m_ = 0; m_ <= dur; m_ += 60) {  // eixo abaixo dos trechos: os rótulos nunca ficam cobertos
    const x = m_ / dur * L;
    s.append(svg('line', { x1: x, y1: 40, x2: x, y2: 46, stroke: 'var(--apagado)', 'stroke-width': 1 }));
    s.append(svg('text', { x: Math.min(x + 2, L - 24), y: 56, 'font-size': 9, fill: 'var(--apagado)' }, mmss(m_)));
  }
  for (const t of rel.trechos) {
    const dentro = aj.trechos[String(t.indice)] !== false;
    const x = t.inicio / dur * L, w = Math.max(4, (t.fim - t.inicio) / dur * L);
    const r = svg('rect', { x, y: 15, width: w, height: 24, rx: 3, tabindex: 0, role: 'button',
      fill: dentro ? 'var(--destaque)' : 'var(--superficie)', stroke: 'var(--destaque)', 'stroke-width': 1.5,
      'aria-label': `Trecho ${t.indice}, ${mmss(t.inicio)} a ${mmss(t.fim)}${dentro ? '' : ', fora da partitura'}: ouvir` });
    r.append(svg('title', {}, `Trecho ${t.indice} · ${mmss(t.inicio)}–${mmss(t.fim)} · c. ${t.compasso_ini}–${t.compasso_fim} · clique para ouvir`));
    r.addEventListener('click', () => aoEscolher(t));
    r.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); aoEscolher(t); } });
    s.append(r);
    if (w > 14) s.append(svg('text', { x: x + w / 2, y: 13, 'text-anchor': 'middle', 'font-size': 10, fill: 'var(--tinta-2)' }, t.indice));
  }
  return el('div', { class: 'mapa' }, s,
    el('div', { class: 'legenda pequeno' },
      el('span', {}, el('span', { class: 'amostra cheia' }), ' na partitura'),
      el('span', {}, el('span', { class: 'amostra vazia' }), ' fora da partitura'),
      el('span', { class: 'apagado' }, 'clique num trecho para ouvir a transcrição sobre a gravação')));
}

const ITENS_CHECKLIST_AUDIO = [
  ['trechos', 'Trechos conferidos (os que não são do instrumento ficaram de fora)'],
  ['ritmo', 'Andamento, compasso e posição do 1º tempo conferidos'],
  ['notas', 'Notas e ligaduras conferidas no MuseScore'],
  ['ouvida', 'Ouvi a transcrição junto com a gravação'],
];
