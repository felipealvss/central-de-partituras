"""Conferência da transcrição de áudio: relatório (dados e texto), síntese da transcrição para ouvir sobre o
original e uma imagem por trecho (espectrograma do stem com a curva de altura e as notas). Ambiente de áudio."""
import numpy as np

SR = 44100
CONFIANCA_BAIXA = 0.5


def sintese(notas, n_amostras, desvio=0.0):
    """Timbre simples (harmônicos com envelope) nas alturas e tempos da transcrição, alinhado ao original."""
    out = np.zeros(n_amostras, dtype=np.float32)
    for n in notas:
        i0, i1 = int(n['t_q0'] * SR), min(int(n['t_q1'] * SR), n_amostras)
        if i1 <= i0 or i0 >= n_amostras or i0 < 0:
            continue
        tt = np.arange(i1 - i0) / SR
        f = 440 * 2 ** ((n['nota'] - 69 + desvio) / 12)
        onda = sum((0.6 ** h) * np.sin(2 * np.pi * f * (h + 1) * tt) for h in range(6))
        env = np.minimum(1, tt / 0.02) * np.minimum(1, (tt[-1] - tt + 1e-3) / 0.05)
        out[i0:i1] += (0.25 * onda * env).astype(np.float32)
    return out


def figura(arquivo, y, t0, tt, midi, notas, batidas, titulo):
    import librosa
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    hop = 512
    S = librosa.amplitude_to_db(np.abs(librosa.cqt(y, sr=SR, hop_length=hop, fmin=librosa.note_to_hz('C1'),
                                                   n_bins=72 * 2, bins_per_octave=24)), ref=np.max)
    fig, ax = plt.subplots(figsize=(14, 4.6))
    ext = [t0, t0 + S.shape[1] * hop / SR, 24, 24 + 72]
    ax.imshow(S, origin='lower', aspect='auto', extent=ext, cmap='magma', vmin=-70, vmax=0)
    ax.plot(tt, midi, color='#3987e5', lw=1.2)
    for n in notas:
        ax.add_patch(plt.Rectangle((n['t_q0'], n['nota'] - 0.4), n['t_q1'] - n['t_q0'], 0.8, fill=False,
                                   ec='#0ca30c' if n['conf'] > CONFIANCA_BAIXA else '#fab219', lw=1.5))
    for b in batidas:
        if ext[0] <= b <= ext[1]:
            ax.axvline(b, color='white', alpha=0.25, lw=0.6)
    validos = midi[~np.isnan(midi)] if len(midi) else midi
    centro = float(np.median(validos)) if len(validos) else 60.0
    ax.set_ylim(max(24, centro - 22), min(96, centro + 22))
    marcas = range(int(ax.get_ylim()[0]) // 5 * 5 + 5, int(ax.get_ylim()[1]), 5)
    ax.set_yticks(list(marcas), [librosa.midi_to_note(m, unicode=False) for m in marcas])
    ax.set_xlabel('tempo (s)')
    ax.set_title(titulo)
    fig.tight_layout()
    fig.savefig(arquivo, dpi=80)
    plt.close(fig)


def _nome(m):
    nomes = ['Dó', 'Dó♯', 'Ré', 'Mi♭', 'Mi', 'Fá', 'Fá♯', 'Sol', 'Lá♭', 'Lá', 'Si♭', 'Si']
    return f'{nomes[m % 12]}{m // 12 - 1}'


def relatorio(instrumento, analise, grade, ajustes, notas, trechos, info_partitura):
    baixa = sum(1 for n in notas if n['conf'] <= CONFIANCA_BAIXA)
    alturas = [n['nota'] for n in notas]
    rel = {
        'tipo': 'audio', 'instrumento': instrumento['id'], 'instrumento_nome': instrumento['nome'],
        'segmentacao': analise['segmentacao'], 'trechos': trechos, 'notas': len(notas), 'baixa_confianca': baixa,
        'bpm': round(grade['bpm'], 1), 'compasso': f"{grade['compasso']}/4",
        'compasso_detectado': f"{grade['compasso_detectado']}/4", 'tom_som': info_partitura['tom_som'],
        'tom_escrito': info_partitura['tom_escrito'], 'afinacao_cents': round(analise['afinacao'] * 100, 1),
        'tessitura_som': [_nome(min(alturas)), _nome(max(alturas))] if alturas else None,
        'fora_extensao': info_partitura['fora_extensao'],
        'fora_dos_trechos_db': (round(analise['fora_dos_trechos_db'], 1)
                                if analise.get('fora_dos_trechos_db') is not None else None),
        'total': info_partitura['compassos'], 'esperado': None, 'diferenca': None, 'ajustes': ajustes,
    }
    rel['alertas'] = bool(not trechos or rel['fora_extensao'] or (notas and baixa / len(notas) > 0.4))
    return rel


def texto(rel):
    linhas = [f"Instrumento: {rel['instrumento_nome']}",
              f"Trechos com o instrumento: {len(rel['trechos'])}",
              f"Notas: {rel['notas']} ({rel['baixa_confianca']} com baixa confiança)",
              f"Andamento: {rel['bpm']} BPM · compasso {rel['compasso']} (detectado: {rel['compasso_detectado']})",
              f"Tom: {rel['tom_som']} em som real · {rel['tom_escrito']} na parte",
              f"Afinação da gravação: {rel['afinacao_cents']:+.0f} cents"]
    if rel['tessitura_som']:
        linhas.append(f"Tessitura (som real): {rel['tessitura_som'][0]}–{rel['tessitura_som'][1]}")
    if rel['fora_dos_trechos_db'] is not None:
        linhas.append(f"Stem fora dos trechos: {rel['fora_dos_trechos_db']} dB (quanto mais negativo, mais limpo)")
    linhas.append('Trechos:')
    for t in rel['trechos']:
        marca = '' if t.get('incluido', True) else ' (excluído)'
        linhas.append(f"  {t['indice']}) {t['inicio']:.1f}–{t['fim']:.1f} s · c. {t.get('compasso_ini')}–"
                      f"{t.get('compasso_fim')} · {t.get('notas', 0)} notas{marca}")
    if rel['fora_extensao']:
        linhas.append('Notas fora da extensão normal (escrita):')
        linhas.extend(f"  c.{f['compasso']}: {f['nota']}{' (altíssimo)' if f['acima'] else ' (grave demais)'}"
                      for f in rel['fora_extensao'])
    return '\n'.join(linhas)
