"""Orquestra a conversão em três fases:

  reconhecer()  roda o motor (lento) e guarda o resultado bruto em <conv>/bruto.musicxml;
  acabar()      limpa, converte ligaduras, aplica as correções de pausa, confere e gera MusicXML/.mscz/.pdf
                numa nova versão <conv>/versoes/NN/ (segundos). Corrigir pausas repete só esta fase;
  publicar()    copia a versão para a pasta de saída sem nunca sobrescrever.
"""
import json
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from . import conferencia, guias, imagens, motores, musescore
from . import musicxml as mx
from .erros import ErroConversao
from .publicar import publicar


@dataclass
class Opcoes:
    motor: str = 'homr'                 # 'homr' | 'audiveris'
    titulo: str | None = None
    instrumento: str | None = None
    compositor: str | None = None
    pdf: bool = True
    guias: str | None = None            # 'fa' | 'sol' | None
    ultimo_compasso: int | None = None

    @classmethod
    def de_dict(cls, d):
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class Pagina:
    caminho: Path
    giro: int = 0


def _nada(*_a, **_k):
    pass


def _agora():
    return datetime.now().isoformat(timespec='seconds')


def reconhecer(paginas, conv, opcoes, progresso=_nada, manter_trabalho=False):
    """Roda o motor e grava <conv>/bruto.musicxml (páginas já unidas), logs e, se pedido, as guias."""
    conv = Path(conv)
    conv.mkdir(parents=True, exist_ok=True)
    trabalho = conv / 'trabalho'
    shutil.rmtree(trabalho, ignore_errors=True)
    trabalho.mkdir()
    inicio = time.monotonic()
    progresso('preparando', 'Lendo as páginas', None, None)
    pags = imagens.carregar(paginas, trabalho)
    info = {'motor': opcoes.motor, 'paginas': [n for n, _ in pags], 'quando': _agora()}
    preparadas = omr = None
    if opcoes.motor == 'homr':
        arvores = motores.rodar_homr(pags, trabalho, progresso)
    elif opcoes.motor == 'audiveris':
        progresso('preparando', 'Preparando as imagens para o Audiveris', None, None)
        pdf, preparadas, info['preparo'] = imagens.preparar_audiveris(pags, trabalho, lambda m: progresso('preparando', m, None, None))
        arvores, omr = motores.rodar_audiveris(pdf, trabalho, progresso)
    else:
        raise ErroConversao(f'Motor desconhecido: {opcoes.motor}')
    mx.gravar(mx.unir_paginas(arvores), conv / 'bruto.musicxml')
    if opcoes.guias:
        progresso('guias', 'Gerando as guias de altura', None, None)
        if omr is None:  # as guias dependem das linhas de pauta que só o Audiveris localiza
            pdf, preparadas, _ = imagens.preparar_audiveris(pags, trabalho, lambda m: None)
            _, omr = motores.rodar_audiveris(pdf, trabalho, progresso)
        info['guias'] = [str(p.relative_to(conv)) for p in guias.gerar(omr, preparadas, opcoes.guias, conv / 'guias')]
    if omr:
        shutil.copyfile(omr, conv / 'audiveris.omr')
    logs = conv / 'logs'
    logs.mkdir(exist_ok=True)
    for log in trabalho.rglob('*.log'):
        shutil.copyfile(log, logs / log.name)
    info['segundos'] = round(time.monotonic() - inicio, 1)
    (conv / 'reconhecimento.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    if not manter_trabalho:
        shutil.rmtree(trabalho, ignore_errors=True)
    return info


def acabar(conv, opcoes, correcoes=None, progresso=_nada):
    """Gera uma nova versão a partir do bruto: <conv>/versoes/NN/{partitura.musicxml,.mscz,.pdf,conferencia.*}."""
    conv = Path(conv)
    bruto = conv / 'bruto.musicxml'
    if not bruto.exists():
        raise ErroConversao('Esta conversão não tem o reconhecimento bruto; converta de novo.')
    progresso('acabamento', 'Corrigindo ligaduras e pausas e conferindo os compassos', None, None)
    arvore = mx.ler(bruto)
    mx.normalizar_multirests(arvore)
    ligaduras = mx.ligaduras_de_valor(arvore)
    base = mx.trechos_de_pausa(arvore, com_elementos=True)  # como o motor leu: os índices das correções
    feitas = mx.corrigir_trechos(arvore, correcoes) if correcoes else []
    textos = mx.ajustar(arvore, opcoes.titulo, opcoes.instrumento, opcoes.compositor)
    rel = conferencia.analisar(arvore, opcoes.motor, opcoes.ultimo_compasso, ligaduras, textos,
                               trechos=mx.situar_trechos(base, correcoes))
    rel['correcoes'] = feitas
    versoes = conv / 'versoes'
    versoes.mkdir(exist_ok=True)
    n = 1 + max((int(p.name) for p in versoes.iterdir() if p.name.isdigit()), default=0)
    vdir = versoes / f'{n:02d}'
    vdir.mkdir()
    xml = vdir / 'partitura.musicxml'
    mx.gravar(arvore, xml)
    progresso('musescore', 'Gerando o arquivo do MuseScore', None, None)
    mscz = musescore.converter(xml, vdir / 'partitura.mscz', log=vdir / 'musescore.log')
    pdf = musescore.converter(mscz, vdir / 'partitura.pdf', log=vdir / 'musescore-pdf.log') if opcoes.pdf else None
    texto = conferencia.formatar(rel)
    (vdir / 'conferencia.txt').write_text(texto + '\n', encoding='utf-8')
    (vdir / 'conferencia.json').write_text(json.dumps(rel, ensure_ascii=False, indent=1), encoding='utf-8')
    (vdir / 'versao.json').write_text(json.dumps({'versao': n, 'quando': _agora(), 'opcoes': asdict(opcoes),
                                                  'correcoes': correcoes or {}}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'versao': n, 'pasta': vdir, 'conferencia': rel, 'texto': texto,
            'arquivos': {'.mscz': mscz, '.pdf': pdf, '.musicxml': xml, '-conferencia.txt': vdir / 'conferencia.txt'}}


def publicar_versao(resultado, pasta, nome, substituir=False, extensoes=('.mscz', '.pdf')):
    arquivos = {ext: p for ext, p in resultado['arquivos'].items() if p and ext in extensoes}
    return publicar(arquivos, pasta, nome, substituir)


def converter(paginas, conv, opcoes, pasta_saida, nome_saida, correcoes=None, substituir=False,
              progresso=_nada, extensoes=('.mscz', '.pdf'), manter_trabalho=False):
    reconhecer(paginas, conv, opcoes, progresso, manter_trabalho)
    res = acabar(conv, opcoes, correcoes, progresso)
    res['publicados'] = publicar_versao(res, pasta_saida, nome_saida, substituir, extensoes)
    return res
