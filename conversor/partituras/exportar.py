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


def conversoes_atuais(m):
    """As conversões do relatório atual: as do último lote (motor 'os dois') ou a última com resultado."""
    conv, _ = ultima_versao(m)
    if conv is None:
        return []
    if conv.get('lote'):
        return [c for c in m['conversoes'] if c.get('lote') == conv['lote'] and c.get('versoes')]
    return [conv]


def arquivos_finais(m):
    """O arquivo revisado, se a música tiver; senão os publicados das conversões atuais (os dois motores, se for o caso)."""
    final = (m.get('final') or {}).get('publicados') or {}
    if final:
        return [Path(p) for p in final.values() if p and Path(p).exists()]
    return [Path(p) for c in conversoes_atuais(m) for p in c['versoes'][-1].get('publicados', {}).values()
            if p and Path(p).exists()]


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
                for p in arquivos_finais(m):
                    z.write(p, raiz + p.name)
                    conteudo.append(p.name)
                convs = conversoes_atuais(m)
                guias_postas = False
                for conv in convs:
                    versao = conv['versoes'][-1]
                    sufixo = f"-{conv['motor']}" if len(convs) > 1 else ''
                    cdir = b.pasta_conversao(m['id'], conv['id'])
                    vdir = cdir / 'versoes' / f"{versao['n']:02d}"
                    if opc['relatorio'] and (vdir / 'conferencia.txt').exists():
                        z.write(vdir / 'conferencia.txt', raiz + f'conferencia{sufixo}.txt')
                        conteudo.append(f'conferencia{sufixo}.txt (relatório da conversão)')
                    if opc['musicxml'] and (vdir / 'partitura.musicxml').exists():
                        z.write(vdir / 'partitura.musicxml', raiz + f'partitura{sufixo}.musicxml')
                        conteudo.append(f'partitura{sufixo}.musicxml (abre em qualquer editor de partitura)')
                    if opc['guias'] and not guias_postas:
                        for g in sorted((cdir / 'guias').glob('*.jpg')):
                            z.write(g, raiz + 'guias/' + g.name)
                            guias_postas = True
                    if opc['logs']:
                        for log in sorted((cdir / 'logs').glob('*.log')):
                            z.write(log, raiz + f'logs{sufixo}/' + log.name)
                if opc['guias'] and not guias_postas:  # guias do pacote de revisão mais recente
                    pacote = next((Path(r['pasta']) for r in reversed(m.get('revisoes', [])) if r.get('ok') and r.get('pasta')), None)
                    for g in sorted((pacote / 'guias').glob('*.jpg')) if pacote and pacote.is_dir() else []:
                        z.write(g, raiz + 'guias/' + g.name)
                        guias_postas = True
                if guias_postas:
                    conteudo.append('guias/ (imagens com o nome das notas nas linhas suplementares)')
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
