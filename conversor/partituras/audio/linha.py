"""Linha isolada: onde o instrumento toca no stem e quais notas ele toca (pYIN + segmentação).

Portado do piloto (sax tenor numa gravação comercial) com os mesmos números por padrão; a faixa de busca e a segmentação
vêm do instrumento (instrumentos.py). Só roda no ambiente de áudio (librosa, soundfile, soxr).
"""
import librosa
import numpy as np
import soundfile as sf
import soxr

SR = 44100
HOP_RMS = 512
HOP_F0 = 512          # 11,6 ms: basta para semicolcheias a 111 BPM (135 ms)
RESOLUCAO_F0 = 0.2    # 1/5 de semitom: metade dos estados do HMM do pYIN (4× mais rápido que 0,1)
LIMIAR_PICO_DB = 24   # trecho ativo: até 24 dB abaixo do pico do stem…
LIMIAR_RAZAO_DB = -14  # …e o stem a no máximo 14 dB abaixo da mistura
TRECHO_MINIMO = 0.6   # segundos
JUNTAR_BURACO = 1.2   # segundos


def ler_mono(caminho):
    a, sr = sf.read(str(caminho), dtype='float32', always_2d=True)
    a = a.mean(axis=1)
    return soxr.resample(a, sr, SR, quality='HQ') if sr != SR else a


def _db(x):
    return 20 * np.log10(np.maximum(x, 1e-9))


def _rms(y):
    return librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP_RMS, center=True)[0]


def _segmentos(ativo, t, min_dur=TRECHO_MINIMO, juntar=JUNTAR_BURACO):
    seg, ini = [], None
    for i, a in enumerate(ativo):
        if a and ini is None:
            ini = t[i]
        if not a and ini is not None:
            seg.append([ini, t[i]])
            ini = None
    if ini is not None:
        seg.append([ini, t[-1]])
    unidos = []
    for s in seg:
        if unidos and s[0] - unidos[-1][1] < juntar:
            unidos[-1][1] = s[1]
        else:
            unidos.append(s)
    return [s for s in unidos if s[1] - s[0] >= min_dur]


def presenca(stem):
    """Fração do tempo em que o stem soa (até 24 dB abaixo do próprio pico): instrumento presente na faixa?"""
    d = _db(_rms(stem))
    return float(np.mean(d > np.percentile(d, 99.5) - LIMIAR_PICO_DB))


def localizar(mix, stem, voz=None):
    """Trechos em que o instrumento soa: [{indice, inicio, fim, dur, nivel_stem_db, stem_vs_mix_db, voz_ativa_pct}],
    e quantos dB a energia do stem cai fora deles (quanto mais negativo, mais limpo o stem)."""
    r_mix, r_stem = _rms(mix), _rms(stem)
    t = librosa.frames_to_time(np.arange(len(r_stem)), sr=SR, hop_length=HOP_RMS)
    stem_db, razao = _db(r_stem), _db(r_stem) - _db(r_mix)
    pico = np.percentile(stem_db, 99.5)
    k = 15  # suaviza ~0,17 s
    suave = np.convolve(stem_db, np.ones(k) / k, mode='same')
    ativo = (suave > pico - LIMIAR_PICO_DB) & (np.convolve(razao, np.ones(k) / k, mode='same') > LIMIAR_RAZAO_DB)
    segs = _segmentos(ativo, t)
    dentro = np.zeros_like(ativo)
    for a, b in segs:
        dentro |= (t >= a) & (t < b)
    energia = r_stem ** 2
    fora_db = (float(10 * np.log10((energia[~dentro].mean() + 1e-12) / (energia[dentro].mean() + 1e-12)))
               if dentro.any() and (~dentro).any() else None)
    voz_db = _db(_rms(voz)) if voz is not None else None
    trechos = []
    for k_, (a, b) in enumerate(segs, 1):
        m = (t >= a) & (t < b)
        item = {'indice': k_, 'inicio': round(float(a), 2), 'fim': round(float(b), 2), 'dur': round(float(b - a), 2),
                'nivel_stem_db': round(float(np.median(stem_db[m])), 1),
                'stem_vs_mix_db': round(float(np.median(razao[m])), 1)}
        if voz_db is not None:
            vm = voz_db[:len(m)]
            limiar = np.percentile(voz_db, 99.5) - LIMIAR_PICO_DB
            item['voz_ativa_pct'] = round(float(np.mean(vm[m[:len(vm)]] > limiar) * 100), 0)
        trechos.append(item)
    return trechos, fora_db


def notas_do_trecho(y, t0, fmin, fmax, seg):
    """Curva de altura (pYIN) e notas de um trecho. seg = parâmetros de segmentação (instrumentos.SEGMENTACAO)."""
    f0, voz, prob = librosa.pyin(y, fmin=fmin, fmax=fmax, sr=SR, frame_length=2048, hop_length=HOP_F0,
                                 resolution=RESOLUCAO_F0)
    tt = t0 + librosa.frames_to_time(np.arange(len(f0)), sr=SR, hop_length=HOP_F0)
    midi = np.where(voz, librosa.hz_to_midi(np.nan_to_num(f0, nan=1.0)), np.nan)
    ataques = set(librosa.onset.onset_detect(y=y, sr=SR, hop_length=HOP_F0, backtrack=True, units='frames',
                                             delta=seg['delta_ataque']))
    adiante, mudanca = seg['olhar_adiante'], seg['mudanca']
    notas, atual = [], None

    def fechar(i):
        nonlocal atual
        if atual and (tt[i] - atual['t0']) >= seg['nota_minima']:
            vals = np.array(atual['m'])
            atual.update(t1=float(tt[i]), alt=float(np.median(vals)), desvio=float(np.std(vals)),
                         conf=float(np.mean(atual['p'])))
            del atual['m'], atual['p']
            notas.append(atual)
        atual = None

    for i in range(len(midi)):
        m = midi[i]
        if np.isnan(m):
            fechar(i)
            continue
        if atual is not None:
            ref = np.median(atual['m'][-seg['janela_mediana']:])
            # nova nota: mudança de altura que se sustenta adiante, ou ataque detectado depois de N quadros
            muda = (abs(m - ref) > mudanca and i + adiante < len(midi) and not np.isnan(midi[i + adiante])
                    and abs(midi[i + adiante] - ref) > mudanca)
            if muda or (i in ataques and len(atual['m']) >= seg['ataque_minimo_quadros']):
                fechar(i)
        if atual is None:
            atual = {'t0': float(tt[i]), 'm': [], 'p': []}
        atual['m'].append(float(m))
        atual['p'].append(float(prob[i]))
    fechar(len(midi) - 1)
    return notas, tt, midi


def afinacao(notas):
    """Desvio da afinação da gravação em semitons (mediana das notas estáveis em relação ao semitom)."""
    estaveis = [x['alt'] for x in notas if x['desvio'] < 0.25 and x['t1'] - x['t0'] > 0.12]
    return float(np.median([m - round(m) for m in estaveis])) if estaveis else 0.0
