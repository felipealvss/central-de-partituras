"""Biblioteca de músicas em disco: caixa de entrada, músicas (musica.json), páginas e histórico de conversões.

Só o servidor grava aqui (o processo de conversão grava apenas dentro da pasta da sua conversão).
Gravações atômicas, com trava, e número de revisão: duas edições sobre a mesma versão → Conflito.
"""
import json
import os
import re
import shutil
import threading
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from . import fotos
from .imagens import EXTENSOES
from .publicar import nome_seguro, para_lixeira

FORMATO = 1
MOTORES = ('homr', 'audiveris', 'ambos')
CHECKLIST = ('pausas', 'ligaduras', 'dinamicas', 'ouvida')


class Conflito(Exception):
    """A música mudou depois que a interface a leu."""

    def __init__(self, atual):
        super().__init__('A música foi alterada em outro lugar; recarregue.')
        self.atual = atual


class NaoEncontrado(Exception):
    pass


class Invalido(Exception):
    pass


def slug(texto):
    t = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode()
    t = re.sub(r'[^a-zA-Z0-9]+', '-', t).strip('-').lower()
    return t[:60].strip('-') or 'musica'


def agora():
    return datetime.now().isoformat(timespec='seconds')


def _gravar_json(caminho, dados):
    caminho = Path(caminho)
    tmp = caminho.with_name(f'.{caminho.name}.{uuid.uuid4().hex[:8]}.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, caminho)


def _ler_json(caminho, padrao):
    try:
        return json.loads(Path(caminho).read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def _destino_livre(pasta, nome):
    destino = Path(pasta) / nome
    base, ext = destino.stem, destino.suffix
    n = 2
    while destino.exists():
        destino = destino.with_name(f'{base} ({n}){ext}')
        n += 1
    return destino


class Biblioteca:
    def __init__(self, raiz):
        self.raiz = Path(raiz)
        self.musicas = self.raiz / 'musicas'
        self.entrada = self.raiz / 'entrada'
        self.partituras = self.raiz / 'partituras'
        self.exportados = self.raiz / 'exportados'
        self.estado = self.raiz / '.estado'
        for p in (self.musicas, self.entrada, self.partituras, self.exportados, self.estado):
            p.mkdir(parents=True, exist_ok=True)
        self.miniaturas = self.estado / 'miniaturas'
        self._trava = threading.RLock()
        self._arq_indice = self.estado / 'fotos.json'
        self._indice = _ler_json(self._arq_indice, {})

    # ------------------------------------------------------------ fotos
    def info_foto(self, caminho):
        """id (conteúdo), hora em que foi tirada e tipo; com cache por arquivo/tamanho/data."""
        caminho = Path(caminho)
        st = caminho.stat()
        chave = f'{caminho}|{st.st_size}|{st.st_mtime_ns}'
        with self._trava:
            info = self._indice.get(chave)
            if info is None:
                hora, origem = fotos.hora_da_foto(caminho)
                info = {'id': fotos.identificar(caminho), 'hora': hora.isoformat(timespec='milliseconds'),
                        'origem_hora': origem}
                if caminho.suffix.lower() == '.pdf':
                    info['paginas'] = fotos.paginas_do_pdf(caminho)
                self._indice[chave] = info
                _gravar_json(self._arq_indice, self._indice)
        return {**info, 'arquivo': caminho.name, 'tamanho': st.st_size,
                'tipo': 'pdf' if caminho.suffix.lower() == '.pdf' else 'imagem'}

    def _arquivos(self, pasta):
        if not pasta.exists():
            return []
        return sorted(p for p in pasta.iterdir()
                      if p.is_file() and not p.name.startswith('.') and p.suffix.lower() in EXTENSOES)

    def todos_ids(self):
        """{id da foto: onde está} — para detectar fotos repetidas."""
        ids = {}
        for p in self._arquivos(self.entrada):
            ids[self.info_foto(p)['id']] = 'caixa de entrada'
        for pasta in self.musicas.iterdir() if self.musicas.exists() else []:
            for p in self._arquivos(pasta / 'paginas'):
                ids[self.info_foto(p)['id']] = pasta.name
        return ids

    # ------------------------------------------------------------ caixa de entrada
    def _giros_entrada(self):
        return _ler_json(self.estado / 'giros-entrada.json', {})

    def fotos_entrada(self):
        giros = self._giros_entrada()
        itens = [{**self.info_foto(p), 'giro': giros.get(p.name, 0)} for p in self._arquivos(self.entrada)]
        return sorted(itens, key=lambda f: (f['hora'], f['arquivo']))

    def importar(self, nome, fluxo, destino=None):
        """Grava um arquivo enviado (fluxo binário) na caixa de entrada ou nas páginas de uma música."""
        nome = nome_seguro(Path(nome).name, 'foto')
        if Path(nome).suffix.lower() not in EXTENSOES:
            raise Invalido(f'"{nome}" não é foto nem PDF.')
        pasta = destino or self.entrada
        pasta.mkdir(parents=True, exist_ok=True)
        tmp = pasta / f'.{uuid.uuid4().hex}.parcial'
        with open(tmp, 'wb') as f:
            shutil.copyfileobj(fluxo, f, 1 << 20)
        try:
            novo_id = fotos.identificar(tmp)
            existentes = self.todos_ids()
            if novo_id in existentes:
                return {'duplicada': True, 'arquivo': nome, 'onde': existentes[novo_id]}
            with self._trava:
                final = _destino_livre(pasta, nome)
                os.replace(tmp, final)
            return {'duplicada': False, **self.info_foto(final)}
        finally:
            tmp.unlink(missing_ok=True)

    def girar_entrada(self, arquivo, giro):
        with self._trava:
            giros = self._giros_entrada()
            giros[arquivo] = int(giro) % 360
            _gravar_json(self.estado / 'giros-entrada.json', giros)

    def descartar_entrada(self, arquivo):
        caminho = self._na_entrada(arquivo)
        para_lixeira(caminho)

    def _na_entrada(self, arquivo):
        caminho = (self.entrada / Path(arquivo).name)
        if not caminho.is_file():
            raise NaoEncontrado(f'"{arquivo}" não está na caixa de entrada.')
        return caminho

    def grupos_sugeridos(self, limiar=90):
        return fotos.sugerir_grupos(self.fotos_entrada(), limiar)

    # ------------------------------------------------------------ músicas
    def _pasta(self, mid):
        pasta = self.musicas / Path(mid).name
        if not (pasta / 'musica.json').exists():
            raise NaoEncontrado(f'Música "{mid}" não encontrada.')
        return pasta

    def ler(self, mid):
        return _ler_json(self._pasta(mid) / 'musica.json', None)

    def _salvar(self, m):
        m['atualizada'] = agora()
        _gravar_json(self.musicas / m['id'] / 'musica.json', m)
        return m

    def listar(self):
        lista = []
        for pasta in sorted(self.musicas.iterdir()) if self.musicas.exists() else []:
            m = _ler_json(pasta / 'musica.json', None)
            if m:
                lista.append(m)
        return lista

    def nome_padrao(self, m):
        titulo = m.get('titulo') or 'Partitura'
        return nome_seguro(f"{titulo} - {m['instrumento']}" if m.get('instrumento') else titulo)

    def saida(self, m):
        s = m.get('saida') or {}
        return Path(s['pasta']) if s.get('pasta') else self.partituras, s.get('nome') or self.nome_padrao(m)

    def _novo_id(self, titulo):
        base = slug(titulo)
        mid, n = base, 2
        while (self.musicas / mid).exists():
            mid = f'{base}-{n}'
            n += 1
        return mid

    def criar(self, titulo, arquivos_entrada=(), **campos):
        titulo = (titulo or '').strip() or 'Música sem título'
        with self._trava:
            origens = [self._na_entrada(a) for a in arquivos_entrada]
            giros = self._giros_entrada()
            mid = self._novo_id(titulo)
            pasta = self.musicas / mid
            (pasta / 'paginas').mkdir(parents=True)
            (pasta / 'conversoes').mkdir()
            m = {'formato': FORMATO, 'id': mid, 'titulo': titulo, 'instrumento': '', 'compositor': '',
                 'ultimo_compasso': None, 'clave': 'fa', 'paginas': [], 'motor': 'homr',
                 'opcoes': {'pdf': True, 'guias': None}, 'saida': {'pasta': None, 'nome': None},
                 'estado': 'nova', 'revisada': False, 'checklist': {k: False for k in CHECKLIST},
                 'conversoes': [], 'revisao': 1, 'criada': agora()}
            self._mover_para(m, origens, giros)
            for k, v in campos.items():
                if k in ('instrumento', 'compositor', 'ultimo_compasso', 'motor', 'clave'):
                    m[k] = v
            return self._salvar(m)

    def _mover_para(self, m, origens, giros):
        """Move arquivos da caixa de entrada para as páginas da música, em ordem de hora."""
        infos = sorted((self.info_foto(o) | {'origem': o} for o in origens), key=lambda f: f['hora'])
        destino_dir = self.musicas / m['id'] / 'paginas'
        for info in infos:
            destino = _destino_livre(destino_dir, info['origem'].name)
            shutil.move(info['origem'], destino)
            m['paginas'].append({'arquivo': destino.name, 'giro': giros.pop(info['origem'].name, 0),
                                 'hora': info['hora'], 'tipo': info['tipo']})
        _gravar_json(self.estado / 'giros-entrada.json', giros)

    def atualizar(self, mid, revisao, mudancas):
        with self._trava:
            m = self.ler(mid)
            if revisao is not None and int(revisao) != m['revisao']:
                raise Conflito(m)
            for chave, valor in (mudancas or {}).items():
                self._aplicar(m, chave, valor)
            m['revisao'] += 1
            return self._salvar(m)

    def _aplicar(self, m, chave, valor):
        if chave in ('titulo', 'instrumento', 'compositor'):
            m[chave] = str(valor or '').strip()[:200]
        elif chave == 'ultimo_compasso':
            if valor in (None, ''):
                m[chave] = None
            else:
                v = int(valor)
                if not 1 <= v <= 9999:
                    raise Invalido('Último compasso deve estar entre 1 e 9999.')
                m[chave] = v
        elif chave == 'motor':
            if valor not in MOTORES:
                raise Invalido(f'Motor inválido: {valor}')
            m[chave] = valor
        elif chave == 'clave':
            if valor not in ('fa', 'sol'):
                raise Invalido('Clave deve ser fa ou sol.')
            m[chave] = valor
        elif chave == 'opcoes':
            guias = (valor or {}).get('guias')
            if guias not in (None, 'fa', 'sol'):
                raise Invalido('Guias deve ser fa, sol ou vazio.')
            m['opcoes'] = {'pdf': bool((valor or {}).get('pdf', True)), 'guias': guias}
        elif chave == 'saida':
            pasta = (valor or {}).get('pasta') or None
            if pasta and not Path(pasta).is_absolute():
                raise Invalido('A pasta de saída precisa ser um caminho completo.')
            nome = (valor or {}).get('nome')
            m['saida'] = {'pasta': pasta, 'nome': nome_seguro(nome) if nome else None}
        elif chave == 'paginas':
            atuais = {p['arquivo']: p for p in m['paginas']}
            novos = [p.get('arquivo') if isinstance(p, dict) else p for p in valor]
            if sorted(novos) != sorted(atuais):
                raise Invalido('A nova ordem precisa conter exatamente as mesmas páginas.')
            m['paginas'] = [dict(atuais[a], giro=int(p.get('giro', atuais[a]['giro'])) % 360 if isinstance(p, dict)
                                 else atuais[a]['giro']) for a, p in zip(novos, valor)]
        elif chave == 'checklist':
            m['checklist'] = {k: bool((valor or {}).get(k)) for k in CHECKLIST}
        elif chave == 'revisada':
            m['revisada'] = bool(valor)
            if valor and not (m.get('final') or {}).get('publicados'):
                versao = next((c['versoes'][-1] for c in reversed(m['conversoes']) if c.get('versoes')), None)
                if versao and versao.get('publicados'):
                    m['final'] = {'origem': 'Rascunho revisado no MuseScore', 'quando': agora(),
                                  'publicados': versao['publicados']}
            m['estado'] = 'revisada' if valor else self._estado_da_ultima(m)
        else:
            raise Invalido(f'Campo desconhecido: {chave}')

    def adicionar_paginas(self, mid, arquivos_entrada):
        with self._trava:
            m = self.ler(mid)
            origens = [self._na_entrada(a) for a in arquivos_entrada]
            self._mover_para(m, origens, self._giros_entrada())
            m['revisao'] += 1
            return self._salvar(m)

    def devolver_pagina(self, mid, arquivo):
        """Tira a página da música e devolve a foto para a caixa de entrada."""
        with self._trava:
            m = self.ler(mid)
            pag = next((p for p in m['paginas'] if p['arquivo'] == arquivo), None)
            if pag is None:
                raise NaoEncontrado(f'Página "{arquivo}" não está nesta música.')
            origem = self.musicas / mid / 'paginas' / arquivo
            destino = _destino_livre(self.entrada, arquivo)
            shutil.move(origem, destino)
            if pag.get('giro'):
                self.girar_entrada(destino.name, pag['giro'])
            m['paginas'] = [p for p in m['paginas'] if p['arquivo'] != arquivo]
            m['revisao'] += 1
            return self._salvar(m)

    def excluir(self, mid):
        with self._trava:
            para_lixeira(self._pasta(mid))

    def caminho_pagina(self, mid, arquivo):
        caminho = self.musicas / Path(mid).name / 'paginas' / Path(arquivo).name
        if not caminho.is_file():
            raise NaoEncontrado(f'Página "{arquivo}" não encontrada.')
        return caminho

    def paginas(self, m):
        return [(self.musicas / m['id'] / 'paginas' / p['arquivo'], p.get('giro', 0)) for p in m['paginas']]

    # ------------------------------------------------------------ conversões
    def pasta_conversao(self, mid, cid):
        pasta = self.musicas / Path(mid).name / 'conversoes' / Path(cid).name
        if not pasta.is_dir():
            raise NaoEncontrado(f'Conversão "{cid}" não encontrada.')
        return pasta

    def nova_conversao(self, mid, motor, lote=None):
        with self._trava:
            m = self.ler(mid)
            cid = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{motor}"
            pasta = self.musicas / mid / 'conversoes' / cid
            n = 2
            while pasta.exists():
                pasta = pasta.with_name(f'{cid}-{n}')
                n += 1
            pasta.mkdir(parents=True)
            m['conversoes'].append({'id': pasta.name, 'motor': motor, 'lote': lote, 'quando': agora(),
                                    'estado': 'na_fila', 'versoes': []})
            m['revisao'] += 1
            self._salvar(m)
            return pasta.name, pasta

    def definir_estado(self, mid, estado, cid=None, **extra):
        with self._trava:
            m = self.ler(mid)
            if cid:
                conv = next((c for c in m['conversoes'] if c['id'] == cid), None)
                if conv is not None:
                    conv['estado'] = estado
                    conv.update(extra)
            m['estado'] = estado if estado in ('na_fila', 'convertendo') else self._estado_da_ultima(m)
            m['revisao'] += 1
            return self._salvar(m)

    def registrar_versao(self, mid, cid, resultado, correcoes=None):
        """Guarda o resultado de uma conversão (ou de um novo acabamento) e recalcula o estado da música."""
        with self._trava:
            m = self.ler(mid)
            conv = next((c for c in m['conversoes'] if c['id'] == cid), None)
            if conv is None:
                raise NaoEncontrado(f'Conversão "{cid}" não encontrada.')
            if resultado.get('ok'):
                conv['estado'] = 'ok'
                conv['erro'] = None
                conv['versoes'].append({'n': resultado['versao'], 'quando': agora(), 'correcoes': correcoes or {},
                                        'publicados': resultado.get('publicados', {}),
                                        'resumo': resultado.get('resumo', {})})
            else:
                conv['estado'] = 'erro' if conv.get('versoes') == [] else 'ok'
                conv['erro'] = resultado.get('erro')
            m['estado'] = self._estado_da_ultima(m)
            m['revisao'] += 1
            return self._salvar(m)

    def _estado_da_ultima(self, m):
        if m.get('revisada'):
            return 'revisada'
        conversoes = [c for c in m['conversoes'] if c.get('estado') != 'legado']
        if not conversoes:
            return 'nova'
        ultima = conversoes[-1]
        if ultima['estado'] in ('na_fila', 'convertendo', 'cancelada', 'interrompida'):
            return ultima['estado']
        if ultima['estado'] == 'erro' or not ultima['versoes']:
            return 'erro'
        return 'rascunho_alertas' if ultima['versoes'][-1]['resumo'].get('alertas') else 'rascunho'

    def registrar_revisao(self, mid, resultado):
        """Guarda o pacote de revisão com o Claude mais recente (pasta e pedido para colar)."""
        with self._trava:
            m = self.ler(mid)
            m.setdefault('revisoes', []).append({'quando': agora(), 'ok': bool(resultado.get('ok')),
                                                 'pasta': resultado.get('pasta'), 'pedido': resultado.get('pedido'),
                                                 'erro': resultado.get('erro'), 'aviso': resultado.get('aviso')})
            m['revisao'] += 1
            return self._salvar(m)

    def conferencia(self, mid, cid, versao):
        arq = self.pasta_conversao(mid, cid) / 'versoes' / f'{int(versao):02d}' / 'conferencia.json'
        dados = _ler_json(arq, None)
        if dados is None:
            raise NaoEncontrado('Relatório não encontrado.')
        return dados
