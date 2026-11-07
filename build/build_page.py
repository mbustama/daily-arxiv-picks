#!/usr/bin/env python3
"""Rebuild index.html (the searchable Daily arXiv Picks page) from Selected_papers.txt.

Usage:
    python3 build/build_page.py PATH/TO/Selected_papers.txt [--out index.html] [--check]

Input format (one block per paper, blank line between blocks, lines of dashes between batches):
    *Optional stars, then the title
    Author One, Author Two, ...
    2611.05170 hep-ph

The page is fully self-contained: the data are embedded in index.html and search runs in the browser.
Public-page rules: no author rankings or people section, no private project lists or notes.
"""
import argparse, collections, datetime, difflib, json, math, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December']

# ---------------------------------------------------------------- parsing
KNOWN_CATS = ['astro-ph', 'hep-ph', 'hep-ex', 'hep-th', 'hep-lat', 'gr-qc', 'nucl-th', 'nucl-ex', 'physics',
              'quant-ph', 'cond-mat', 'math-ph', 'math', 'cs', 'stat', 'q-bio', 'q-fin', 'nlin', 'eess', 'econ']
SEP = re.compile(r'^(-+|\++)$')
IDLINE = re.compile(r"^\*?\s*(?:([A-Za-z][A-Za-z\-'\.]*)\s+)?(\d{3,5}(?:[\./\-]|\.\s)\d{1,6}|\d{9})\.?(v\d+)?\s*([A-Za-z][A-Za-z\-'\.]*)?\s*$")
GLUED = re.compile(r'^(.*\S)\s+(\d{4}\.\d{4,5})\s+([A-Za-z][A-Za-z\-\.]*)$')
IDGOOD = re.compile(r'^\d{4}\.\d{4,5}$')


def normcat(c):
    c = (c or '').lower().replace("'", '-').split('.')[0].strip('-')
    if not c:
        return ''
    if c in KNOWN_CATS:
        return c
    m = difflib.get_close_matches(c, KNOWN_CATS, n=1, cutoff=0.6)
    if m:
        return m[0]
    if c.startswith('h'):
        return 'hep-ph'
    if c.startswith('a'):
        return 'astro-ph'
    return c


def parse(path):
    txt = open(path, encoding='utf-8').read().replace('\r', '')
    lines = [l.strip().replace(' ', ' ') for l in txt.split('\n')]
    recs, batch, buf, leftovers = [], 0, [], []
    for ln, l in enumerate(lines):
        if l == '':
            if buf:
                leftovers.append((ln, list(buf)))
            buf = []
            continue
        if SEP.match(l):
            if buf:
                leftovers.append((ln, list(buf)))
            buf = []
            batch += 1
            continue
        m = IDLINE.match(l)
        mg = GLUED.match(l)
        if (m and len(buf) >= 1) or (mg and len(buf) == 1):
            if m:
                raw, cat = m.group(2), (m.group(1) or m.group(4) or '')
            else:
                buf.append(mg.group(1))
                raw, cat = mg.group(2), mg.group(3)
            t = buf[0]
            stars = len(t) - len(t.lstrip('*'))
            title = t.lstrip('*').strip().lstrip('| ').strip()
            aid = re.sub(r'[/\-]|\.\s', '.', raw)
            recs.append(dict(stars=min(stars, 2), title=title, authors=' '.join(buf[1:]), id=aid, rawid=raw,
                             cat=normcat(cat), batch=batch, ok=bool(IDGOOD.match(aid)), line=ln + 1))
            buf = []
        else:
            buf.append(l)
    repair_ids(recs)
    return recs, batch, leftovers


def repair_ids(recs):
    """Fix mistyped arXiv IDs when exactly one one-character edit matches the neighbours' YYMM."""
    def neigh(i, k=6):
        s = set()
        for j in range(max(0, i - k), min(len(recs), i + k + 1)):
            if recs[j]['ok']:
                s.add(recs[j]['id'][:4])
        out = set()
        for p in s:
            y, mo = int(p[:2]), int(p[2:])
            for d in (-1, 0, 1):
                m2, y2 = mo + d, y
                if m2 == 0:
                    m2, y2 = 12, y - 1
                if m2 == 13:
                    m2, y2 = 1, y + 1
                out.add('%02d%02d' % (y2, m2))
        return out

    def cands(s):
        c = set()
        if '.' not in s and len(s) in (8, 9):
            return {s[:4] + '.' + s[4:]}
        for i in range(len(s)):
            c.add(s[:i] + s[i + 1:])
            for d in '0123456789':
                c.add(s[:i] + d + s[i + 1:])
        for i in range(len(s) + 1):
            for d in '0123456789':
                c.add(s[:i] + d + s[i:])
        return c

    for i, r in enumerate(recs):
        if r['ok']:
            continue
        pref = neigh(i)
        good = sorted({c for c in cands(r['id']) if IDGOOD.match(c) and c[:4] in pref and
                       (len(c) == 10 if c[:4] >= '1501' else len(c) == 9)})
        if len(good) == 1:
            r['id'], r['fixed'] = good[0], 'repaired'
        else:
            r['fixed'] = 'uncertain'


# ---------------------------------------------------------------- topics (keyword matches on titles)
TOPICS = {
    'High-energy astrophysical neutrinos': r'icecube|high[- ]energy (astrophysical |cosmic )?neutrino|astrophysical neutrino|neutrino telescope|km3net|baikal|antares|cosmic neutrino',
    'Flavor composition': r'flavo(u)?r (composition|ratio|content|transition|triangle)|flavou?r of (high|astro|cosmic)',
    'UHE neutrinos / UHE cosmic rays': r'ultra[- ]?high[- ]energy|uhe|uhecr|auger|telescope array|cosmogenic|\bgzk\b|eev',
    'Radio detection (GRAND-type)': r'\bradio\b.*(detect|emission|array|shower|neutrino|cosmic)|askaryan|\bgrand\b|\brno\b|\bara\b|arianna|anita|\bpueo\b|lofar.*cosmic|beacon|taroge|tambo|trinity',
    'Tau neutrinos / Earth-skimming': r'tau[- ]neutrino|ν_?τ|\bν\s?τ\b|earth[- ]skimming|tau air[- ]shower|tau lepton',
    'Glashow resonance': r'glashow',
    'Neutrino cross sections / DIS': r'cross[- ]section|deep[- ]inelastic|\bdis\b',
    'GRBs': r'gamma[- ]ray burst|\bgrbs?\b',
    'Blazars / AGN / TXS': r'blazar|txs ?0506|\bagn\b|active galactic',
    'NGC 1068 / Seyferts / coronae': r'ngc ?1068|seyfert|coron(a|ae|al)',
    'TDEs': r'tidal disruption|\btdes?\b',
    'Galactic plane / Galactic neutrinos': r'galactic plane|galactic neutrino|pevatron',
    'Supernova neutrinos': r'supernova(e)? neutrino|neutrinos? from (a |core[- ]collapse )?supernova|core[- ]collapse|\bsn ?1987a\b|pre-?supernova',
    'Neutrino oscillations': r'oscillation',
    'Sterile neutrinos / HNLs': r'sterile|heavy neutral lepton|\bhnls?\b|heavy neutrino',
    'NSI / new neutrino interactions': r'non[- ]standard interaction|\bnsi\b|secret interaction|self[- ]interact|neutrino interactions? (with|beyond)',
    'Lorentz / CPT violation': r'lorentz (invariance )?violat|cpt|\bliv\b|lorentz[- ]violat',
    'Decoherence / quantum gravity': r'decoherence|quantum gravity',
    'Neutrino decay': r'neutrino decay|decaying neutrino|invisible decay',
    'Neutrino mass / Majorana / 0νββ': r'neutrino mass|majorana|double[- ]beta|0\s?ν\s?ββ|neutrinoless|dirac',
    'Dark matter (any)': r'dark matter|\bwimps?\b|dark sector|dark photon',
    'Dark matter and neutrinos': r'(dark matter.*neutrino|neutrino.*dark matter)',
    'Axions / ALPs': r'axion|\balps?\b|axion[- ]like',
    'Primordial black holes': r'primordial black hole|\bpbhs?\b',
    'Magnetic monopoles': r'monopole',
    'Gravitational waves': r'gravitational[- ]wave|\bligo\b|\blisa\b|virgo|kagra|pulsar timing',
    'FRBs': r'fast radio burst|\bfrbs?\b',
    'Cosmology / tensions / DESI': r'hubble tension|\bh_?0\b|\bdesi\b|dark energy|cosmolog',
    'Relic neutrinos / CνB': r'relic neutrino|cosmic neutrino background|c\s?ν\s?b\b',
    'Forward LHC neutrinos (FASER, SND)': r'faser|snd@lhc|forward physics|forward neutrino|forward.*lhc',
    'Machine learning / AI': r'machine learning|neural network|deep learning|\bai\b|artificial intelligence|language model|\bllms?\b|transformer|normalizing flow|simulation[- ]based inference',
    'Statistics / methods': r'statistic|bayesian|likelihood|confidence interval|feldman|unfolding|p-value|look[- ]elsewhere',
    'SETI / technosignatures': r'seti\b|technosignature|extraterrestrial|alien|civilization',
    'Philosophy / sociology of science': r'philosoph|sociolog|peer review|reproducib|scientific (method|statement)|truth|bibliometric|citation',
    'KM3-230213A (220 PeV event)': r'km3-?230213|220 ?pev|km3net.*(event|ultra)',
}
TOPIC_RE = {k: re.compile(v, re.I) for k, v in TOPICS.items()}
CODES = '0123456789abcdefghijklmnopqrstuvwxyz'
OWN_RE = re.compile(r'\b(M\.|Mauricio)\s*Bustamante\b')

# ---------------------------------------------------------------- rising / fading title terms
STOP = set("""a an the of in on for and or with from to by at as is are be its their via using use new into toward towards
beyond between within without under over can do does what how why we our this that these those first study studies search searches
searching constraints constraint probing probe probes implications impact effects effect evidence prospects analysis
revisiting revisited high low small based case cases role nature future current origin observations observation
signatures signature limits limit bounds bound measurement measurements detection detecting test testing tests physics two one three
not more than all part fourth open little update input red event events review status results result data paper report
white approach framework frameworks""".split())
STOP_UNI = set("dark matter black holes hole particle particles neutrino neutrinos cosmic universe galaxies galaxy stars star energy energies strategy model models large".split())


def term_lists(recs, last_year):
    recent = [r for r in recs if r['year'] and r['year'] >= last_year - 1]
    early = [r for r in recs if r['year'] and 2014 <= r['year'] <= last_year - 4]
    forms = collections.defaultdict(collections.Counter)   # case forms seen at non-initial positions of sentence-case titles

    def grams(title):
        t = re.sub(r'\$[^$]*\$', ' ', title)
        raw = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9]", t)
        low = [w.lower() for w in raw]
        long_words = [w for w in raw if len(w) > 3]
        sentence = sum(w[0].isupper() for w in long_words) / max(1, len(long_words)) < 0.5
        g = set()
        for n in (1, 2, 3):
            for k in range(len(low) - n + 1):
                ws = low[k:k + n]
                if any(w in STOP or len(w) <= 2 for w in ws) or (n == 1 and (ws[0] in STOP_UNI or ws[0].isdigit())):
                    continue
                key = ' '.join(ws)
                g.add(key)
                if sentence and k > 0:
                    forms[key][' '.join(raw[k:k + n])] += 1
        return g

    ca, cb = collections.Counter(), collections.Counter()
    for r in recent:
        ca.update(grams(r['title']))
    for r in early:
        cb.update(grams(r['title']))
    na, nb = len(recent), len(early)
    z = {}
    for g in set(ca) | set(cb):
        a, b = ca[g], cb[g]
        if a + b < 14:
            continue
        pa, pb = (a + .5) / (na + 1), (b + .5) / (nb + 1)
        z[g] = (math.log(pa / (1 - pa)) - math.log(pb / (1 - pb))) / math.sqrt(1 / (a + .5) + 1 / (b + .5))

    def norm(g):
        return g.replace('-', ' ')

    def label(g):
        f = forms.get(g)
        if f:
            best = f.most_common(1)[0][0]
            if any(ch.isupper() or ch.isdigit() for ch in best):
                return best
        return g

    def named(g):
        f = forms.get(g)
        if not f:
            return any(ch.isdigit() for ch in g)
        tot = sum(f.values())
        return sum(c for o, c in f.items() if any(ch.isupper() or ch.isdigit() for ch in o)) / tot > 0.6

    def pick(sign, n):
        cand = sorted((g for g in z if sign * z[g] > 2.5), key=lambda g: -sign * z[g])
        # drop a gram when a longer gram containing it is nearly as strong
        drop = set()
        for g in cand:
            for h in cand:
                if h != g and norm(g) in norm(h) and sign * z[h] >= 0.6 * sign * z[g]:
                    drop.add(g)
                    break
        out, seen = [], []
        for g in cand:
            if g in drop:
                continue
            if ' ' not in g:
                lab = label(g)
                acronym = any(ch.isdigit() for ch in lab) or any(ch.isupper() for ch in lab[1:])
                if not (acronym or (len(g) >= 9 and lab == g)):
                    continue
            k = norm(g)
            kw = set(k.split())
            if any(k in s or s in k or len(kw & set(s.split())) >= 2 for s in seen):
                continue
            seen.append(k)
            out.append([label(g), ca[g], cb[g]])
            if len(out) >= n:
                break
        return out

    sy = lambda y: str(y)[2:]
    return pick(1, 18), pick(-1, 16), f'{last_year - 1}–{sy(last_year)}', f'2014–{sy(last_year - 4)}'


# ---------------------------------------------------------------- build
def build(src, out, check=False):
    recs, nbatches, leftovers = parse(src)
    for r in recs:
        r['year'] = 2000 + int(r['id'][:2]) if IDGOOD.match(r['id']) else None
        r['topics'] = [i for i, (k, rx) in enumerate(TOPIC_RE.items()) if rx.search(r['title'])]
    ids_ok = [r['id'] for r in recs if IDGOOD.match(r['id'])]
    newest = collections.Counter(r['id'][:4] for r in recs[:40] if IDGOOD.match(r['id'])).most_common(1)[0][0]
    oldest = collections.Counter(r['id'][:4] for r in recs[-40:] if IDGOOD.match(r['id'])).most_common(1)[0][0]
    last_id, first_id = max(max(ids_ok)[:4], newest) + '.0', oldest + '.0'
    last_year = 2000 + int(last_id[:2])
    years = list(range(2014, last_year + 1))

    ys = []
    for y in years:
        rr = [r for r in recs if r['year'] == y]
        c = collections.Counter(r['cat'] for r in rr)
        ys.append(dict(y=y, n=len(rr), s0=sum(r['stars'] == 0 for r in rr), s1=sum(r['stars'] == 1 for r in rr),
                       s2=sum(r['stars'] == 2 for r in rr), astro=c['astro-ph'], hepph=c['hep-ph'], hepex=c['hep-ex'],
                       other=len(rr) - c['astro-ph'] - c['hep-ph'] - c['hep-ex']))
    py = {d['y']: (d['s1'] + d['s2']) / d['n'] for d in ys if d['n']}
    names = list(TOPICS)
    tstats = []
    for i, k in enumerate(names):
        rr = [r for r in recs if i in r['topics'] and r['year'] in py]
        if not rr:
            continue
        obs = sum(r['stars'] > 0 for r in rr)
        exp = sum(py[r['year']] for r in rr)
        share = [round(100 * sum(1 for r in rr if r['year'] == d['y']) / d['n'], 2) if d['n'] else 0 for d in ys]
        tstats.append(dict(k=k, i=i, n=len(rr), starred=obs, lift=round(obs / exp, 2) if exp else 0, share=share))
    rise, fade, recent_lbl, early_lbl = term_lists(recs, last_year)

    data = dict(
        years=years, ys=ys, topics=names, tstats=tstats, rise=rise, fade=fade,
        recs=[[r['id'], r['title'], r['authors'], r['cat'], r['stars'], r['year'] or 0,
               ''.join(CODES[t] for t in r['topics']),
               0 if r['ok'] else (1 if r.get('fixed') == 'repaired' else 2), 0] for r in recs],
        own=[i for i, r in enumerate(recs) if OWN_RE.search(r['authors'])],
        meta=dict(n=len(recs), batches=nbatches, s1=sum(r['stars'] == 1 for r in recs),
                  s2=sum(r['stars'] == 2 for r in recs),
                  first=MONTHS[int(first_id[2:4]) - 1][:3] + ' 20' + first_id[:2],
                  last=MONTHS[int(last_id[2:4]) - 1][:3] + ' 20' + last_id[:2]))
    span = f"{MONTHS[int(first_id[2:4]) - 1]} 20{first_id[:2]} – {MONTHS[int(last_id[2:4]) - 1]} 20{last_id[:2]}"
    untagged = round(100 * sum(1 for r in recs if not r['topics']) / len(recs))

    tpl = open(os.path.join(HERE, 'template.html'), encoding='utf-8').read()
    page = (tpl.replace('/*DATA*/null', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
            .replace('__N__', f'{len(recs):,}').replace('__SPAN__', span)
            .replace('__LASTYEAR__', str(last_year)).replace('__LASTMONTH__', MONTHS[int(last_id[2:4]) - 1])
            .replace('__UNTAGGED__', str(untagged)).replace('__RECENT__', recent_lbl).replace('__EARLY__', early_lbl))
    assert not re.search(r'__[A-Z]+__', page), 'unfilled placeholder'

    prev_n = None
    if os.path.exists(out):
        m = re.search(r'"meta":\{"n":(\d+)', open(out, encoding='utf-8').read())
        prev_n = int(m.group(1)) if m else None
    open(out, 'w', encoding='utf-8').write(page)

    bad = [r for r in recs if not r['ok']]
    dup = [k for k, v in collections.Counter(r['id'] for r in recs).items() if v > 1]
    print(f'Wrote {out} ({len(page) / 1e6:.2f} MB)')
    print(f'Papers: {len(recs):,}' + (f'  (previous build: {prev_n:,}; change {len(recs) - prev_n:+,})' if prev_n else ''))
    print(f'Span: {span}; batches: {nbatches}; ★ {data["meta"]["s1"]:,}; ★★ {data["meta"]["s2"]:,}; own papers: {len(data["own"])}')
    print(f'Latest year {last_year}: {ys[-1]["n"]:,} picks')
    print(f'Mistyped IDs: {len(bad)} ({sum(r.get("fixed") == "repaired" for r in bad)} repaired, '
          f'{sum(r.get("fixed") == "uncertain" for r in bad)} unclear); duplicate IDs: {len(dup)}')
    if leftovers:
        print(f'Unparsed blocks: {len(leftovers)} (first few below; fix them in the text file)')
        for ln, b in leftovers[:5]:
            print(f'  near line {ln}: {b}')
    new_bad = [r for r in bad if r['line'] < 2000]
    for r in new_bad[:10]:
        print(f'  recent mistyped ID at line {r["line"]}: {r["rawid"]} → {r["id"] if r.get("fixed") == "repaired" else "?"}  ({r["title"][:60]})')
    print('Rising terms:', ', '.join(x[0] for x in rise[:10]))
    print('Fading terms:', ', '.join(x[0] for x in fade[:10]))
    if check:
        smoke_test(out, len(recs))


def smoke_test(path, n):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('Skipping browser check (playwright not installed)')
        return
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={'width': 1100, 'height': 900})
        errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.route(re.compile(r'fonts\.(googleapis|gstatic)'), lambda r: r.abort())
        pg.goto('file://' + os.path.abspath(path) + '#overview')
        pg.wait_for_timeout(600)
        bars = pg.evaluate("document.querySelectorAll('#chVol svg path, #chVol svg rect').length")
        rows = pg.evaluate("document.querySelectorAll('#tTop tbody tr').length")
        pg.goto('file://' + os.path.abspath(path) + '#search')
        pg.wait_for_timeout(400)
        pg.fill('#q', 'neutrino')
        pg.wait_for_timeout(400)
        res = pg.evaluate("document.querySelector('#resN').textContent")
        total = pg.evaluate('R.length')
        b.close()
    ok = not errs and bars > 10 and rows > 20 and total == n and res and not res.startswith('0')
    print(f'Browser check: {"OK" if ok else "PROBLEM"} — errors {errs}, chart marks {bars}, topic rows {rows}, '
          f'records {total}, search "neutrino" → {res}')
    if not ok:
        sys.exit(1)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('src', help='path to Selected_papers.txt')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(HERE), 'index.html'))
    ap.add_argument('--check', action='store_true', help='load the page in headless Chromium and run a search')
    a = ap.parse_args()
    build(a.src, a.out, a.check)
