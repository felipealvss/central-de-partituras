"""Servidor local da Central de Partituras (só em 127.0.0.1).

Uso (o lançador abrir-conversor.sh faz isso): .venv/bin/python -m partituras.servidor

Segurança: uma ficha secreta é gerada a cada início e passada na URL da janela; vira um cookie
(SameSite=Strict). Toda a API exige o cookie, o cabeçalho Host local e, para alterar dados, o cabeçalho
X-Central. O navegador nunca envia caminhos de arquivo: só identificadores de músicas, fotos e conversões.
"""
import fcntl
import os
import secrets
import signal
import socket
import sys
import threading
import time
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, request, send_file, send_from_directory

from . import caminhos, exportar, motores, sistema
from .biblioteca import Biblioteca, Conflito, Invalido, NaoEncontrado, _gravar_json
from .erros import ErroConversao
from .fila import Fila

ESTATICOS = Path(__file__).resolve().parent / 'static'
PORTAS = range(8765, 8786)
INATIVIDADE = 180  # segundos sem a janela aberta e com a fila vazia → o servidor encerra
ARQUIVOS_DA_VERSAO = {'partitura.pdf', 'partitura.musicxml', 'conferencia.txt'}


def _resumo_motores():
    return motores.disponibilidade()


def criar_app(b, fila, token):
    app = Flask(__name__, static_folder=None)
    app.config['MAX_CONTENT_LENGTH'] = 400 * 1024 * 1024
    app.config['ultimo_sinal'] = time.monotonic()
    cache = {'motores': (0.0, None)}

    def motores_cache():
        t, valor = cache['motores']
        if valor is None or time.monotonic() - t > 60:
            cache['motores'] = (time.monotonic(), _resumo_motores())
        return cache['motores'][1]

    # ------------------------------------------------------------ proteção
    @app.before_request
    def proteger():
        if request.host.rsplit(':', 1)[0] not in ('127.0.0.1', 'localhost'):
            abort(403)
        if request.path == '/api/ping' or (request.path == '/' and request.args.get('t') == token):
            return None
        if not secrets.compare_digest(request.cookies.get('central', ''), token):
            abort(403)
        if request.method not in ('GET', 'HEAD') and request.headers.get('X-Central') != '1':
            abort(403)
        return None

    def erro(status, msg, **extra):
        return jsonify({'erro': msg, **extra}), status

    @app.errorhandler(403)
    def proibido(_e):
        if request.path.startswith('/api/'):
            return erro(403, 'Acesso negado. Abra a Central pelo atalho.')
        return ('<meta charset="utf-8"><body style="font-family:system-ui;padding:2rem">'
                '<h2>Central de Partituras</h2><p>Abra pelo atalho <b>Central de Partituras</b> '
                'ou rode <code>abrir-conversor.sh</code> na pasta image-to-music.</p></body>', 403)

    app.register_error_handler(NaoEncontrado, lambda e: erro(404, str(e)))
    app.register_error_handler(Invalido, lambda e: erro(400, str(e)))
    app.register_error_handler(ValueError, lambda e: erro(400, str(e)))
    app.register_error_handler(ErroConversao, lambda e: erro(400, str(e)))
    app.register_error_handler(Conflito, lambda e: erro(409, str(e), musica=e.atual))
    app.register_error_handler(sistema.Ocupado, lambda e: erro(409, str(e)))

    def corpo():
        return request.get_json(silent=True) or {}

    # ------------------------------------------------------------ páginas
    @app.get('/')
    def inicio():
        if request.args.get('t') == token:
            r = redirect('/')
            r.set_cookie('central', token, httponly=True, samesite='Strict', path='/')
            return r
        return send_from_directory(ESTATICOS, 'index.html')

    @app.get('/static/<path:nome>')
    def estaticos(nome):
        return send_from_directory(ESTATICOS, nome)

    @app.get('/api/ping')
    def ping():
        return {'ok': True, 'app': 'central-partituras'}

    @app.get('/api/estado')
    def estado():
        app.config['ultimo_sinal'] = time.monotonic()  # a janela está aberta
        return {'fila': fila.estado(), 'motores': motores_cache(),
                'revisoes': {m['id']: m['revisao'] for m in b.listar()},
                'entrada': len(b._arquivos(b.entrada))}

    @app.get('/api/manual')
    def manual():
        arq = caminhos.RAIZ / 'MANUAL.md'
        return {'texto': arq.read_text(encoding='utf-8') if arq.exists() else '# Manual\n\nAinda não disponível.'}

    # ------------------------------------------------------------ músicas
    @app.get('/api/musicas')
    def listar():
        return {'musicas': b.listar(), 'saida_padrao': str(b.partituras), 'casa': str(Path.home())}

    @app.post('/api/musicas')
    def criar():
        d = corpo()
        campos = {k: d[k] for k in ('instrumento', 'compositor', 'ultimo_compasso', 'motor', 'clave') if k in d}
        return b.criar(d.get('titulo'), d.get('fotos', []), **campos), 201

    @app.get('/api/musicas/<mid>')
    def ler(mid):
        return b.ler(mid) or abort(404)

    @app.patch('/api/musicas/<mid>')
    def atualizar(mid):
        d = corpo()
        return b.atualizar(mid, d.get('revisao'), d.get('mudancas', {}))

    @app.delete('/api/musicas/<mid>')
    def excluir(mid):
        b.excluir(mid)
        return {'ok': True}

    @app.post('/api/musicas/<mid>/paginas')
    def adicionar_paginas(mid):
        return b.adicionar_paginas(mid, corpo().get('fotos', []))

    @app.delete('/api/musicas/<mid>/paginas/<arquivo>')
    def devolver_pagina(mid, arquivo):
        return b.devolver_pagina(mid, arquivo)

    def _lado():
        try:
            return max(80, min(int(request.args.get('lado', 400)), 2400))
        except ValueError:
            return 400

    @app.get('/api/imagem/musica/<mid>/<arquivo>')
    def imagem_musica(mid, arquivo):
        m = b.ler(mid)
        pag = next((p for p in m['paginas'] if p['arquivo'] == arquivo), None)
        if pag is None:
            abort(404)
        from . import fotos
        mini = fotos.miniatura(b.caminho_pagina(mid, arquivo), pag.get('giro', 0), _lado(), b.miniaturas)
        return send_file(mini, mimetype='image/jpeg', max_age=3600) if mini else abort(404)

    # ------------------------------------------------------------ caixa de entrada
    @app.get('/api/entrada')
    def entrada():
        limiar = int(request.args.get('limiar', 90))
        fotos_ = b.fotos_entrada()
        grupos = [[f['arquivo'] for f in g] for g in b.grupos_sugeridos(limiar)]
        return {'fotos': fotos_, 'grupos': grupos, 'limiar': limiar}

    @app.get('/api/imagem/entrada/<arquivo>')
    def imagem_entrada(arquivo):
        from . import fotos
        caminho = b._na_entrada(arquivo)
        giro = b._giros_entrada().get(caminho.name, 0)
        mini = fotos.miniatura(caminho, giro, _lado(), b.miniaturas)
        return send_file(mini, mimetype='image/jpeg', max_age=3600) if mini else abort(404)

    @app.put('/api/entrada/<nome>')
    def enviar(nome):
        return b.importar(nome, request.stream), 201

    @app.patch('/api/entrada/<arquivo>')
    def girar_entrada(arquivo):
        b._na_entrada(arquivo)
        b.girar_entrada(arquivo, corpo().get('giro', 0))
        return {'ok': True}

    @app.delete('/api/entrada/<arquivo>')
    def descartar(arquivo):
        b.descartar_entrada(arquivo)
        return {'ok': True}

    @app.post('/api/entrada/criar')
    def criar_grupos():
        criadas = []
        for g in corpo().get('grupos', []):
            criadas.append(b.criar(g.get('titulo'), g.get('fotos', []),
                                   **{k: g[k] for k in ('instrumento', 'compositor') if g.get(k)}))
        return {'musicas': criadas}, 201

    # ------------------------------------------------------------ conversão e fila
    @app.post('/api/musicas/<mid>/converter')
    def converter(mid):
        return {'trabalhos': fila.enfileirar(mid, 'converter', substituir=bool(corpo().get('substituir')))}

    @app.post('/api/musicas/<mid>/conversoes/<cid>/acabar')
    def acabar(mid, cid):
        d = corpo()
        correcoes = {str(int(k)): int(v) for k, v in (d.get('correcoes') or {}).items() if str(v).strip()}
        return {'trabalhos': fila.enfileirar(mid, 'acabar', cid=cid, correcoes=correcoes,
                                             substituir=bool(d.get('substituir')))}

    @app.delete('/api/fila/<job>')
    def cancelar(job):
        return {'ok': fila.cancelar(job)}

    @app.get('/api/musicas/<mid>/conversoes/<cid>/versoes/<int:n>/conferencia')
    def conferencia(mid, cid, n):
        return b.conferencia(mid, cid, n)

    @app.get('/api/musicas/<mid>/conversoes/<cid>/versoes/<int:n>/<nome>')
    def arquivo_versao(mid, cid, n, nome):
        if nome not in ARQUIVOS_DA_VERSAO:
            abort(404)
        arq = b.pasta_conversao(mid, cid) / 'versoes' / f'{n:02d}' / nome
        return send_file(arq) if arq.is_file() else abort(404)

    @app.get('/api/musicas/<mid>/conversoes/<cid>/guias/<nome>')
    def guia(mid, cid, nome):
        arq = b.pasta_conversao(mid, cid) / 'guias' / Path(nome).name
        return send_file(arq, mimetype='image/jpeg') if arq.is_file() else abort(404)

    # ------------------------------------------------------------ sistema
    def _publicados(m):
        conhecidos = set()
        for c in m['conversoes']:
            for v in c.get('versoes', []):
                conhecidos.update(v.get('publicados', {}).values())
        conhecidos.update((m.get('final') or {}).get('publicados', {}).values())
        return conhecidos

    @app.post('/api/sistema/abrir')
    def abrir():
        d = corpo()
        m = b.ler(d.get('musica'))
        alvo, arquivo = d.get('alvo'), d.get('arquivo')
        if arquivo:
            if arquivo not in _publicados(m) or not Path(arquivo).exists():
                raise NaoEncontrado('Arquivo não encontrado (foi movido ou apagado?).')
            if alvo == 'musescore':
                sistema.abrir_no_musescore(arquivo)
            elif alvo == 'pasta':
                sistema.mostrar_na_pasta(arquivo)
            else:
                sistema.abrir(arquivo)
        else:
            pasta, _ = b.saida(m)
            pasta.mkdir(parents=True, exist_ok=True)
            sistema.abrir(pasta)
        return {'ok': True}

    @app.post('/api/sistema/abrir-pasta')
    def abrir_pasta():
        qual = corpo().get('qual')
        pastas = {'entrada': b.entrada, 'partituras': b.partituras, 'exportados': b.exportados, 'raiz': b.raiz}
        if qual not in pastas:
            abort(404)
        sistema.abrir(pastas[qual])
        return {'ok': True}

    @app.post('/api/sistema/escolher-pasta')
    def escolher_pasta():
        return {'pasta': sistema.escolher_pasta(corpo().get('inicial') or str(b.partituras))}

    # ------------------------------------------------------------ extras
    @app.post('/api/exportar')
    def exportar_zip():
        d = corpo()
        destino = exportar.exportar(b, d.get('musicas', []), d.get('incluir', {}))
        if d.get('mostrar', True):
            sistema.mostrar_na_pasta(destino)
        return {'arquivo': str(destino), 'nome': destino.name}

    @app.post('/api/musicas/<mid>/revisao')
    def preparar_revisao(mid):
        return {'trabalhos': fila.enfileirar_revisao(mid)}

    @app.post('/api/musicas/<mid>/abrir-revisao')
    def abrir_revisao(mid):
        m = b.ler(mid)
        ultima = next((r for r in reversed(m.get('revisoes', [])) if r.get('ok') and r.get('pasta')), None)
        base = (b.musicas / m['id'] / 'revisao').resolve()
        if not ultima or not Path(ultima['pasta']).resolve().is_relative_to(base) or not Path(ultima['pasta']).is_dir():
            raise NaoEncontrado('Pacote de revisão não encontrado.')
        sistema.abrir(ultima['pasta'])
        return {'ok': True}

    @app.post('/api/encerrar')
    def encerrar():
        threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
        return {'ok': True}

    return app


def _porta_livre():
    for porta in PORTAS:
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', porta))
                return porta
            except OSError:
                continue
    raise SystemExit('Nenhuma porta livre entre 8765 e 8785.')


def _avisar(resumo):
    ok = sum(1 for r in resumo if r['ok'])
    falhas = [r['titulo'] for r in resumo if not r['ok'] and not r['cancelado']]
    texto = f'{ok} conversão(ões) concluída(s).'
    if falhas:
        texto += f' Com erro: {", ".join(falhas)}.'
    sistema.notificar('Fila de conversão terminada', texto)


def main():
    caminhos.ESTADO.mkdir(parents=True, exist_ok=True)
    trava = open(caminhos.ESTADO / 'servidor.lock', 'w')
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('A Central de Partituras já está aberta.')
        sys.exit(0)
    porta, token = _porta_livre(), secrets.token_urlsafe(24)
    b = Biblioteca(caminhos.RAIZ)
    fila = Fila(b, ao_terminar=_avisar)
    fila.recuperar()
    app = criar_app(b, fila, token)
    info = caminhos.ESTADO / 'servidor.json'
    _gravar_json(info, {'porta': porta, 'token': token, 'pid': os.getpid()})
    os.chmod(info, 0o600)

    def desligar(*_):
        fila.encerrar()
        info.unlink(missing_ok=True)
        os._exit(0)

    signal.signal(signal.SIGTERM, desligar)
    signal.signal(signal.SIGINT, desligar)

    def vigiar():
        while True:
            time.sleep(15)
            if time.monotonic() - app.config['ultimo_sinal'] > INATIVIDADE and not fila.ocupada():
                desligar()

    threading.Thread(target=vigiar, daemon=True).start()
    from waitress import create_server
    print(f'Central de Partituras em http://127.0.0.1:{porta}/', flush=True)
    create_server(app, host='127.0.0.1', port=porta, threads=8).run()


if __name__ == '__main__':
    main()
