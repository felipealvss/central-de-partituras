"""Importação por link com o yt-dlp: um vídeo só (sem playlists), melhor áudio disponível, sem recomprimir.

Aviso que a interface repete: os Termos do YouTube não permitem baixar fora dos recursos do próprio site; usar o
link fica por conta do usuário. O yt-dlp precisa de um interpretador de JavaScript (Node.js) para o YouTube e
quebra com frequência quando o site muda: os erros aparecem como ele os escreve, com a dica de atualizá-lo.
O yt-dlp fica no grupo de processos do trabalho (como os motores em processos.rodar): cancelar na fila encerra
o grupo inteiro, yt-dlp junto. O tempo limite vale mesmo se ele parar de escrever.
"""
import json
import os
import re
import subprocess
import threading
from pathlib import Path

from . import fonte
from .. import processos
from ..erros import ErroConversao

DURACAO_MAXIMA = 30 * 60
PROGRESSO = re.compile(r'\[download\]\s+([\d.]+)%')


def comando(yt_dlp, node, url, pasta):
    cmd = [yt_dlp, '--no-playlist', '--playlist-items', '1', '--match-filter', f'duration <= {DURACAO_MAXIMA}',
           '--max-filesize', '400M', '-f', 'bestaudio/best', '--newline', '--no-mtime', '--write-info-json',
           '--no-write-playlist-metafiles', '-o', str(Path(pasta) / '.baixando.%(ext)s')]
    if node:
        cmd += ['--js-runtimes', f'node:{node}']
    return cmd + ['--', url]  # "--": o link nunca vira opção do yt-dlp


def executar(tarefa, progresso, timeout=1800):
    pasta = Path(tarefa['pasta_audio'])
    yt_dlp = tarefa.get('yt_dlp')
    if not yt_dlp or not Path(yt_dlp).exists():
        raise ErroConversao('O yt-dlp não está instalado (rode conversor/instalar.sh --audio).')
    for velho in pasta.glob('.baixando*'):
        velho.unlink(missing_ok=True)
    progresso('baixando', 'Baixando o áudio do link', None, None)
    log = []
    proc = subprocess.Popen(comando(yt_dlp, tarefa.get('node'), tarefa['url'], pasta), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
    estourou = threading.Event()

    def estourar():
        estourou.set()
        processos.parar(proc)

    relogio = threading.Timer(timeout, estourar)
    relogio.daemon = True
    relogio.start()
    try:
        for linha in proc.stdout:
            log.append(linha.rstrip())
            m = PROGRESSO.search(linha)
            if m:
                progresso('baixando', f'Baixando o áudio: {float(m.group(1)):.0f}%', int(float(m.group(1))), 100)
        proc.wait()
    finally:
        relogio.cancel()
        processos.parar(proc)
        (pasta / 'download.log').write_text('\n'.join(log) + '\n', encoding='utf-8')
    if estourou.is_set():
        raise ErroConversao(f'O download passou do tempo limite ({max(timeout // 60, 1)} min) e foi interrompido.')
    baixados = [p for p in pasta.glob('.baixando.*') if not p.name.endswith(('.info.json', '.part', '.ytdl'))]
    if proc.returncode != 0 or not baixados:
        texto = '\n'.join(log)
        if 'does not pass filter' in texto:
            raise ErroConversao(f'O vídeo tem mais de {DURACAO_MAXIMA // 60} minutos: a Central aceita áudios até '
                                'esse tamanho.')
        if 'larger than max-filesize' in texto:
            raise ErroConversao('O áudio desse vídeo passa de 400 MB.')
        erros = [x for x in log if 'ERROR' in x] or log[-3:]
        raise ErroConversao('O yt-dlp não conseguiu baixar: ' + ' / '.join(erros)[-500:] +
                            ' (se o problema continuar, atualize o yt-dlp: conversor/instalar.sh --atualizar-yt-dlp)')
    arquivo = baixados[0]
    info_json = pasta / '.baixando.info.json'
    titulo = None
    if info_json.exists():
        try:
            titulo = json.loads(info_json.read_text(encoding='utf-8')).get('title')
        except ValueError:
            pass
        info_json.unlink(missing_ok=True)
    final = pasta / f'original{arquivo.suffix.lower()}'
    os.replace(arquivo, final)
    info = fonte.sondar(final)
    audio = {'arquivo': final.name, 'nome_original': f'{titulo or "link"}{final.suffix}', 'titulo_original': titulo,
             'hash': fonte.identificar(final), 'tamanho': final.stat().st_size, **info}
    if info['com_perdas']:
        audio['aviso'] = (f"Áudio com perdas ({info['codec']}"
                          f"{', ~' + str(info['kbps']) + ' kb/s' if info.get('kbps') else ''}): bom para isolar "
                          'uma linha em evidência; um arquivo sem perdas é sempre melhor.')
    return {'ok': True, 'audio': audio}
