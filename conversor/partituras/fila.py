"""Fila de conversões: uma por vez, cada uma num processo separado (partituras.trabalho), com progresso,
cancelamento (encerra o grupo de processos inteiro) e retomada depois de reiniciar o servidor."""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from . import caminhos, motores, processos
from .audio import disponivel as audio_disponivel
from .biblioteca import _gravar_json, _ler_json, agora


def comando_padrao(tarefa):
    return [sys.executable, '-m', 'partituras.trabalho', str(tarefa)]


def comando_audio_padrao(tarefa):
    """Trabalhos de áudio rodam no ambiente próprio (Python 3.12 com torch, librosa e music21)."""
    return [str(caminhos.PY_AUDIO), '-m', 'partituras.audio.trabalho', str(tarefa)]


class Fila:
    def __init__(self, biblioteca, comando=comando_padrao, ao_terminar=None, verificar_motores=True,
                 comando_audio=comando_audio_padrao):
        self.b = biblioteca
        self.comando = comando
        self.comando_audio = comando_audio
        self.ao_terminar = ao_terminar          # chamado quando a fila esvazia: ao_terminar(resumo)
        self.verificar_motores = verificar_motores
        self._itens = deque()
        self._atual = None
        self._trava = threading.RLock()
        self._sinal = threading.Event()
        self._arquivo = self.b.estado / 'fila.json'
        self._concluidas = []
        self._thread = threading.Thread(target=self._trabalhar, name='fila', daemon=True)
        self._thread.start()

    # ------------------------------------------------------------ consulta
    def ocupada(self):
        with self._trava:
            return self._atual is not None or bool(self._itens)

    def estado(self):
        with self._trava:
            atual = None
            if self._atual:
                a = self._atual
                atual = {k: a.get(k) for k in ('id', 'musica', 'titulo', 'motor', 'tipo', 'cid')}
                atual['ambiente'] = a.get('ambiente', 'omr')
                atual['progresso'] = a.get('progresso', {})
                atual['segundos'] = round(time.monotonic() - a['inicio'])
            return {'atual': atual,
                    'fila': [{**{k: j.get(k) for k in ('id', 'musica', 'titulo', 'motor', 'tipo', 'cid')},
                              'ambiente': j.get('ambiente', 'omr')} for j in self._itens]}

    # ------------------------------------------------------------ entrada
    def _persistir(self):
        _gravar_json(self._arquivo, {'itens': list(self._itens)})

    def _pasta_saida(self, m):
        pasta, nome = self.b.saida(m)
        try:
            pasta.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(f'Não consigo usar a pasta de saída {pasta}: {e}')
        if not os.access(pasta, os.W_OK):
            raise ValueError(f'Sem permissão para gravar em {pasta}.')
        return pasta, nome

    def _por_na_fila(self, job, mid, estado, cid=None):
        with self._trava:
            self._itens.append(job)
            self._persistir()
        self.b.definir_estado(mid, estado, cid)
        self._sinal.set()
        return [job['id']]

    def enfileirar(self, mid, tipo='converter', cid=None, correcoes=None, substituir=False):
        """Congela os dados da música agora e põe na fila. Devolve os ids dos trabalhos criados."""
        m = self.b.ler(mid)
        if m.get('fonte') == 'audio':
            return self._enfileirar_audio(m, tipo, cid, correcoes, substituir)
        if tipo == 'converter' and not m['paginas']:
            raise ValueError('A música não tem páginas.')
        pasta, nome = self._pasta_saida(m)
        if tipo == 'converter':
            lista_motores = ['homr', 'audiveris'] if m['motor'] == 'ambos' else [m['motor']]
        else:
            conv = next((c for c in m['conversoes'] if c['id'] == cid), None)
            if conv is None:
                raise ValueError('Conversão não encontrada.')
            lista_motores = [conv['motor']]
        if self.verificar_motores and tipo == 'converter':
            disp = motores.disponibilidade()
            faltam = [mo for mo in lista_motores if not disp.get(mo)]
            if faltam:
                raise ValueError(f'Motor não instalado: {", ".join(faltam)}. Rode conversor/instalar.sh.')
        lote = uuid.uuid4().hex[:8] if len(lista_motores) > 1 else None
        criados = []
        for motor in lista_motores:
            if tipo == 'converter':
                cid_atual, conv_dir = self.b.nova_conversao(mid, motor, lote)
            else:
                cid_atual, conv_dir = cid, self.b.pasta_conversao(mid, cid)
            saida_nome = nome if len(lista_motores) == 1 else f'{nome} ({motor})'
            opcoes = {'motor': motor, 'titulo': m['titulo'], 'instrumento': m['instrumento'] or None,
                      'compositor': m['compositor'] or None, 'pdf': m['opcoes'].get('pdf', True),
                      'guias': m['opcoes'].get('guias'), 'ultimo_compasso': m.get('ultimo_compasso')}
            tarefa = {'tipo': tipo, 'conv': str(conv_dir), 'opcoes': opcoes, 'correcoes': correcoes or {},
                      'paginas': [{'caminho': str(p), 'giro': g} for p, g in self.b.paginas(m)],
                      'saida': {'pasta': str(pasta), 'nome': saida_nome}, 'substituir': bool(substituir)}
            arq = conv_dir / f'tarefa-{tipo}-{uuid.uuid4().hex[:6]}.json'
            arq.write_text(json.dumps(tarefa, ensure_ascii=False, indent=2), encoding='utf-8')
            job = {'id': uuid.uuid4().hex[:10], 'musica': mid, 'titulo': m['titulo'], 'motor': motor, 'tipo': tipo,
                   'cid': cid_atual, 'arquivo': str(arq), 'correcoes': correcoes or {}, 'criado': agora()}
            with self._trava:
                self._itens.append(job)
                self._persistir()
            self.b.definir_estado(mid, 'na_fila', cid_atual)
            criados.append(job['id'])
        self._sinal.set()
        return criados

    def _enfileirar_audio(self, m, tipo, cid, ajustes, substituir):
        """Áudio: 'converter' separa (se o cache da música ainda não tem os stems) e transcreve; 'acabar' só
        transcreve de novo com os ajustes da revisão (sem separar)."""
        from .audio import instrumentos
        mid = m['id']
        a = m.get('audio') or {}
        if a.get('estado') != 'pronto' or not a.get('arquivo'):
            raise ValueError('O áudio desta música ainda não está pronto (baixando ou com erro).')
        if self.verificar_motores:
            disp = audio_disponivel.estado()
            if not disp['pronto']:
                raise ValueError('O modo de áudio não está instalado: falta ' + '; '.join(disp['falta']) + '.')
        ajustes = instrumentos.validar_ajustes(ajustes) if tipo == 'acabar' else {}
        pasta, nome = self._pasta_saida(m)
        iid = m.get('instrumento_alvo') or instrumentos.PADRAO
        if tipo == 'converter':
            cid, conv_dir = self.b.nova_conversao(mid, 'audio', None, instrumento=iid)
        else:
            conv = next((c for c in m['conversoes'] if c['id'] == cid), None)
            if conv is None:
                raise ValueError('Conversão não encontrada.')
            iid, conv_dir = conv.get('instrumento') or iid, self.b.pasta_conversao(mid, cid)
        pasta_audio = self.b.musicas / mid / 'audio'
        tarefa = {'tipo': tipo, 'ambiente': 'audio', 'conv': str(conv_dir), 'pasta_audio': str(pasta_audio),
                  'audio': {'original': str(pasta_audio / a['arquivo']), 'hash': a.get('hash'),
                            'duracao': a.get('duracao')},
                  'musica': {'id': mid, 'titulo': m['titulo'], 'compositor': m.get('compositor') or None,
                             'instrumento': m.get('instrumento')},
                  'instrumento': iid, 'ajustes': ajustes, 'opcoes': {'pdf': m['opcoes'].get('pdf', True)},
                  'saida': {'pasta': str(pasta), 'nome': nome}, 'substituir': bool(substituir)}
        arq = conv_dir / f'tarefa-{tipo}-{uuid.uuid4().hex[:6]}.json'
        arq.write_text(json.dumps(tarefa, ensure_ascii=False, indent=2), encoding='utf-8')
        job = {'id': uuid.uuid4().hex[:10], 'musica': mid, 'titulo': m['titulo'], 'motor': 'audio', 'tipo': tipo,
               'ambiente': 'audio', 'cid': cid, 'arquivo': str(arq), 'correcoes': ajustes, 'criado': agora()}
        return self._por_na_fila(job, mid, 'na_fila', cid)

    def enfileirar_baixar(self, mid, converter_depois=True):
        """Baixa o áudio de um link (yt-dlp) para a música; se pedido, emenda a conversão ao terminar."""
        m = self.b.ler(mid)
        a = m.get('audio') or {}
        if a.get('origem') != 'link' or not a.get('url'):
            raise ValueError('Esta música não veio de um link.')
        if self.verificar_motores and not audio_disponivel.estado()['link']:
            raise ValueError('A importação por link precisa do modo de áudio instalado (yt-dlp e Node.js). '
                             'Rode conversor/instalar.sh --audio.')
        pasta_audio = self.b.musicas / mid / 'audio'
        pasta_audio.mkdir(parents=True, exist_ok=True)
        tarefa = {'tipo': 'baixar', 'ambiente': 'audio', 'url': a['url'], 'pasta_audio': str(pasta_audio),
                  'yt_dlp': audio_disponivel.yt_dlp(), 'node': audio_disponivel.node()}
        arq = pasta_audio / f'.tarefa-baixar-{uuid.uuid4().hex[:6]}.json'
        arq.write_text(json.dumps(tarefa, ensure_ascii=False, indent=2), encoding='utf-8')
        job = {'id': uuid.uuid4().hex[:10], 'musica': mid, 'titulo': m['titulo'], 'motor': 'link', 'tipo': 'baixar',
               'ambiente': 'audio', 'cid': None, 'arquivo': str(arq), 'correcoes': {}, 'criado': agora(),
               'converter_depois': bool(converter_depois)}
        return self._por_na_fila(job, mid, 'baixando')

    def cancelar_da_musica(self, mid):
        """Cancela tudo o que a música tem na fila (antes de apagá-la)."""
        with self._trava:
            ids = [j['id'] for j in self._itens if j['musica'] == mid]
            if self._atual and self._atual['musica'] == mid:
                ids.append(self._atual['id'])
        for job_id in ids:
            self.cancelar(job_id)
        return len(ids)

    def enfileirar_revisao(self, mid):
        """Pacote de revisão com o Claude (fotos JPEG, guias, rascunho, PEDIDO.md) como trabalho da fila."""
        from . import revisao
        m = self.b.ler(mid)
        if m.get('fonte') == 'audio':
            raise ValueError('O pacote de revisão com o Claude ainda é só para músicas de fotos.')
        if not m['paginas']:
            raise ValueError('A música não tem páginas.')
        if self.verificar_motores and not motores.disponibilidade().get('audiveris'):
            raise ValueError('As guias de altura precisam do Audiveris. Rode conversor/instalar.sh.')
        tarefa = revisao.tarefa_de_revisao(self.b, m)
        pasta = Path(tarefa['pasta'])
        pasta.mkdir(parents=True, exist_ok=True)
        arq = pasta / '.tarefa.json'
        arq.write_text(json.dumps(tarefa, ensure_ascii=False, indent=2), encoding='utf-8')
        job = {'id': uuid.uuid4().hex[:10], 'musica': mid, 'titulo': m['titulo'], 'motor': 'audiveris',
               'tipo': 'revisao', 'cid': None, 'arquivo': str(arq), 'correcoes': {}, 'criado': agora()}
        with self._trava:
            self._itens.append(job)
            self._persistir()
        self._sinal.set()
        return [job['id']]

    def cancelar(self, job_id):
        proc = None
        with self._trava:
            for job in list(self._itens):
                if job['id'] == job_id:
                    self._itens.remove(job)
                    self._persistir()
                    self._marcar_fim(job, 'cancelada')
                    return True
            if not (self._atual and self._atual['id'] == job_id):
                return False
            self._atual['cancelado'] = True
            proc = self._atual.get('proc')
        if proc:  # se o processo ainda não começou, _executar vê a marca e o encerra
            processos.encerrar_grupo(proc)
        return True

    def _marcar_fim(self, job, estado):
        """Cancelar/interromper um novo acabamento não estraga as versões que a conversão já tem."""
        if job.get('tipo') == 'revisao':
            return
        if job.get('tipo') == 'baixar':
            try:
                self.b.registrar_audio(job['musica'], {'ok': False, 'estado_audio': 'erro' if estado == 'cancelada'
                                                       else 'interrompido', 'erro': 'Download cancelado.'
                                                       if estado == 'cancelada' else 'Download interrompido.'})
            except Exception:  # noqa: BLE001 — música apagada
                pass
            return
        try:
            m = self.b.ler(job['musica'])
        except Exception:  # noqa: BLE001 — música apagada
            return
        conv = next((c for c in m['conversoes'] if c['id'] == job['cid']), None)
        self.b.definir_estado(job['musica'], 'ok' if conv and conv.get('versoes') else estado, job['cid'])

    def recuperar(self):
        """Ao iniciar: o que estava convertendo foi interrompido; o que estava na fila volta para a fila."""
        pendentes = _ler_json(self._arquivo, {}).get('itens', [])
        ids_pendentes = {j['cid'] for j in pendentes}
        baixando = {j['musica'] for j in pendentes if j.get('tipo') == 'baixar'}
        for m in self.b.listar():
            if (m.get('audio') or {}).get('estado') == 'baixando' and m['id'] not in baixando:
                self.b.registrar_audio(m['id'], {'ok': False, 'estado_audio': 'interrompido',
                                                 'erro': 'O download foi interrompido (o programa foi fechado).'})
            for c in m['conversoes']:
                if c.get('estado') == 'convertendo' or (c.get('estado') == 'na_fila' and c['id'] not in ids_pendentes):
                    self.b.definir_estado(m['id'], 'ok' if c.get('versoes') else 'interrompida', c['id'])
        with self._trava:
            for job in pendentes:
                if Path(job['arquivo']).exists():
                    self._itens.append(job)
            self._persistir()
        if self._itens:
            self._sinal.set()

    def encerrar(self):
        """Ao desligar o servidor: interrompe o trabalho atual (motores incluídos)."""
        with self._trava:
            proc = self._atual.get('proc') if self._atual else None
        if proc:
            processos.encerrar_grupo(proc)

    # ------------------------------------------------------------ execução
    def _trabalhar(self):
        while True:
            self._sinal.wait()
            with self._trava:
                if not self._itens:
                    self._sinal.clear()
                    resumo, self._concluidas = self._concluidas, []
                    if resumo and self.ao_terminar:
                        try:
                            self.ao_terminar(resumo)
                        except Exception:  # noqa: BLE001 — aviso na área de trabalho é opcional
                            pass
                    continue
                job = self._itens.popleft()
                self._persistir()
                self._atual = dict(job, inicio=time.monotonic(), progresso={'etapa': 'iniciando', 'msg': 'Iniciando'})
            self._executar(job)
            with self._trava:
                self._atual = None

    def _executar(self, job):
        mid, cid = job['musica'], job['cid']
        try:
            if job.get('tipo') == 'revisao':
                self.b.ler(mid)
            elif job.get('tipo') == 'baixar':
                self.b.definir_estado(mid, 'baixando')
            else:
                self.b.definir_estado(mid, 'convertendo', cid)
        except Exception:  # noqa: BLE001 — música apagada enquanto estava na fila
            return
        resultado = {'ok': False, 'erro': 'O processo de conversão terminou sem resposta.'}
        log = Path(job['arquivo']).with_suffix('.log')
        try:
            with open(log, 'w', encoding='utf-8') as erros:
                comando = self.comando_audio if job.get('ambiente') == 'audio' else self.comando
                proc = subprocess.Popen(comando(job['arquivo']), cwd=caminhos.CONVERSOR, stdout=subprocess.PIPE,
                                        stderr=erros, text=True, start_new_session=True)
                with self._trava:
                    self._atual['proc'] = proc
                    ja_cancelado = self._atual.get('cancelado')
                if ja_cancelado:
                    processos.encerrar_grupo(proc)
                with proc.stdout:
                    for linha in proc.stdout:
                        try:
                            evento = json.loads(linha)
                        except json.JSONDecodeError:
                            continue
                        if evento.get('fim'):
                            resultado = evento
                        else:
                            with self._trava:
                                self._atual['progresso'] = evento
                proc.wait()
        except OSError as e:
            resultado = {'ok': False, 'erro': f'Não consegui iniciar a conversão: {e}'}
        cancelado = bool(self._atual and self._atual.get('cancelado'))
        if job.get('tipo') == 'baixar':
            if cancelado:
                self._marcar_fim(job, 'cancelada')
            else:
                try:
                    self.b.registrar_audio(mid, resultado)
                    if resultado.get('ok') and job.get('converter_depois'):
                        self.enfileirar(mid, 'converter')
                except Exception:  # noqa: BLE001 — música apagada ou modo de áudio incompleto
                    pass
        elif job.get('tipo') == 'revisao':
            if not cancelado:
                self.b.registrar_revisao(mid, resultado)
        elif cancelado:
            self._marcar_fim(job, 'cancelada')
        else:
            self.b.registrar_versao(mid, cid, resultado, job.get('correcoes'))
        self._concluidas.append({'titulo': job['titulo'], 'ok': resultado.get('ok') and not cancelado,
                                 'cancelado': cancelado})
