"""Instrumentos-alvo do modo de áudio.

O instrumento direciona a cadeia inteira: qual stem separar, em que faixa procurar as notas (em som real), como
segmentar a curva de altura em notas, a transposição e a clave da parte, o som no MuseScore e os avisos de
extensão. Só biblioteca padrão: o servidor importa este módulo.
"""

NOTAS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def midi(nome):
    """Nome de nota → número MIDI (Dó4 = 60): 'G2' → 43, 'Bb3' → 58, 'F#6' → 90."""
    letra, resto = nome[0].upper(), nome[1:]
    alteracao = 0
    while resto and resto[0] in '#b♯♭':
        alteracao += 1 if resto[0] in '#♯' else -1
        resto = resto[1:]
    return 12 * (int(resto) + 1) + NOTAS[letra] + alteracao


# Segmentação da curva de altura em notas. "piloto" reproduz o teste da faixa do piloto (avaliado pelo usuário como
# quase perfeito); "melhorada" traz as regras da pesquisa (vibrato largo, notas repetidas, legato) e só vira
# padrão se o gabarito mostrar ganho.
SEGMENTACAO = {
    'piloto': {
        'mudanca': 0.75,             # semitons de distância da mediana recente para começar outra nota
        'olhar_adiante': 2,          # a mudança precisa continuar N quadros depois (filtra picos de vibrato)
        'janela_mediana': 12,        # quadros usados como referência de altura da nota em curso
        'nota_minima': 0.05,         # segundos
        'ataque_minimo_quadros': 9,  # um ataque só separa a nota em curso depois de N quadros
        'delta_ataque': 0.12,        # sensibilidade do detector de ataques (librosa)
        'legato': False,             # estender a nota até a próxima quando o buraco for menor que 1/4 de tempo
    },
    'melhorada': {
        'mudanca': 1.0, 'olhar_adiante': 3, 'janela_mediana': 12, 'nota_minima': 0.03,
        'ataque_minimo_quadros': 3, 'delta_ataque': 0.12, 'legato': True,
    },
}
SEGMENTACAO_PADRAO = 'piloto'

# transposicao = (diatônica, cromática) de escrito para som real, como no <transpose> do MusicXML.
# extensao_escrita = extensão normal da parte (MIDI, escrito); acima dela, altíssimo/agudo extremo (aviso).
# busca = faixa da curva de altura (som real), com folga para altíssimo e notas de efeito.
INSTRUMENTOS = {
    'sax-tenor': {
        'nome': 'Sax tenor', 'stem': 'saxophone', 'music21': 'TenorSaxophone',
        'som': 'wind.reed.saxophone.tenor', 'transposicao': (-8, -14), 'clave': ('G', 2),
        'extensao_escrita': (midi('Bb3'), midi('F#6')), 'busca': ('G2', 'C6'),
    },
    'sax-alto': {
        'nome': 'Sax alto', 'stem': 'saxophone', 'music21': 'AltoSaxophone',
        'som': 'wind.reed.saxophone.alto', 'transposicao': (-5, -9), 'clave': ('G', 2),
        'extensao_escrita': (midi('Bb3'), midi('F#6')), 'busca': ('C3', 'F6'),
    },
    'sax-soprano': {
        'nome': 'Sax soprano', 'stem': 'saxophone', 'music21': 'SopranoSaxophone',
        'som': 'wind.reed.saxophone.soprano', 'transposicao': (-1, -2), 'clave': ('G', 2),
        'extensao_escrita': (midi('Bb3'), midi('F#6')), 'busca': ('G3', 'A6'),
    },
    'sax-baritono': {
        'nome': 'Sax barítono', 'stem': 'saxophone', 'music21': 'BaritoneSaxophone',
        'som': 'wind.reed.saxophone.baritone', 'transposicao': (-12, -21), 'clave': ('G', 2),
        'extensao_escrita': (midi('A3'), midi('F#6')), 'busca': ('B1', 'A5'),
    },
    'trompete': {
        'nome': 'Trompete em Si♭', 'stem': 'trumpet', 'music21': 'Trumpet',
        'som': 'brass.trumpet', 'transposicao': (-1, -2), 'clave': ('G', 2),
        'extensao_escrita': (midi('F#3'), midi('D6')), 'busca': ('D3', 'A6'),
    },
    'trombone': {
        'nome': 'Trombone', 'stem': 'trombone', 'music21': 'Trombone',
        'som': 'brass.trombone', 'transposicao': (0, 0), 'clave': ('F', 4),
        'extensao_escrita': (midi('E2'), midi('F5')), 'busca': ('A1', 'A5'),
    },
}
PADRAO = 'sax-tenor'
# Stems guardados por música: trocar entre sax, trompete e trombone não exige separar de novo; a voz serve
# para apontar vazamento.
STEMS = tuple(sorted({i['stem'] for i in INSTRUMENTOS.values()})) + ('vocal',)


def obter(iid):
    if iid not in INSTRUMENTOS:
        raise ValueError(f'Instrumento desconhecido: {iid}.')
    return {'id': iid, **INSTRUMENTOS[iid]}


def para_interface():
    return [{'id': k, 'nome': v['nome'], 'stem': v['stem']} for k, v in INSTRUMENTOS.items()]


ANDAMENTOS = ('auto', 'dobro', 'metade')


def validar_ajustes(ajustes):
    """Ajustes de uma nova transcrição (sem separar de novo). Devolve só o que foi informado, normalizado:
    trechos {índice: incluir}, compasso (tempos por compasso), rotacao (onde cai o 1º tempo), andamento
    ('auto' | 'dobro' | 'metade'), grade (4 = semicolcheia, 2 = colcheia). ValueError explica o erro."""
    a = ajustes or {}
    if not isinstance(a, dict):
        raise ValueError('Ajustes em formato inválido.')
    saida = {'trechos': {}}
    trechos = a.get('trechos') or {}
    if not isinstance(trechos, dict):
        raise ValueError('Trechos em formato inválido.')
    for k, v in trechos.items():
        try:
            i = int(k)
        except (TypeError, ValueError):
            raise ValueError(f'Trecho inválido: {k}.') from None
        if not 1 <= i <= 999:
            raise ValueError(f'Trecho inválido: {k}.')
        saida['trechos'][str(i)] = bool(v)
    if a.get('compasso') not in (None, ''):
        c = _inteiro(a['compasso'], 'compasso')
        if not 2 <= c <= 6:
            raise ValueError('O compasso deve ter de 2 a 6 tempos.')
        saida['compasso'] = c
    if a.get('rotacao') not in (None, ''):
        r = _inteiro(a['rotacao'], 'rotação')
        if not 0 <= r < saida.get('compasso', 6):
            raise ValueError('Rotação fora do compasso.')
        saida['rotacao'] = r
    andamento = a.get('andamento') or 'auto'
    if andamento not in ANDAMENTOS:
        raise ValueError(f'Andamento deve ser {", ".join(ANDAMENTOS)}.')
    if andamento != 'auto':
        saida['andamento'] = andamento
    if a.get('grade') not in (None, ''):
        g = _inteiro(a['grade'], 'grade')
        if g not in (2, 4):
            raise ValueError('Grade deve ser 4 (semicolcheia) ou 2 (colcheia).')
        saida['grade'] = g
    return saida


def _inteiro(v, nome):
    try:
        return int(str(v).strip())
    except ValueError:
        raise ValueError(f'Valor inválido para {nome}: {v}.') from None
