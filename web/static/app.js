// Alpine component for the lamp page. State comes from /api/state, then stays
// live via Server-Sent Events from /api/events.

function kelvinToRgb(k) {
  const t = k / 100;
  let r, g, b;
  if (t <= 66) {
    r = 255;
    g = 99.47 * Math.log(t) - 161.12;
    b = t <= 19 ? 0 : 138.52 * Math.log(t - 10) - 305.04;
  } else {
    r = 329.7 * Math.pow(t - 60, -0.1332);
    g = 288.12 * Math.pow(t - 60, -0.0755);
    b = 255;
  }
  return [r, g, b].map(c => Math.max(0, Math.min(255, Math.round(c))));
}

const rgbCss = ([r, g, b], a = 1) => `rgb(${r} ${g} ${b} / ${a})`;
const hexToRgb = hex => [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

window.lampApp = () => ({
  bulbs: {},
  names: [],
  activity: 'idle',
  presets: [],
  budget: null,
  song: null,
  log: [],
  target: 'all',
  sliderValue: 80,
  pickerHex: '#ff9a3c',
  draft: '',
  busy: false,
  listening: false,
  micNote: '',
  connected: true,
  settingsOpen: false,
  toast: '',

  async init() {
    this.sendBrightness = debounce((t, v) => this.post('/api/brightness', { target: t, value: v }), 120);
    this.sendColor = debounce((t, rgb) => this.post('/api/color', { target: t, rgb }), 120);
    await this.load();
    this.connect();
    this.$watch('target', () => this.syncSlider());
  },

  async load() {
    const r = await fetch('/api/state');
    if (r.status === 401) return location.replace('/login');
    this.applySnapshot(await r.json());
  },

  connect() {
    const es = new EventSource('/api/events');
    es.onopen = () => (this.connected = true);
    es.onerror = () => (this.connected = false);
    es.addEventListener('snapshot', e => this.applySnapshot(JSON.parse(e.data)));
    es.addEventListener('state', e => this.applyBulbs(JSON.parse(e.data)));
    es.addEventListener('activity', e => (this.activity = JSON.parse(e.data).kind));
    es.addEventListener('budget', e => (this.budget = JSON.parse(e.data)));
    es.addEventListener('song', e => (this.song = JSON.parse(e.data)));
    es.addEventListener('log', e => this.addLog(JSON.parse(e.data)));
  },

  applySnapshot(s) {
    this.applyBulbs(s.bulbs);
    this.activity = s.activity;
    this.presets = s.presets;
    this.budget = s.budget;
    this.song = s.song;
  },

  applyBulbs(bulbs) {
    this.bulbs = bulbs;
    this.names = Object.keys(bulbs);
    if (this.target !== 'all' && !this.names.includes(this.target)) this.target = 'all';
    if (!this.dragging) this.syncSlider();
  },

  syncSlider() {
    const list = this.target === 'all' ? Object.values(this.bulbs) : [this.bulbs[this.target]].filter(Boolean);
    if (list.length) this.sliderValue = Math.max(...list.map(b => b.brightness));
  },

  addLog(entry) {
    // the same entry arrives both as the POST reply and over SSE; keep one
    const last = this.log[0];
    if (last && last.text === entry.text && last.reply === entry.reply) return;
    this.log.unshift(entry);
    this.log = this.log.slice(0, 8);
  },

  // ---- display helpers ----
  rgbOf(name) {
    const b = this.bulbs[name];
    if (!b) return [0, 0, 0];
    return b.rgb ?? kelvinToRgb(b.kelvin ?? 2700);
  },
  displayColor(name) {
    const b = this.bulbs[name];
    if (!b || !b.on) return 'var(--panel)';
    return rgbCss(this.rgbOf(name));
  },
  glow(name, alpha) {
    const b = this.bulbs[name];
    if (!b || !b.on) return 'transparent';
    const level = 0.25 + 0.75 * (b.brightness / 100);
    return rgbCss(this.rgbOf(name), alpha * level);
  },
  lampStyle() {
    const [top, bottom] = [this.names[0], this.names[1] ?? this.names[0]];
    return [
      `--top-glow:${this.glow(top, 0.95)}`, `--bottom-glow:${this.glow(bottom, 0.95)}`,
      `--top-halo:${this.glow(top, 0.45)}`, `--bottom-halo:${this.glow(bottom, 0.5)}`,
    ].join(';') + (this.anyOn() ? '' : ';background-color:var(--panel)');
  },
  describe(name) {
    const b = this.bulbs[name];
    if (!b) return '';
    if (!b.on) return 'off';
    return `${b.kelvin ? b.kelvin + 'K' : 'color'} · ${b.brightness}%`;
  },
  kelvinCss: k => rgbCss(kelvinToRgb(k)),
  anyOn() { return Object.values(this.bulbs).some(b => b.on); },
  activityLabel() { return { idle: 'still', effect: 'effect running', song: 'music sync' }[this.activity] ?? this.activity; },
  activityBadge() { return this.activity === 'idle' ? 'badge-ghost' : 'badge-secondary'; },
  money: v => (v == null ? "" : v > 0 && v < 0.01 ? "<$0.01" : `$${v.toFixed(2)}`),

  // ---- actions ----
  async post(url, body) {
    try {
      const r = await fetch(url, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (r.status === 401) return location.replace('/login');
      const data = await r.json().catch(() => ({}));
      if (!r.ok) this.flash(data.error ?? `Request failed (${r.status})`);
      return data;
    } catch {
      this.flash('Can’t reach the lamp server');
    }
  },
  flash(msg) {
    this.toast = msg;
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => (this.toast = ''), 3500);
  },
  power(target, on) { return this.post('/api/power', { target, on }); },
  setBrightness(target, v) { this.sendBrightness(target, v); },
  setColor(target, hex) { this.sendColor(target, hexToRgb(hex)); },
  setKelvin(target, k) { return this.post('/api/color', { target, kelvin: k }); },
  applyPreset(name) { return this.post(`/api/preset/${encodeURIComponent(name)}`); },
  stop() { return this.post('/api/stop'); },
  async rename(old, name) {
    name = name.trim().toLowerCase();
    if (name && name !== old) await this.post('/api/bulbs/rename', { old, new: name });
  },

  async send(text) {
    text = (text ?? '').trim();
    if (!text || this.busy) return;
    this.busy = true;
    this.draft = '';
    try {
      const r = await this.post('/api/prompt', { text });
      if (r && r.reply) this.addLog({ text, ...r });
    } finally {
      this.busy = false;
    }
  },

  // voice input lives in Task 10
  toggleMic() {
    this.micNote = 'Voice input is coming next.';
  },
});
