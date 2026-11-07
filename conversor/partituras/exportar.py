"""Exporta uma ou várias músicas num único .zip: arquivos finais (.mscz/.pdf), relatório, MusicXML,
fotos em ordem (pagina-01...), dados da música e, se pedido, guias, transcrição e logs."""
import json
import os
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from .publicar import nome_livre, nome_seguro

PADRAO = {'fotos': True, 'relatorio': True, 'musicxml': True, 'transcricao': True, 'guias': False, 'logs': False}


def ultima_versao(m):
    """(conversão, versão) mais recente com resultado, ou (None, None)."""
    for conv in reversed(m.get('conversoes', [])):
        if conv.get('versoes'):
            return conv, conv['versoes'][-1]
    return None, None


def arquivos_finais(m):
    """O arquivo revisado, se a música tiver; senão os publicados da última versão."""
    final = (m.get('final') or {}).get('publicados') or {}
    if not final:
        _, versao = ultima_versao(m)
        final = (versao or {}).get('publicados') or {}
    return {ext: Path(p) for ext, p in final.items() if p and Path(p).exists()}


def _leia_me(m, conteudo):
    linhas = [f"{m['titulo']}" + (f" — {m['instrumento']}" if m.get('instrumento') else ''),
              f"Exportado pela Central de Partituras em {datetime.now():%d/%m/%Y %H:%M}.",
              f"Situação: {'revisada' if m.get('revisada') else 'rascunho (revise no MuseScore antes de usar)'}.", '',
              'Conteúdo:']
    linhas += [f'  - {c}' for c in conteudo]
    return '\n'.join(linhas) + '\n'


def exportar(b, ids, incluir=None):
    if not ids:
        raise ValueError('Escolha ao menos uma música para exportar.')
    opc = {**PADRAO, **{k: bool(v) for k, v in (incluir or {}).items() if k in PADRAO}}
    musicas = [b.ler(mid) for mid in ids]
    base = nome_seguro(musicas[0]['titulo'] if len(musicas) == 1 else f'{len(musicas)} músicas')
    base = f"{base} {datetime.now():%Y-%m-%d}"
    destino = b.exportados / f"{nome_livre(b.exportados, base, ['.zip'])}.zip"
    tmp = b.exportados / f'.{uuid.uuid4().hex}.parcial'
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            for m in musicas:
                raiz = '' if len(musicas) == 1 else nome_seguro(m['titulo']) + '/'
                conteudo = []
                for ext, p in arquivos_finais(m).items():
                    z.write(p, raiz + p.name)
                    conteudo.append(p.name)
                conv, versao = ultima_versao(m)
                if versao:
                    cdir = b.pasta_conversao(m['id'], conv['id'])
                    vdir = cdir / 'versoes' / f"{versao['n']:02d}"
                    if opc['relatorio'] and (vdir / 'conferencia.txt').exists():
                        z.write(vdir / 'conferencia.txt', raiz + 'conferencia.txt')
                        conteudo.append('conferencia.txt (relatório da última conversão)')
                    if opc['musicxml'] and (vdir / 'partitura.musicxml').exists():
                        z.write(vdir / 'partitura.musicxml', raiz + 'partitura.musicxml')
                        conteudo.append('partitura.musicxml (abre em qualquer editor de partitura)')
                    if opc['guias']:
                        for g in sorted((cdir / 'guias').glob('*.jpg')):
                            z.write(g, raiz + 'guias/' + g.name)
                    if opc['logs']:
                        for log in sorted((cdir / 'logs').glob('*.log')):
                            z.write(log, raiz + 'logs/' + log.name)
                if opc['fotos']:
                    for i, (p, _giro) in enumerate(b.paginas(m), 1):
                        z.write(p, raiz + f'fotos/pagina-{i:02d}{p.suffix.lower()}')
                    if m['paginas']:
                        conteudo.append(f"fotos/ ({len(m['paginas'])} página(s), na ordem da música)")
                if opc['transcricao']:
                    tdir = b.musicas / m['id'] / 'transcricao'
                    arquivos = [f for f in sorted(tdir.rglob('*')) if f.is_file() and '__pycache__' not in f.parts] if tdir.exists() else []
                    for f in arquivos:
                        z.write(f, raiz + 'transcricao/' + str(f.relative_to(tdir)))
                    if arquivos:
                        conteudo.append('transcricao/ (transcrição assistida em notação compacta)')
                z.writestr(raiz + 'musica.json', json.dumps(m, ensure_ascii=False, indent=2))
                z.writestr(raiz + 'LEIA-ME.txt', _leia_me(m, conteudo + ['musica.json (dados da música)']))
        os.link(tmp, destino)  # nunca sobrescreve
    finally:
        tmp.unlink(missing_ok=True)
    return destino
