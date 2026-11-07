"""Conferência do resultado: o relatório como dados (para a interface e o mapa de compassos)
e como texto (para a linha de comando e o arquivo .txt)."""
from . import musicxml as mx


def _duracao(m):
    pos = maximo = 0
    for el in m:
        if el.tag == 'note':
            if el.find('grace') is not None or el.find('chord') is not None:
                continue
            pos += int(el.findtext('duration') or 0)
        elif el.tag == 'backup':
            pos -= int(el.findtext('duration') or 0)
        elif el.tag == 'forward':
            pos += int(el.findtext('duration') or 0)
        maximo = max(maximo, pos)
    return maximo


def analisar(arvore, motor=None, ultimo_compasso=None, ligaduras=(), textos=(), trechos=None):
    """trechos: os trechos de pausa como o motor leu, já situados depois das correções (mx.situar_trechos);
    sem eles, usa os da partitura como está."""
    parte = mx.partes(arvore)[0]
    divisoes, beats, beat_type = 1, 4, 4
    compassos, pausas_longas = [], []
    restante = 0  # compassos que ainda pertencem a uma pausa longa
    for numero, m in enumerate(parte.findall('measure'), 1):
        for at in m.findall('attributes'):
            if at.findtext('divisions'):
                divisoes = int(at.findtext('divisions'))
            if at.findtext('time/beats') and at.findtext('time/beat-type'):
                beats, beat_type = int(at.findtext('time/beats')), int(at.findtext('time/beat-type'))
            mr = at.findtext('measure-style/multiple-rest')
            if mr and mr.strip().isdigit():
                pausas_longas.append({'n': numero, 'lido': int(mr)})
                restante = int(mr)
        notas = m.findall('note')
        tem_nota = any(n.find('rest') is None for n in notas)
        inteira = any(n.find('rest') is not None and n.find('rest').get('measure') == 'yes' for n in notas)
        item = {'n': numero, 'tipo': 'notas' if tem_nota else 'pausa'}
        unidade = divisoes * 4 / beat_type
        dur = _duracao(m)
        if tem_nota and not inteira and m.get('implicit') != 'yes' and abs(dur - beats * unidade) > 1e-6:
            item.update(problema='duracao', tempos=round(dur / unidade, 3), esperado=beats)
        elif not notas and restante <= 0:
            # Compasso sem nenhuma nota nem pausa, fora de pausa longa: é assim que o Audiveris deixa
            # as semibreves que não reconheceu.
            item['problema'] = 'suspeito'
        restante -= 1
        compassos.append(item)
    total = len(compassos)
    diferenca = (total - int(ultimo_compasso)) if ultimo_compasso else None
    rel = {
        'motor': motor,
        'total': total,
        'esperado': int(ultimo_compasso) if ultimo_compasso else None,
        'diferenca': diferenca,
        'com_notas': sum(c['tipo'] == 'notas' for c in compassos),
        'compassos': compassos,
        'trechos': trechos if trechos is not None else mx.trechos_de_pausa(arvore),
        'pausas_longas': pausas_longas,
        'duracao_errada': [c for c in compassos if c.get('problema') == 'duracao'],
        'suspeitos': [c['n'] for c in compassos if c.get('problema') == 'suspeito'],
        'so_pausa': [c['n'] for c in compassos if c['tipo'] == 'pausa'],
        'ligaduras': list(ligaduras),
        'textos_ocr': list(textos),
    }
    rel['alertas'] = bool(rel['duracao_errada'] or rel['suspeitos'] or diferenca)
    return rel


def _linha_trecho(t):
    linha = f"  {t['indice']}) c.{t['inicio']}–{t['fim']}: {t['lidos']} compasso(s)"
    if t.get('grupos'):
        linha += ' = ' + ' + '.join(f'{n} em {f}' if f else str(n) for n, f in t['grupos'])
    elif t.get('compasso'):
        linha += f" em {t['compasso']}"
    lido = t.get('grupos_motor') or []
    if t.get('motor') is not None and (t['motor'] != t['lidos'] or t.get('grupos')):
        linha += f" (o motor leu {' + '.join(str(g['n']) for g in lido) if len(lido) > 1 else t['motor']})"
    elif len(lido) > 1:
        linha += f" (pausas de {' + '.join(str(g['n']) for g in lido)})"
    return linha


def formatar(rel):
    linhas = []
    if rel.get('motor'):
        linhas.append(f"Motor: {rel['motor']}")
    total = f"Compassos no arquivo: {rel['total']}"
    if rel.get('esperado'):
        d = rel['diferenca']
        situacao = 'confere' if d == 0 else (f'faltam {-d}' if d < 0 else f'sobram {d}')
        total += f" · esperado {rel['esperado']} (último número impresso): {situacao}"
    else:
        total += ' (compare com o último número de compasso impresso na partitura)'
    linhas.append(total)
    linhas.append('Trechos de pausa (confira cada número com a partitura; os de dois dígitos costumam sair errados):')
    linhas.extend(_linha_trecho(t) for t in rel['trechos'])
    if not rel['trechos']:
        linhas.append('  nenhum')
    linhas.append('Compassos com duração errada (nota ou figura mal reconhecida):')
    linhas.extend(f"  c.{c['n']}: {c['tempos']:g} de {c['esperado']} tempos" for c in rel['duracao_errada'])
    if not rel['duracao_errada']:
        linhas.append('  nenhum')
    if rel['suspeitos']:
        linhas.append('Compassos vazios entre compassos com notas (provável semibreve perdida):')
        linhas.append('  ' + ', '.join(f'c.{n}' for n in rel['suspeitos']))
    if rel['ligaduras']:
        linhas.append(f"Ligaduras de valor reconhecidas ({len(rel['ligaduras'])}):")
        linhas.extend(f'  {t}' for t in rel['ligaduras'])
    if rel['textos_ocr']:
        linhas.append('Textos de cabeçalho lidos pelo OCR (fora da partitura; confira a grafia e digite no MuseScore):')
        linhas.append('  ' + ' | '.join(rel['textos_ocr']))
    if rel.get('motor') == 'homr':
        linhas.append('O homr não gera dinâmicas, textos nem fermatas, e reconhece só parte dos acentos: acrescente no MuseScore.')
    linhas.append('O reconhecimento nunca é 100%: revise no MuseScore comparando com a partitura original.')
    return '\n'.join(linhas)
