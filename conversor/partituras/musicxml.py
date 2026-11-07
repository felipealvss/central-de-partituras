"""Operações sobre MusicXML: ler e gravar, juntar páginas, pausas longas, ligaduras de valor,
trechos de pausa (e sua correção) e limpeza do cabeçalho lido pelo OCR."""
import copy
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NOMES = {'C': 'Dó', 'D': 'Ré', 'E': 'Mi', 'F': 'Fá', 'G': 'Sol', 'A': 'Lá', 'B': 'Si'}
SINAIS = {-2: '𝄫', -1: '♭', 0: '', 1: '♯', 2: '𝄪'}


# ---------------------------------------------------------------- leitura e gravação

def ler(caminho):
    """Lê .musicxml/.xml ou .mxl (compactado)."""
    caminho = Path(caminho)
    if zipfile.is_zipfile(caminho):
        z = zipfile.ZipFile(caminho)
        raiz_nome = None
        if 'META-INF/container.xml' in z.namelist():
            rf = ET.fromstring(z.read('META-INF/container.xml')).find('.//{*}rootfile')
            if rf is not None:
                raiz_nome = rf.get('full-path')
        if not raiz_nome:
            raiz_nome = next(n for n in z.namelist() if n.endswith('.xml') and not n.startswith('META-INF'))
        return ET.ElementTree(ET.fromstring(z.read(raiz_nome)))
    return ET.parse(caminho)


def gravar(arvore, caminho):
    arvore.write(caminho, encoding='utf-8', xml_declaration=True)


def partes(arvore):
    return arvore.getroot().findall('part')


def numerar(arvore):
    for parte in partes(arvore):
        for k, m in enumerate(parte.findall('measure'), 1):
            m.set('number', str(k))


def so_pausa(m):
    return all(n.find('rest') is not None for n in m.findall('note'))


def nome_nota(nota):
    p = nota.find('pitch')
    if p is None:
        return 'pausa'
    alt = int(float(p.findtext('alter') or 0))
    return f"{NOMES.get(p.findtext('step'), '?')}{SINAIS.get(alt, '')}{p.findtext('octave')}"


# ---------------------------------------------------------------- páginas e pausas longas

def _canon(el):
    """Conteúdo de um elemento sem a formatação (espaços e quebras de linha variam entre arquivos)."""
    return (el.tag, tuple(sorted(el.attrib.items())), (el.text or '').strip(), tuple(_canon(c) for c in el))


def unir_paginas(arvores):
    """Junta páginas reconhecidas separadamente numa partitura só, sem repetir clave, armadura
    ou fórmula de compasso iguais às anteriores. A primeira página de cada nova folha recebe quebra de página."""
    base = arvores[0]
    parte = base.getroot().find('part')
    atual = {}

    def registrar(m):
        for at in m.findall('attributes'):
            for tag in ('key', 'time', 'clef'):
                el = at.find(tag)
                if el is not None:
                    atual[tag] = _canon(el)

    for m in parte.findall('measure'):
        registrar(m)
    for arv in arvores[1:]:
        medidas = arv.getroot().find('part').findall('measure')
        for i, m in enumerate(medidas):
            if i == 0:
                m.insert(0, ET.Element('print', {'new-page': 'yes'}))
                for at in m.findall('attributes'):
                    for tag in ('key', 'time', 'clef'):
                        el = at.find(tag)
                        if el is not None and atual.get(tag) == _canon(el):
                            at.remove(el)
            registrar(m)
            parte.append(m)
    numerar(base)
    return base


def normalizar_multirests(arvore):
    """Garante que cada pausa de N compassos tenha N compassos reais (o homr grava um só compasso,
    sem notas; o Audiveris grava os N) e renumera os compassos."""
    for parte in partes(arvore):
        medidas = parte.findall('measure')
        i = 0
        while i < len(medidas):
            mr = medidas[i].find('attributes/measure-style/multiple-rest')
            if mr is not None and (mr.text or '').strip().isdigit():
                n, j = int(mr.text), i + 1
                if medidas[i].find('note') is not None:  # estilo Audiveris: os compassos seguintes já existem
                    while (j < len(medidas) and j - i < n and so_pausa(medidas[j])
                           and medidas[j].find('attributes/measure-style/multiple-rest') is None):
                        j += 1
                pos = list(parte).index(medidas[j - 1]) + 1
                for _ in range(n - (j - i)):
                    parte.insert(pos, ET.Element('measure'))
                medidas = parte.findall('measure')
                i += n
            else:
                i += 1
    numerar(arvore)


# ---------------------------------------------------------------- ligaduras

def _acordes_por_voz(parte):
    """{voz: [(numero_compasso, [notas do acorde])]} na ordem da partitura."""
    vozes = {}
    for m in parte.findall('measure'):
        atual = None
        for el in m:
            if el.tag != 'note' or el.find('grace') is not None:
                continue
            if el.find('chord') is not None and atual is not None:
                atual[1].append(el)
                continue
            atual = (m.get('number'), [el])
            vozes.setdefault(el.findtext('voice') or '1', []).append(atual)
    return vozes


def _altura(nota):
    p = nota.find('pitch')
    return (p.findtext('step'), p.findtext('octave')) if p is not None else None


def _notations(nota):
    n = nota.find('notations')
    if n is None:
        n = ET.Element('notations')
        pos = next((i for i, el in enumerate(nota) if el.tag in ('lyric', 'play', 'listen')), len(nota))
        nota.insert(pos, n)
    return n


def _por_ligadura(nota, tipo):
    filhos = list(nota)
    idx = next((i for i, el in enumerate(filhos) if el.tag == 'duration'), None)
    if idx is None:
        return
    pos = idx + 1
    while pos < len(filhos) and filhos[pos].tag == 'tie':
        pos += 1
    nota.insert(pos, ET.Element('tie', {'type': tipo}))
    _notations(nota).append(ET.Element('tied', {'type': tipo}))


def _manter_acidente(de, para):
    """A ligadura mantém o acidente além da barra: a nota ligada recebe a alteração da primeira."""
    pa, pb = de.find('pitch'), para.find('pitch')
    va = pa.findtext('alter') or '0'
    vb = pb.findtext('alter') or '0'
    if float(va) == float(vb):
        return False
    alt = pb.find('alter')
    if alt is not None:
        pb.remove(alt)
    if float(va) != 0:
        novo = ET.Element('alter')
        novo.text = va
        pb.insert(1, novo)
    acc = para.find('accidental')
    if acc is not None:
        para.remove(acc)
    return True


def ligaduras_de_valor(arvore):
    """Curva entre um acorde e o acorde seguinte da mesma voz, com as mesmas alturas, é ligadura de valor
    (o homr grava todas como ligadura de expressão). Converte e devolve a lista do que mudou."""
    mudancas = []
    for parte in partes(arvore):
        for lista in _acordes_por_voz(parte).values():
            for (c1, notas1), (c2, notas2) in zip(lista, lista[1:]):
                for n1 in notas1:
                    notac = n1.find('notations')
                    if notac is None:
                        continue
                    for s1 in [s for s in notac.findall('slur') if s.get('type') == 'start']:
                        num = s1.get('number', '1')
                        fim = next(((n2, s2) for n2 in notas2 for s2 in (n2.findall('notations/slur'))
                                    if s2.get('type') == 'stop' and s2.get('number', '1') == num), None)
                        if fim is None:
                            continue
                        a1 = {_altura(n): n for n in notas1 if n.find('rest') is None}
                        a2 = {_altura(n): n for n in notas2 if n.find('rest') is None}
                        if not a1 or set(a1) != set(a2) or any(n.find("tie[@type='start']") is not None for n in a1.values()):
                            continue
                        acidente = False
                        for chave, nota in a1.items():
                            _por_ligadura(nota, 'start')
                            _por_ligadura(a2[chave], 'stop')
                            acidente |= _manter_acidente(nota, a2[chave])
                        notac.remove(s1)
                        n2, s2 = fim
                        n2.find('notations').remove(s2)
                        for n in (n1, n2):
                            nt = n.find('notations')
                            if nt is not None and len(nt) == 0:
                                n.remove(nt)
                        nomes = '+'.join(nome_nota(n) for n in sorted(a2.values(), key=lambda n: -_ordem(n)))
                        mudancas.append(f'c.{c1}–{c2} {nomes}' + (' (acidente mantido pela ligadura)' if acidente else ''))
    return mudancas


def _ordem(nota):
    p = nota.find('pitch')
    return int(p.findtext('octave')) * 7 + 'CDEFGAB'.index(p.findtext('step'))


# ---------------------------------------------------------------- trechos de pausa

FORMULA = re.compile(r'^([1-9][0-9]?)/(1|2|4|8|16|32)$')
# Ordem dos filhos de <attributes> no MusicXML: a fórmula de compasso vem antes destes.
_DEPOIS_DA_FORMULA = ('staves', 'part-symbol', 'instruments', 'clef', 'staff-details', 'transpose', 'for-part',
                      'directive', 'measure-style')


def _formula(m):
    """Fórmula de compasso escrita no compasso m, como (tempos, unidade), ou None (vale a última, como no relatório)."""
    formula = None
    for at in m.findall('attributes'):
        b, t = (at.findtext('time/beats') or '').strip(), (at.findtext('time/beat-type') or '').strip()
        if b.isdigit() and t.isdigit():
            formula = int(b), int(t)
    return formula


def _vigentes(parte):
    """(fórmula, divisions) em vigor em cada compasso da parte."""
    formula, divisoes, saida = (4, 4), 1, []
    for m in parte.findall('measure'):
        for at in m.findall('attributes'):
            d = (at.findtext('divisions') or '').strip()
            if d.isdigit():
                divisoes = int(d)
        formula = _formula(m) or formula
        saida.append((formula, divisoes))
    return saida


def _texto_formula(formula):
    return f'{formula[0]}/{formula[1]}'


def _pausa_longa(m):
    n = (m.findtext('attributes/measure-style/multiple-rest') or '').strip()
    return int(n) if n.isdigit() else None


def trechos_de_pausa(arvore, com_elementos=False):
    """Sequências de compassos só com pausa (na 1ª parte), separadas onde muda a armadura ou a fórmula de
    compasso. Cada trecho: {'indice', 'inicio', 'fim', 'lidos', 'compasso', 'grupos'}: números de compasso a partir
    de 1; 'compasso' é a fórmula em vigor no início ('3/4'); 'grupos' são as pausas como estão escritas, uma por
    pausa longa ou compasso de pausa avulso (ex.: [{'n': 4, 'compasso': '4/4'}, {'n': 2, ...}, {'n': 1, ...}]).
    Com `com_elementos`, cada trecho leva também os seus compassos em '_medidas'."""
    parte = partes(arvore)[0]
    vigentes = _vigentes(parte)
    trechos, atual, cobre = [], None, 0
    for i, m in enumerate(parte.findall('measure'), 1):
        if not so_pausa(m):
            atual, cobre = None, 0
            continue
        formula = _texto_formula(vigentes[i - 1][0])
        muda = m.find('attributes/key') is not None or m.find('attributes/time') is not None
        if atual is None or muda:
            atual = {'indice': len(trechos) + 1, 'inicio': i, 'fim': i, 'lidos': 0, 'compasso': formula, 'grupos': []}
            if com_elementos:
                atual['_medidas'] = []
            trechos.append(atual)
            cobre = 0
        longa = _pausa_longa(m)
        if longa or cobre <= 0:  # começa um grupo: uma pausa longa, ou um compasso de pausa avulso
            atual['grupos'].append({'n': 0, 'compasso': formula})
            cobre = longa or 1
        atual['grupos'][-1]['n'] += 1
        cobre -= 1
        atual['lidos'] += 1
        atual['fim'] = i
        if com_elementos:
            atual['_medidas'].append(m)
    return trechos


def _compassos(v, indice):
    try:
        n = int(str(v).strip())
    except ValueError:
        raise ValueError(f'Trecho {indice}: número de compassos inválido ({v}).') from None
    if not 1 <= n <= 999:
        raise ValueError(f'Trecho {indice}: número de compassos inválido ({n}).')
    return n


def validar_correcoes(correcoes):
    """Confere as correções dos trechos de pausa e devolve {indice: compassos} ou, para um trecho dividido em
    grupos, {indice: [(compassos, 'b/t' ou ''), ...]} ('' = fórmula como foi lida). ValueError explica o erro."""
    saida = {}
    for k, v in (correcoes or {}).items():
        try:
            indice = int(k)
        except (TypeError, ValueError):
            raise ValueError(f'Trecho inválido: {k}.') from None
        if isinstance(v, (list, tuple)):
            grupos = []
            for g in v:
                if not isinstance(g, (list, tuple)) or not 1 <= len(g) <= 2:
                    raise ValueError(f'Trecho {indice}: grupo inválido ({g}).')
                formula = str(g[1] or '').strip() if len(g) == 2 else ''
                if formula and not FORMULA.match(formula):
                    raise ValueError(f'Trecho {indice}: fórmula de compasso inválida ({formula}). Use, por exemplo, 3/4.')
                grupos.append((_compassos(g[0], indice), formula))
            if sum(n for n, _ in grupos) > 999:
                raise ValueError(f'Trecho {indice}: compassos demais.')
            if grupos:
                saida[indice] = grupos
        elif v is not None and str(v).strip():
            saida[indice] = _compassos(v, indice)
    return saida


def _definir_multirest(m, n):
    # Um compasso pode ter vários blocos <attributes> (o homr grava assim): limpa o número antigo de todos.
    for bloco in m.findall('attributes'):
        for estilo in bloco.findall('measure-style'):
            for mr in estilo.findall('multiple-rest'):
                estilo.remove(mr)
            if len(estilo) == 0:
                bloco.remove(estilo)
    at = m.find('attributes')
    if n > 1:
        if at is None:
            at = ET.Element('attributes')
            pos = next((i for i, el in enumerate(m) if el.tag not in ('print',)), len(m))
            m.insert(pos, at)
        estilo = at.find('measure-style')
        if estilo is None:
            estilo = ET.SubElement(at, 'measure-style')
        ET.SubElement(estilo, 'multiple-rest').text = str(n)


def _redimensionar(parte, grupo, novo):
    """Deixa o trecho (lista dos seus compassos) com `novo` compassos, mantendo o primeiro (armadura, andamento)
    e o último (fermata, barra dupla/final). Devolve o primeiro compasso."""
    primeiro, ultimo = grupo[0], grupo[-1]
    if novo == 1:
        barras = [b for b in ultimo.findall('barline') if b.get('location', 'right') == 'right']
        for m in grupo[1:]:
            parte.remove(m)
        if ultimo is not primeiro:
            for b in primeiro.findall('barline'):
                if b.get('location', 'right') == 'right':
                    primeiro.remove(b)
            for b in barras:
                primeiro.append(copy.deepcopy(b))
    else:
        for m in grupo[1:-1]:
            parte.remove(m)
        pos = list(parte).index(primeiro) + 1
        if ultimo is primeiro:  # trecho de 1 compasso que vira N: cria os N-1 depois dele
            barras = [b for b in primeiro.findall('barline') if b.get('location', 'right') == 'right']
            for b in barras:
                primeiro.remove(b)
            novos = [ET.Element('measure') for _ in range(novo - 1)]
            for k, nm in enumerate(novos):
                parte.insert(pos + k, nm)
            for b in barras:
                novos[-1].append(b)
        else:
            for k in range(novo - 2):
                parte.insert(pos + k, ET.Element('measure'))
    return primeiro


def _definir_formula(m, formula):
    """Escreve (ou troca) a fórmula de compasso no compasso m; None tira a fórmula escrita."""
    for at in m.findall('attributes'):
        for t in at.findall('time'):
            at.remove(t)
    if formula is None:
        return
    at = m.find('attributes')
    if at is None:
        at = ET.Element('attributes')
        m.insert(next((i for i, el in enumerate(m) if el.tag != 'print'), len(m)), at)
    t = ET.Element('time')
    ET.SubElement(t, 'beats').text = str(formula[0])
    ET.SubElement(t, 'beat-type').text = str(formula[1])
    at.insert(next((i for i, el in enumerate(at) if el.tag in _DEPOIS_DA_FORMULA), len(at)), t)


def _acertar_pausa(m, formula, divisoes, sozinho):
    """Num compasso só de pausa, deixa uma pausa de compasso inteiro com a duração da fórmula em vigor (uma
    semibreve de 4 tempos num 3/4 deixaria o compasso grande demais). Compassos vazios dentro de uma pausa longa
    ficam vazios (o MuseScore completa); um compasso avulso ganha a pausa, para não parecer nota perdida."""
    duracao = divisoes * formula[0] * 4 / formula[1]
    notas = m.findall('note')
    if duracao != int(duracao) or (not notas and not sozinho):
        return
    nova = ET.Element('note')
    ET.SubElement(nova, 'rest').set('measure', 'yes')
    ET.SubElement(nova, 'duration').text = str(int(duracao))
    ET.SubElement(nova, 'voice').text = '1'
    for nome in ('staff', 'notations'):  # pauta e fermata da pausa original
        el = next((n.find(nome) for n in notas if n.find(nome) is not None), None)
        if el is not None:
            nova.append(copy.deepcopy(el))
    pos = next((i for i, el in enumerate(m) if el.tag == 'note'), None)
    if pos is None:
        pos = next((i for i, el in enumerate(m) if el.tag == 'barline' and el.get('location', 'right') == 'right'), len(m))
    for el in list(m):
        if el.tag in ('note', 'backup', 'forward'):
            m.remove(el)
    m.insert(min(pos, len(m)), nova)


def _aplicar_grupos(parte, primeiro, grupos, antes, lido_no_primeiro, seguinte, formula_seguinte):
    """Marca cada grupo do trecho (número da pausa longa e fórmula de compasso) e acerta as pausas.
    antes: fórmula em vigor antes do trecho (None se ele abre a música); lido_no_primeiro: (fórmula, divisions)
    lidas no 1º compasso do trecho; seguinte: o compasso depois do trecho e a fórmula que ele tinha."""
    ms = parte.findall('measure')
    k = ms.index(primeiro)
    trecho = ms[k:k + sum(n for n, _ in grupos)]
    formula, divisoes = lido_no_primeiro
    pos = 0
    for g, (n, texto) in enumerate(grupos):
        m = trecho[pos]
        if texto:
            alvo = tuple(int(x) for x in texto.split('/'))
            if g == 0:  # no 1º compasso, troca a fórmula lida (ou tira, se ela não mudava nada)
                _definir_formula(m, None if alvo == antes else alvo)
            elif alvo != formula:
                _definir_formula(m, alvo)
            formula = alvo
        for mm in trecho[pos:pos + n]:
            _definir_multirest(mm, 1)
            _acertar_pausa(mm, formula, divisoes, sozinho=(n == 1))
        _definir_multirest(m, n)
        pos += n
    if seguinte is not None and _formula(seguinte) is None and formula != formula_seguinte:
        _definir_formula(seguinte, formula_seguinte)  # o que vem depois continua na fórmula que tinha


def corrigir_trechos(arvore, correcoes):
    """Ajusta os trechos de pausa. `correcoes`: {indice do trecho: compassos certos} ou, para dividir o trecho em
    grupos com fórmula de compasso própria, {indice: [(compassos, 'b/t' ou ''), ...]} — por exemplo
    [(5, '3/4'), (3, '4/4'), (1, '')] para "5 em 3/4, 3 em 4/4 e 1". Ver validar_correcoes."""
    correcoes = validar_correcoes(correcoes)
    if not correcoes:
        return []
    parte = partes(arvore)[0]
    medidas = parte.findall('measure')
    vigentes = _vigentes(parte)
    feitas = []
    for t in reversed(trechos_de_pausa(arvore)):  # de trás para frente: os índices de antes não mudam
        pedido = correcoes.get(t['indice'])
        if pedido is None:
            continue
        grupos = pedido if isinstance(pedido, list) else None
        novo = sum(n for n, _ in grupos) if grupos else pedido
        if grupos is None and novo == t['lidos']:
            continue
        primeiro = _redimensionar(parte, medidas[t['inicio'] - 1:t['fim']], novo)
        feita = {'indice': t['indice'], 'lidos': t['lidos'], 'corrigido': novo}
        if grupos:
            seguinte = medidas[t['fim']] if t['fim'] < len(medidas) else None
            _aplicar_grupos(parte, primeiro, grupos, vigentes[t['inicio'] - 2][0] if t['inicio'] > 1 else None,
                            vigentes[t['inicio'] - 1], seguinte, vigentes[t['fim']][0] if seguinte is not None else None)
            feita['grupos'] = [[n, f] for n, f in grupos]
        else:
            _definir_multirest(primeiro, novo)
        feitas.append(feita)
    numerar(arvore)
    return list(reversed(feitas))


def situar_trechos(base, correcoes=None):
    """Os trechos como o motor leu (`trechos_de_pausa(..., com_elementos=True)` antes das correções), com a posição
    e o número de compassos que ficaram depois delas. Os índices são os do motor: é a eles que as correções se
    referem, mesmo quando uma fórmula de compasso informada divide o trecho em dois na partitura final."""
    correcoes = validar_correcoes(correcoes)
    saida = []
    for t in base:
        pedido = correcoes.get(t['indice'])
        grupos = pedido if isinstance(pedido, list) else None
        n = sum(g for g, _ in grupos) if grupos else (pedido or t['lidos'])
        inicio = int(t['_medidas'][0].get('number'))
        saida.append({'indice': t['indice'], 'inicio': inicio, 'fim': inicio + n - 1, 'lidos': n, 'motor': t['lidos'],
                      'compasso': t['compasso'], 'grupos_motor': t['grupos'],
                      'grupos': [[g, f] for g, f in grupos] if grupos else None})
    return saida



# ---------------------------------------------------------------- cabeçalho

def ajustar(arvore, titulo=None, instrumento=None, compositor=None):
    """Remove os textos de cabeçalho lidos pelo OCR (saem desalinhados no MuseScore), define título,
    compositor e nome do instrumento. Devolve os textos removidos, para o relatório."""
    raiz = arvore.getroot()
    textos = []
    for credito in raiz.findall('credit'):
        for cw in credito.iter('credit-words'):
            t = (cw.text or '').strip()
            if t:
                textos.append((float(cw.get('font-size') or 0), t))
        raiz.remove(credito)
    for tag in ('movement-number', 'movement-title'):
        for el in raiz.findall(tag):
            raiz.remove(el)
    ident = raiz.find('identification')
    if ident is not None:
        for el in ident.findall('creator') + ident.findall('source') + ident.findall('miscellaneous'):
            ident.remove(el)
    if compositor:
        if ident is None:
            ident = ET.Element('identification')
            pos = 1 if raiz.find('work') is not None else 0
            raiz.insert(pos, ident)
        cr = ET.Element('creator', {'type': 'composer'})
        cr.text = compositor
        ident.insert(0, cr)
    if not titulo and textos:
        titulo = max(textos)[1]
    if titulo:
        work = raiz.find('work')
        if work is None:
            work = ET.Element('work')
            raiz.insert(0, work)
        wt = work.find('work-title')
        if wt is None:
            wt = ET.SubElement(work, 'work-title')
        wt.text = titulo
    if instrumento:
        for tag in ('part-name', 'part-abbreviation', 'instrument-name'):
            for el in raiz.iter(tag):
                el.text = instrumento
    return [t for _, t in textos]
