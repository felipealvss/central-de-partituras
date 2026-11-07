"""Pacote de revisão assistida pelo Claude — o mesmo processo da versão revisada citada no manual.

Gera musicas/<id>/revisao/<data-hora>/ com: fotos em JPEG (o Claude não lê HEIC), guias de altura (o Audiveris
localiza as pautas), o rascunho mais recente (MusicXML e listado compasso a compasso), a conferência e um
PEDIDO.md com as instruções. Roda como trabalho da fila (leva ~1 min por causa do Audiveris). As guias são uma
ajuda: se o Audiveris não conseguir localizar as pautas, o pacote sai sem elas, com um aviso.
"""
import shutil
from datetime import datetime
from pathlib import Path

from . import guias, imagens, motores
from . import musicxml as mx
from .erros import Cancelado, ErroConversao


def listar_compassos(arvore):
    """Rascunho legível: uma linha por compasso, notas da mais grave para a mais aguda."""
    linhas, restante = [], 0
    for m in mx.partes(arvore)[0].findall('measure'):
        itens = []
        for el in m:
            if el.tag == 'attributes':
                k, t = el.findtext('key/fifths'), el.findtext('time/beats')
                mr = el.findtext('measure-style/multiple-rest')
                if k is not None:
                    itens.append(f'[armadura {k}]')
                if t:
                    itens.append(f"[compasso {t}/{el.findtext('time/beat-type')}]")
                if mr and mr.strip().isdigit():
                    itens.append(f'[pausa longa de {mr} compassos]')
                    restante = int(mr)
            if el.tag != 'note':
                continue
            tipo = (el.findtext('type') or 'compasso') + ('.' if el.find('dot') is not None else '')
            if el.find('rest') is not None:
                itens.append(f'pausa:{tipo}')
                continue
            lig = '~' if el.find("tie[@type='start']") is not None else ''
            itens.append(('+' if el.find('chord') is not None else ' ') + f'{mx.nome_nota(el)}:{tipo}{lig}')
        if not m.findall('note'):
            itens.append('pausa' if restante > 0 else '(vazio: provável nota perdida)')
        restante -= 1
        linhas.append(f"c.{m.get('number'):>3}: " + ' '.join(itens))
    return '\n'.join(linhas) + '\n'


PEDIDO = """# Pedido de revisão — {titulo}{instr}

Cole no Claude Code (aberto na pasta do programa, a que tem o `abrir-conversor.sh`):

> Revise a música em `{rel}` seguindo o PEDIDO.md dessa pasta.

## O que fazer
Comparar o rascunho com as fotos, compasso a compasso, e escrever a transcrição final em notação compacta.

{passo_guias}
2. Confira contra `rascunho-por-compasso.txt` (o que o {motor} leu, já com ligaduras e pausas corrigidas).
   As notas pretas costumam estar certas; confira semibreves graves, pausas longas, acidentes e ligaduras.
3. Escreva a transcrição em `{transcricao}` (arquivo novo, com data: não apague transcrições anteriores) usando `conversor/partituras/notacao.py`
   (o formato está descrito no início desse arquivo; transcrições anteriores em `musicas/*/transcricao/` servem de exemplo).
   Inclua dinâmicas, andamentos, rit./a tempo, forquilhas, articulações, fermatas e barras duplas.
4. Gere e confira (na pasta conversor/):
   `.venv/bin/python -m partituras.notacao ../{transcricao} -o ../{saida_xml} --mscz "{saida_mscz}" --pdf`
   A geração recusa compassos com duração errada e nunca sobrescreve um .mscz existente (salva como "Nome (2)").
5. Compare o PDF gerado com as fotos, sistema por sistema. Último compasso impresso: {ultimo}.

## Arquivos desta pasta
- `pagina-NN.jpg`: fotos da partitura original, na ordem.
{arquivo_guias}
- `rascunho.musicxml` e `rascunho-por-compasso.txt`: o rascunho mais recente.
- `conferencia.json`: total de compassos, trechos de pausa e problemas apontados.
"""


def _guias(pags, trabalho, pasta, clave, progresso):
    """Desenha as guias de altura em `pasta`/guias (o Audiveris localiza as pautas). Devolve None se deu certo,
    ou o motivo da falha: as guias são uma ajuda, e sem elas o pacote ainda serve."""
    progresso('guias', 'Localizando as pautas com o Audiveris para desenhar as guias', None, None)
    try:
        if not motores.disponibilidade()['audiveris']:
            raise ErroConversao('o Audiveris não está instalado (rode conversor/instalar.sh)')
        pdf, preparadas, _ = imagens.preparar_audiveris(pags, trabalho, lambda m: None)
        falha = None
        try:
            _, omr = motores.rodar_audiveris(pdf, trabalho, progresso)
        except Cancelado:
            raise
        except ErroConversao as e:  # sem partitura exportada, as pautas ainda podem ter sido localizadas
            omr, falha = next(iter((trabalho / 'audiveris').glob('*.omr')), None), e
        if not (omr and guias.gerar(omr, preparadas, clave, pasta / 'guias')):
            raise falha or ErroConversao('o Audiveris não localizou as pautas')
        return None
    except Cancelado:
        raise
    except Exception as e:
        shutil.rmtree(pasta / 'guias', ignore_errors=True)
        if (trabalho / 'audiveris.log').exists():
            shutil.copyfile(trabalho / 'audiveris.log', pasta / 'audiveris.log')
        return str(e).strip().rstrip('.') or e.__class__.__name__


def montar(tarefa, progresso):
    """Executado pelo processo de trabalho. tarefa: {pasta, paginas, clave, motor, versao_dir, musica...}."""
    pasta = Path(tarefa['pasta'])
    pasta.mkdir(parents=True, exist_ok=True)
    trabalho = pasta / '.trabalho'
    trabalho.mkdir(exist_ok=True)
    clave = tarefa.get('clave') or 'fa'
    try:  # a pasta de trabalho (páginas ampliadas, PDF, saída do Audiveris) passa de 100 MB: sempre sai
        progresso('preparando', 'Convertendo as fotos para JPEG', None, None)
        paginas = [type('P', (), {'caminho': Path(p['caminho']), 'giro': int(p.get('giro', 0))})() for p in tarefa['paginas']]
        pags = imagens.carregar(paginas, trabalho)
        for i, (_nome, im) in enumerate(pags, 1):
            imagens.salvar_jpeg(im, pasta / f'pagina-{i:02d}.jpg', qualidade=90, lado_max=4200)
        sem_guias = _guias(pags, trabalho, pasta, clave, progresso)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    vdir = Path(tarefa['versao_dir']) if tarefa.get('versao_dir') else None
    if vdir and (vdir / 'partitura.musicxml').exists():
        shutil.copyfile(vdir / 'partitura.musicxml', pasta / 'rascunho.musicxml')
        (pasta / 'rascunho-por-compasso.txt').write_text(listar_compassos(mx.ler(vdir / 'partitura.musicxml')), encoding='utf-8')
        if (vdir / 'conferencia.json').exists():
            shutil.copyfile(vdir / 'conferencia.json', pasta / 'conferencia.json')
    m = tarefa['musica']
    base = m['id']
    carimbo = pasta.name
    rel = str(pasta.relative_to(Path(tarefa['raiz']))) if tarefa.get('raiz') else str(pasta)
    nome_clave = 'fá' if clave == 'fa' else 'sol'
    if sem_guias:
        passo_guias = (f'1. **Este pacote não tem guias de altura** ({sem_guias}). Leia as alturas direto nas fotos\n'
                       f'   (`pagina-NN.jpg`), ampliando sistema por sistema; em clave de {nome_clave}, conte as linhas\n'
                       '   suplementares com cuidado e confira cada nota grave contra o rascunho.')
        arquivo_guias = ('- `audiveris.log`: registro do Audiveris (por que as guias não saíram).'
                         if (pasta / 'audiveris.log').exists() else '- (sem guias de altura neste pacote)')
    else:
        passo_guias = (f'1. Para cada sistema, use as imagens de `guias/` (clave de {nome_clave}): as linhas suplementares têm o nome da\n'
                       '   nota desenhado (Mi2, Dó2, Lá1…). Conte as linhas pela guia, não no olho.')
        arquivo_guias = '- `guias/`: cada sistema com as alturas desenhadas.'
    texto = PEDIDO.format(titulo=m['titulo'], instr=f" ({m['instrumento']})" if m.get('instrumento') else '',
                          rel=rel, passo_guias=passo_guias, arquivo_guias=arquivo_guias,
                          motor=tarefa.get('motor') or 'motor', transcricao=f'musicas/{base}/transcricao/transcricao-{carimbo}.py',
                          saida_xml=f'musicas/{base}/transcricao/transcricao-{carimbo}.musicxml',
                          saida_mscz=f"../partituras/{m['titulo']} (revisada).mscz",
                          ultimo=m.get('ultimo_compasso') or 'confira na última página')
    (pasta / 'PEDIDO.md').write_text(texto, encoding='utf-8')
    pedido_curto = f'Revise a música em {rel} seguindo o PEDIDO.md dessa pasta.'
    resultado = {'ok': True, 'pasta': str(pasta), 'pedido': pedido_curto,
                 'quando': datetime.now().isoformat(timespec='seconds')}
    if sem_guias:
        resultado['aviso'] = f'Pacote sem guias de altura: {sem_guias}.'
    return resultado


def tarefa_de_revisao(b, m):
    from .exportar import ultima_versao
    conv, versao = ultima_versao(m)
    vdir = (b.pasta_conversao(m['id'], conv['id']) / 'versoes' / f"{versao['n']:02d}") if versao else None
    pasta = b.musicas / m['id'] / 'revisao' / datetime.now().strftime('%Y%m%d-%H%M%S')
    return {'tipo': 'revisao', 'pasta': str(pasta), 'raiz': str(b.raiz), 'clave': m.get('clave') or 'fa',
            'motor': conv['motor'] if conv else None, 'versao_dir': str(vdir) if vdir else None,
            'paginas': [{'caminho': str(p), 'giro': g} for p, g in b.paginas(m)],
            'musica': {k: m.get(k) for k in ('id', 'titulo', 'instrumento', 'ultimo_compasso')}}

