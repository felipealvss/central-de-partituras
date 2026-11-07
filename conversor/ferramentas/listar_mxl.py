# Lista as notas de um .mxl (MusicXML compactado) por compasso: usado como conferência cruzada.
import sys, zipfile, xml.etree.ElementTree as ET
z = zipfile.ZipFile(sys.argv[1])
nome = [n for n in z.namelist() if n.endswith('.xml') and not n.startswith('META')][0]
raiz = ET.fromstring(z.read(nome))
for m in raiz.iter('measure'):
    itens = []
    for el in m:
        if el.tag == 'attributes':
            k = el.find('key/fifths'); mr = el.find('measure-style/multiple-rest')
            if k is not None: itens.append(f'[arm {k.text}]')
            if mr is not None: itens.append(f'[multirest {mr.text}]')
        if el.tag != 'note': continue
        d = el.findtext('duration'); t = el.findtext('type') or ''; v = el.findtext('voice')
        if el.find('rest') is not None:
            itens.append(f'pausa:{t or "compasso"}'); continue
        p = el.find('pitch'); alt = p.findtext('alter') or ''
        alt = {'1': '#', '-1': 'b', '0': ''}.get(alt, alt)
        nota = p.findtext('step') + alt + p.findtext('octave')
        dot = '.' if el.find('dot') is not None else ''
        tie = '~' if el.find("tie[@type='start']") is not None else ''
        itens.append(('+' if el.find('chord') is not None else ' ') + f'{nota}:{t}{dot}{tie}(v{v})')
    print(f"c{m.get('number'):>3}: " + ' '.join(itens))
