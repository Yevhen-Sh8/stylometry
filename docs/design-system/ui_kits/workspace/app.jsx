/* DIMS Analysis Workspace — interactive recreation.
   Uses the design-system primitives off window.<Namespace>. */
const DS = window.DIMSDesignSystem_175874;
const { Button, Tabs, Input, Select, StatCard, GradeBadge, SourceItem, Alert, Badge } = DS;

/* ── Seed corpus — realistic open-source monitoring set ── */
const SEED = [
  { id: 1, type: 'TELEGRAM', label: "rt_russian (об'єднано 18 постів)", meta: 't.me/rt_russian · 4 210 ток. · 09:14', warn: false },
  { id: 2, type: 'RSS',      label: 'ТАСС — Политика',                 meta: 'tass.ru · 1 240 ток. · 08:51', warn: false },
  { id: 3, type: 'GOOGLE',   label: 'Sputnik: переговоры по Украине',  meta: 'sputnikglobe.com · 980 ток. · 08:30', warn: false },
];

const MFW_HELP = 'Рекомендовано: 50–200. Короткі тексти — 50.';

function Field({ label, children, hint }) {
  return (
    <div className="param-group">
      <label>{label}</label>
      {children}
      {hint && <p className="param-hint">{hint}</p>}
    </div>
  );
}

function Slider({ value, min, max, step, onChange }) {
  return (
    <div className="param-row">
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))} />
      <input className="param-number" type="number" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))} />
    </div>
  );
}

function App() {
  const [theme, setTheme] = React.useState('dark');
  const [tab, setTab] = React.useState('files');
  const [sources, setSources] = React.useState(SEED);
  const [results, setResults] = React.useState(null);
  const [busy, setBusy] = React.useState(false);

  // manual-add form
  const [mLabel, setMLabel] = React.useState('');
  const [mText, setMText] = React.useState('');

  // params
  const [mfw, setMfw] = React.useState(100);
  const [theta, setTheta] = React.useState(0.8);
  const [feature, setFeature] = React.useState('word');
  const [projection, setProjection] = React.useState('mds');

  React.useEffect(() => { document.documentElement.setAttribute('data-theme', theme); }, [theme]);

  const removeSource = (id) => { setSources(s => s.filter(x => x.id !== id)); setResults(null); };
  const clearAll = () => { setSources([]); setResults(null); };

  const addManual = () => {
    if (!mText.trim()) return;
    const isUrl = /^https?:\/\//i.test(mText.trim());
    const id = Date.now();
    setSources(s => [...s, {
      id,
      type: isUrl ? 'URL' : 'TXT',
      label: mLabel.trim() || (isUrl ? mText.trim().replace(/^https?:\/\//, '').slice(0, 40) : 'Текст ' + (s.length + 1)),
      meta: isUrl ? 'автозавантаження · очікує' : (mText.trim().split(/\s+/).length + ' ток.'),
      warn: !isUrl && mText.trim().split(/\s+/).length < 500,
    }]);
    setMLabel(''); setMText(''); setResults(null);
  };

  const runAnalysis = () => {
    setBusy(true); setResults(null);
    setTimeout(() => {
      // Deterministic mock: lower theta + more sources → higher grade.
      const n = sources.length;
      const pairs = (n * (n - 1)) / 2;
      const minDelta = Math.max(0.18, 0.62 - (1.0 - theta) * 0.4);
      const flagged = [
        { a: sources[0]?.label || 'Джерело A', b: sources[1]?.label || 'Джерело B', delta: minDelta, sev: 'critical' },
        sources[2] && { a: sources[1]?.label, b: sources[2]?.label, delta: minDelta + 0.21, sev: 'high' },
      ].filter(Boolean).filter(f => f.delta < theta);
      const rdims = Math.min(0.96, 0.34 + flagged.length * 0.2 + (n >= 4 ? 0.12 : 0));
      const grade = rdims >= 0.8 ? 'SSS' : rdims >= 0.62 ? 'SS' : rdims >= 0.42 ? 'S' : rdims >= 0.2 ? 'B' : 'F';
      setResults({ n, pairs, minDelta, flagged, rdims: rdims.toFixed(2), grade });
      setBusy(false);
    }, 850);
  };

  const canRun = sources.length >= 2 && !busy;
  const escalated = results && (results.grade === 'SS' || results.grade === 'SSS');

  return (
    <React.Fragment>
      {/* Header */}
      <header className="app-header">
        <div className="header-inner">
          <div className="header-logo">
            <div className="header-badge">D</div>
            <div>
              <div className="header-wordmark">DIM<span>S</span></div>
              <div className="header-subtitle">стилометричний аналіз · Δ-Бурровс</div>
            </div>
          </div>
          <div className="header-actions">
            <div className="theme-toggle" role="group" aria-label="Тема">
              {['auto', 'light', 'dark'].map(t => (
                <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>
                  {t === 'auto' ? 'Авто' : t === 'light' ? 'Світла' : 'Темна'}
                </button>
              ))}
            </div>
            <Button variant="ghost" size="sm">Журнал</Button>
          </div>
        </div>
      </header>

      {/* Workspace */}
      <main className="workspace">
        {/* LEFT */}
        <aside className="panel-left">
          <div className="panel-section">
            <div className="panel-section-header">
              <h2>Додати джерела</h2>
              <span className="hint-text">мін. 2</span>
            </div>
            <div style={{ marginBottom: 16 }}>
              <Tabs active={tab} onChange={setTab} tabs={[
                { id: 'files', label: 'Файли' }, { id: 'text', label: 'Текст' },
                { id: 'news', label: 'Новини' }, { id: 'monitor', label: 'Моніторинг' }]} />
            </div>

            {tab === 'files' && (
              <div className="dropzone">
                <div className="dropzone-content">
                  <p>Перетягніть файли сюди</p>
                  <p className="hint">або</p>
                  <Button variant="secondary" size="sm">Вибрати файли</Button>
                  <p className="hint">TXT · PDF · DOCX · RTF · HTML</p>
                </div>
              </div>
            )}

            {tab === 'text' && (
              <div>
                <Input label="Назва джерела" placeholder="напр. RT Telegram, ТАСС, Джерело А"
                  value={mLabel} onChange={e => setMLabel(e.target.value)} />
                <Input label="URL / HTML / текст" textarea mono
                  placeholder="Вставте текст, HTML або URL (https://…)"
                  value={mText} onChange={e => setMText(e.target.value)} />
                <Button variant="primary" onClick={addManual}>Додати джерело</Button>
                <p className="param-hint">URL → автозавантаження · HTML → очищується · Текст → напряму</p>
              </div>
            )}

            {tab === 'news' && (
              <div>
                <Input label="Пошуковий запит" placeholder="напр. зупинка вогню, мобілізація, НАТО" />
                <p className="param-hint" style={{ marginBottom: 12 }}>Мови: RU · DE · FR · UA · EN</p>
                <Button variant="primary" style={{ width: '100%', justifyContent: 'center' }}>Шукати скрізь</Button>
                <p className="param-hint">Google News + збережені RSS + Telegram одночасно</p>
              </div>
            )}

            {tab === 'monitor' && (
              <div>
                <Input label="Тема" placeholder="напр. Переговори / припинення вогню" />
                <Input label="Ключові слова (RU)" textarea placeholder="прекращение огня, переговоры" />
                <Button variant="primary" size="sm">Зберегти тему</Button>
              </div>
            )}
          </div>

          {/* Sources */}
          <div className="panel-section">
            <div className="panel-section-header">
              <h2>Джерела <Badge>{sources.length}</Badge></h2>
              <Button variant="ghost" size="xs" onClick={clearAll}>Очистити</Button>
            </div>
            {sources.length === 0 ? (
              <p className="param-hint" style={{ textAlign: 'center', padding: '24px 0' }}>Ще немає доданих джерел</p>
            ) : (
              <div role="list">
                {sources.map(s => (
                  <SourceItem key={s.id} type={s.type} label={s.label} meta={s.meta} warn={s.warn}
                    onRemove={() => removeSource(s.id)} />
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* RIGHT */}
        <section className="panel-right">
          <div className="panel-card">
            <h2 className="panel-card-title">Параметри аналізу</h2>
            <div className="params-grid">
              <Field label="MFW (найчастіших слів)" hint={MFW_HELP}>
                <Slider value={mfw} min={20} max={500} step={10} onChange={setMfw} />
              </Field>
              <Field label={<span>Поріг <span className="math-inline">θ<sub>Δ</sub></span></span>}
                hint="Менше Δ = більша подібність. Рекомендовано: 0.6–1.0.">
                <Slider value={theta} min={0.1} max={2.0} step={0.05} onChange={setTheta} />
              </Field>
              <div className="param-group">
                <label>Тип ознак</label>
                <Select value={feature} onChange={e => setFeature(e.target.value)}
                  options={[{ value: 'word', label: 'Слова (word tokens)' }, { value: 'char', label: 'Символьні n-грами' }]} />
              </div>
              <div className="param-group">
                <label>Метод проєкції</label>
                <Select value={projection} onChange={e => setProjection(e.target.value)}
                  options={[{ value: 'pca', label: 'PCA (лінійна)' }, { value: 'mds', label: 'MDS (зберігає відстані)' }, { value: 'tsne', label: 't-SNE (нелінійна)' }]} />
              </div>
            </div>
          </div>

          {/* Run */}
          <div className="run-zone">
            <button className="btn-analyze" disabled={!canRun} onClick={runAnalysis}>
              {busy ? 'Аналіз…' : 'Запустити аналіз'}
            </button>
            {!results && (
              <p className="param-hint" style={{ textAlign: 'center', marginTop: 10 }}>
                {sources.length < 2 ? 'Додайте мінімум 2 джерела для запуску' : `${sources.length} джерел готові · ${(sources.length * (sources.length - 1)) / 2} пар`}
              </p>
            )}
          </div>

          {/* Results */}
          {results && (
            <div className="panel-card">
              <h2 className="panel-card-title">Результати аналізу</h2>

              {escalated && (
                <div className={'critical-banner ' + (results.grade === 'SSS' ? 'is-critical' : 'is-high')}>
                  <span className="cb-icon">⚑</span>
                  <div>
                    <div className="cb-title">
                      {results.grade === 'SSS' ? 'Критичний DIMS-ризик' : 'Високий DIMS-ризик'}
                      <span style={{ fontWeight: 500, opacity: .85, marginLeft: 10 }}>R<sub>DIMS</sub> = {results.rdims}</span>
                    </div>
                    <div className="cb-msg">{results.flagged.length} підозрілих пар · пріоритетне опрацювання</div>
                  </div>
                  <button className="cb-cta">До пар</button>
                </div>
              )}

              <div className="stats-grid">
                <StatCard value={results.n} label="Джерел" tone="info" />
                <StatCard value={results.pairs} label="Пар порівняно" tone="info" />
                <StatCard value={results.flagged.length} label="Підозрілих пар" tone={results.flagged.length ? 'danger' : 'ok'} />
                <StatCard value={results.minDelta.toFixed(3)} label="Мін. Δ" tone={results.minDelta < 0.3 ? 'danger' : 'warn'} />
                <StatCard value={results.rdims} label="R DIMS">
                  <GradeBadge grade={results.grade} flag={escalated} />
                </StatCard>
              </div>

              {results.flagged.length > 0 ? (
                <div style={{ marginBottom: 8 }}>
                  {results.flagged.map((f, i) => (
                    <div key={i} className={'flagged-item ' + f.sev}>
                      <div style={{ flex: 1 }}>
                        <div className="flagged-names">{f.a} ↔ {f.b}</div>
                        <div className="flagged-delta">
                          <span className="math-inline">Δ<sub>Burrows</sub></span> = {f.delta.toFixed(4)} · −{((1 - f.delta / theta) * 100).toFixed(0)}% від порогу
                        </div>
                      </div>
                      <Badge tone={f.sev === 'critical' ? 'danger' : 'warn'}>{f.sev === 'critical' ? 'Критичний' : 'Високий'}</Badge>
                    </div>
                  ))}
                </div>
              ) : (
                <Alert tone="info" title="Підозрілих пар не виявлено">
                  Жодна пара не перевищила поріг подібності θ = {theta}.
                </Alert>
              )}

              <div className="results-cta">
                <Button variant="primary" size="large" onClick={() => window.open('../report/index.html', '_blank')}>Відкрити звіт</Button>
                <Button variant="secondary">Завантажити CSV</Button>
              </div>
            </div>
          )}
        </section>
      </main>

      <footer className="app-footer">
        Метод: <span className="math-inline">Δ<sub>Burrows</sub></span> · Burrows (2002) · Удосконалена методика моніторингу інформації у відкритих джерелах
      </footer>
    </React.Fragment>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
