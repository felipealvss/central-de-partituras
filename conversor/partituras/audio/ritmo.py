"""Pulsação, compasso e quantização. As batidas vêm do Beat This! (carregado de um arquivo local, só pesos); o
resto é numpy puro, para os ajustes da revisão (compasso, rotação, andamento ×2/÷2, grade) refazerem tudo em
segundos sem rodar o modelo de novo."""
import numpy as np


def batidas(mistura, checkpoint, dispositivo=None):
    """(batidas, tempos fortes) em segundos, pelo Beat This! na mistura (a seção rítmica dá o pulso)."""
    import torch
    from beat_this.inference import File2Beats
    dispositivo = dispositivo or ('cuda' if torch.cuda.is_available() else 'cpu')
    f2b = File2Beats(checkpoint_path=str(checkpoint), device=dispositivo, dbn=False)
    b, f = f2b(str(mistura))
    return [float(x) for x in b], [float(x) for x in f]


def grade(batidas_s, fortes_s, ajustes=None):
    """Grade de batidas já ajustada: {'batidas', 'bpm', 'compasso', 'primeira_barra'} — primeira_barra é o índice
    da batida em que cai a 1ª barra de compasso. Compasso e fase vêm dos tempos fortes detectados, a menos que o
    usuário informe compasso/rotação; 'andamento' dobra (insere batidas no meio) ou corta pela metade."""
    a = ajustes or {}
    b = np.asarray(batidas_s, dtype=float)
    fortes = np.asarray(fortes_s, dtype=float)
    idx_fortes = [int(np.argmin(np.abs(b - f))) for f in fortes] if len(b) else []
    detectado = int(np.bincount(np.diff(idx_fortes)).argmax()) if len(idx_fortes) > 2 else 4
    fase = idx_fortes[0] if idx_fortes else 0
    if a.get('andamento') == 'dobro' and len(b) > 1:
        meio = (b[:-1] + b[1:]) / 2
        b = np.sort(np.concatenate([b, meio]))
        fase *= 2
    elif a.get('andamento') == 'metade' and len(b) > 2:
        b = b[fase % 2::2]
        fase //= 2
    compasso = int(a.get('compasso') or detectado or 4)
    if a.get('rotacao') is not None:
        fase += int(a['rotacao'])
    fase %= compasso
    bpm = float(60 / np.median(np.diff(b))) if len(b) > 1 else 0.0
    return {'batidas': b, 'bpm': bpm, 'compasso': compasso, 'primeira_barra': fase, 'compasso_detectado': detectado}


def para_batida(t, batidas):
    """Tempo (s) → posição em batidas, interpolando entre as batidas (extrapola nas pontas)."""
    idx = np.arange(len(batidas), dtype=float)
    if t <= batidas[0]:
        return (t - batidas[0]) / (batidas[1] - batidas[0])
    if t >= batidas[-1]:
        return idx[-1] + (t - batidas[-1]) / (batidas[-1] - batidas[-2])
    return float(np.interp(t, batidas, idx))


def de_batida(posicao, batidas):
    idx = np.arange(len(batidas), dtype=float)
    if posicao <= 0:
        return batidas[0] + posicao * (batidas[1] - batidas[0])
    if posicao >= idx[-1]:
        return batidas[-1] + (posicao - idx[-1]) * (batidas[-1] - batidas[-2])
    return float(np.interp(posicao, idx, batidas))


def quantizar(notas, batidas, grade=4, legato=False):
    """Ataque e fim de cada nota na grade (grade=4: semicolcheia). Monofônico: a nota anterior termina onde a
    próxima começa. legato=True estende a nota até a próxima quando o buraco é menor que 1/4 de tempo."""
    q = []
    for n in notas:
        a = round(para_batida(n['t0'], batidas) * grade) / grade
        b = round(para_batida(n['t1'], batidas) * grade) / grade
        q.append({**n, 'b0': a, 'b1': max(b, a + 1 / grade)})
    q.sort(key=lambda n: n['b0'])
    limpas = []
    for n in q:
        if limpas and n['b0'] <= limpas[-1]['b0']:
            if n['conf'] > limpas[-1]['conf']:
                limpas[-1] = n
            continue
        if limpas and limpas[-1]['b1'] > n['b0']:
            limpas[-1]['b1'] = n['b0']
        if legato and limpas and 0 < n['b0'] - limpas[-1]['b1'] < 0.25:
            limpas[-1]['b1'] = n['b0']
        limpas.append(n)
    for n in limpas:
        n['t_q0'], n['t_q1'] = de_batida(n['b0'], batidas), de_batida(n['b1'], batidas)
    return limpas
