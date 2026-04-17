#!/usr/bin/env node
/**
 * Candidate heatmap receiver for safe migration.
 * - Keeps legacy monitor untouched
 * - Writes to isolated outputs by default
 * - Detects depth sequence gaps and stale feeds, then resyncs
 * - Emits simple health state for promotion decisions
 */

import fs from 'node:fs';
import path from 'node:path';

function arg(name, def = '') {
  const p = process.argv.find((a) => a.startsWith(`--${name}=`));
  return p ? p.split('=').slice(1).join('=') : def;
}

function createAppendStream(filePath) {
  if (!filePath) return null;
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  } catch {}
  try {
    return fs.createWriteStream(filePath, { flags: 'a' });
  } catch (e) {
    console.error(`[io] stream open failed: ${filePath} :: ${e.message}`);
    return null;
  }
}

function writeLine(stream, filePath, line) {
  if (!filePath) return;
  if (stream) {
    stream.write(line + '\n');
  } else {
    fs.appendFileSync(filePath, line + '\n');
  }
}

function fileSizeSafe(path) {
  if (!path) return 0;
  try {
    return fs.statSync(path).size;
  } catch {
    return 0;
  }
}

function trimFileToTailBytes(path, keepBytes) {
  if (!path || keepBytes <= 0) return;
  let size = 0;
  try {
    size = fs.statSync(path).size;
  } catch {
    return;
  }
  if (size <= keepBytes) return;

  const fd = fs.openSync(path, 'r');
  try {
    const start = Math.max(0, size - keepBytes);
    const buf = Buffer.alloc(size - start);
    fs.readSync(fd, buf, 0, buf.length, start);

    let from = 0;
    while (from < buf.length && buf[from] !== 0x0a) from++;
    if (from < buf.length) from += 1;

    fs.writeFileSync(path, buf.subarray(from));
  } finally {
    fs.closeSync(fd);
  }
}

const symbol = arg('symbol', 'btcusdt').toLowerCase();
const seconds = Number(arg('seconds', '0'));
const sourceTag = arg('sourceTag', 'candidate');
const outFile = arg('out', '');
const bookOutFile = arg('bookOut', '');
const bookRawOutFile = arg('bookRawOut', '');
const bookBucketOutFile = arg('bookBucketOut', '');
const tradeOutFile = arg('tradeOut', '');
const tradeCompactOutFile = arg('tradeCompactOut', '');
const healthOutFile = arg('healthOut', '');
const alertWebhook = arg('alertWebhook', process.env.DISCORD_ALERT_WEBHOOK || '');
const alertCooldownSec = Number(arg('alertCooldownSec', '20'));
const pressureAlertTh = Number(arg('pressureAlertTh', '0.45'));
const alertMode = arg('alertMode', 'all');
const absorptionMinNotional = Number(arg('absorptionMinNotional', '250000'));
const absorptionMaxMoveBps = Number(arg('absorptionMaxMoveBps', '0.45'));
const absorptionMinTrades = Number(arg('absorptionMinTrades', '5'));
const btHorizonSec = Number(arg('btHorizonSec', '5'));
const bucketSizeUsd = Number(arg('bucketSizeUsd', '10'));
const bookWriteEverySec = Math.max(5, Number(arg('bookWriteEverySec', '120')));
const rawTopLevelsToSave = Math.max(50, Number(arg('rawTopLevels', '200')));
const trimCheckEverySec = Number(arg('trimCheckEverySec', '120'));
const loopEveryMs = Math.max(500, Number(arg('loopEveryMs', '2000')));
const enableBookRaw = arg('enableBookRaw', bookRawOutFile ? '0' : '0') === '1';
const trimTargetRatio = Number(arg('trimTargetRatio', '0.85'));
const staleDepthMs = Math.max(1500, Number(arg('staleDepthMs', '5000')));
const staleTradeMs = Math.max(1500, Number(arg('staleTradeMs', '7000')));
const maxResyncPerMin = Math.max(1, Number(arg('maxResyncPerMin', '6')));
const strictSeq = arg('strictSeq', '0') === '1';

const maxOutBytes = Math.floor(Number(arg('maxOutMB', '256')) * 1024 * 1024);
const maxBookBytes = Math.floor(Number(arg('maxBookMB', '512')) * 1024 * 1024);
const maxBookRawBytes = Math.floor(Number(arg('maxBookRawMB', '1536')) * 1024 * 1024);
const maxBookBucketBytes = Math.floor(Number(arg('maxBookBucketMB', '2048')) * 1024 * 1024);
const maxTradeBytes = Math.floor(Number(arg('maxTradeMB', '1536')) * 1024 * 1024);
const maxTradeCompactBytes = Math.floor(Number(arg('maxTradeCompactMB', '512')) * 1024 * 1024);
const tradeCompactIntervalSec = Math.max(10, Number(arg('tradeCompactIntervalSec', '60')));
const tradeCompactPriceBucketUsd = Number(arg('tradeCompactPriceBucketUsd', '10'));

const outStream = createAppendStream(outFile);
const bookStream = createAppendStream(bookOutFile);
const bookRawStream = createAppendStream(bookRawOutFile);
const bookBucketStream = createAppendStream(bookBucketOutFile);
const tradeStream = createAppendStream(tradeOutFile);
const tradeCompactStream = createAppendStream(tradeCompactOutFile);

const DEPTH_WS = `wss://fstream.binance.com/ws/${symbol}@depth@100ms`;
const TRADE_WS = `wss://fstream.binance.com/ws/${symbol}@aggTrade`;
const SNAPSHOT_URL = `https://fapi.binance.com/fapi/v1/depth?symbol=${symbol.toUpperCase()}&limit=1000`;

const state = {
  lastUpdateId: 0,
  bookReady: false,
  syncing: false,
  bids: new Map(),
  asks: new Map(),
  depthBuffer: [],
  prevBestBid: null,
  prevBestAsk: null,
  prevMid: null,
  ofi: 0,
  addNotional: 0,
  cancelNotional: 0,
  tradeBuyQty: 0,
  tradeSellQty: 0,
  tradeBuyNotional: 0,
  tradeSellNotional: 0,
  tradeCount: 0,
  tradeEvents: [],
  tradeCompact: new Map(),
  startedAt: Date.now(),
  lastAlertAt: 0,
  lastBookWriteMs: 0,
  lastDepthMsgAt: 0,
  lastTradeMsgAt: 0,
  lastHealthWriteAt: 0,
  reconnecting: false,
  resyncReasons: [],
  bt: {
    horizonSec: btHorizonSec,
    queue: [],
    n: 0,
    sumX: 0,
    sumY: 0,
    sumXX: 0,
    sumYY: 0,
    sumXY: 0,
    hit: 0,
  },
};

let depthSocket;
let tradeSocket;
let stopTimer;
let loopTimer;
let watchTimer;
let lastTrimCheckMs = 0;
let depthReconnectTimer = null;
let tradeReconnectTimer = null;
let isShuttingDown = false;
let depthSocketSeq = 0;
let activeDepthSeq = 0;
let tradeSocketSeq = 0;
let activeTradeSeq = 0;
let resyncInFlight = false;
let lastResyncAt = 0;

function safeWriteHealth(reason = '') {
  if (!healthOutFile) return;
  const now = Date.now();
  if (!reason && now - state.lastHealthWriteAt < 5000) return;
  state.lastHealthWriteAt = now;
  fs.mkdirSync(path.dirname(healthOutFile), { recursive: true });
  const payload = {
    ts: new Date(now).toISOString(),
    sourceTag,
    symbol: symbol.toUpperCase(),
    bookReady: state.bookReady,
    syncing: state.syncing,
    lastUpdateId: state.lastUpdateId,
    depthBuffer: state.depthBuffer.length,
    lastDepthMsgAt: state.lastDepthMsgAt ? new Date(state.lastDepthMsgAt).toISOString() : null,
    lastTradeMsgAt: state.lastTradeMsgAt ? new Date(state.lastTradeMsgAt).toISOString() : null,
    resyncCount1m: state.resyncReasons.length,
    reason,
  };
  try {
    fs.writeFileSync(healthOutFile, JSON.stringify(payload, null, 2));
  } catch (e) {
    console.error('[health] write failed', e.message);
  }
}

function setLevel(side, priceStr, qtyStr) {
  const p = Number(priceStr);
  const q = Number(qtyStr);
  const book = side === 'b' ? state.bids : state.asks;
  const prev = book.get(p) || 0;

  const delta = q - prev;
  const notionalDelta = Math.abs(delta * p);
  if (delta > 0) state.addNotional += notionalDelta;
  else if (delta < 0) state.cancelNotional += notionalDelta;

  if (q === 0) book.delete(p);
  else book.set(p, q);
}

function bestBid() {
  let max = -Infinity;
  let qty = 0;
  for (const [p, q] of state.bids) {
    if (p > max) {
      max = p;
      qty = q;
    }
  }
  return Number.isFinite(max) ? [max, qty] : [null, null];
}

function bestAsk() {
  let min = Infinity;
  let qty = 0;
  for (const [p, q] of state.asks) {
    if (p < min) {
      min = p;
      qty = q;
    }
  }
  return Number.isFinite(min) ? [min, qty] : [null, null];
}

function depthWindowNotional(side, mid, bps = 10) {
  if (!mid) return 0;
  const low = mid * (1 - bps / 10000);
  const high = mid * (1 + bps / 10000);
  const book = side === 'bid' ? state.bids : state.asks;
  let total = 0;
  for (const [p, q] of book) {
    if (p >= low && p <= high) total += p * q;
  }
  return total;
}

function topLevels(side, n = 40) {
  const arr = [...(side === 'bid' ? state.bids : state.asks).entries()];
  arr.sort((a, b) => (side === 'bid' ? b[0] - a[0] : a[0] - b[0]));
  return arr.slice(0, n);
}

function aggregateToBuckets(side, mid, bucketSize = 10) {
  const src = side === 'bid' ? state.bids : state.asks;
  const out = new Map();

  for (const [p, q] of src.entries()) {
    if (side === 'bid' && p > mid) continue;
    if (side === 'ask' && p < mid) continue;

    const key = side === 'ask'
      ? Math.ceil(p / bucketSize) * bucketSize
      : Math.floor(p / bucketSize) * bucketSize;
    out.set(key, (out.get(key) || 0) + q);
  }

  const arr = [...out.entries()].sort((a, b) => (side === 'bid' ? b[0] - a[0] : a[0] - b[0]));
  return Object.fromEntries(arr.map(([k, v]) => [String(k), v]));
}

function applyDepthEvent(msg) {
  for (const [p, q] of msg.b || []) setLevel('b', p, q);
  for (const [p, q] of msg.a || []) setLevel('a', p, q);
  state.lastUpdateId = msg.u;
}

async function initSnapshotAndSync() {
  state.syncing = true;
  state.bookReady = false;
  safeWriteHealth('snapshot-sync-start');

  const res = await fetch(SNAPSHOT_URL);
  if (!res.ok) throw new Error(`snapshot http ${res.status}`);
  const snap = await res.json();

  state.lastUpdateId = snap.lastUpdateId;
  state.bids.clear();
  state.asks.clear();
  for (const [p, q] of snap.bids) setLevel('b', p, q);
  for (const [p, q] of snap.asks) setLevel('a', p, q);

  const pending = state.depthBuffer
    .filter((e) => e.u > state.lastUpdateId)
    .sort((a, b) => a.u - b.u);

  let start = pending.findIndex((e) => e.U <= state.lastUpdateId + 1 && e.u >= state.lastUpdateId + 1);
  if (start === -1) {
    start = pending.findIndex((e) => e.pu === state.lastUpdateId);
  }

  if (start !== -1) {
    for (let i = start; i < pending.length; i++) {
      const e = pending[i];
      if (e.pu !== undefined && e.pu !== state.lastUpdateId) break;
      applyDepthEvent(e);
    }
  }

  state.depthBuffer.length = 0;
  state.bookReady = true;
  state.syncing = false;
  safeWriteHealth('snapshot-sync-done');
}

function rememberResync(reason) {
  const now = Date.now();
  state.resyncReasons.push({ ts: now, reason });
  state.resyncReasons = state.resyncReasons.filter((x) => now - x.ts < 60_000);
}

async function resyncDepth(reason) {
  if (state.syncing || resyncInFlight || isShuttingDown) return;

  const now = Date.now();
  const minResyncIntervalMs = 1200;
  if (now - lastResyncAt < minResyncIntervalMs) return;
  lastResyncAt = now;

  resyncInFlight = true;
  state.syncing = true;
  rememberResync(reason);
  safeWriteHealth(reason);
  console.error(`[depth] resync reason=${reason}`);
  if (state.resyncReasons.length > maxResyncPerMin) {
    console.error(`[depth] resync storm ${state.resyncReasons.length}/min`);
  }

  try {
    state.depthBuffer.length = 0;
    try { depthSocket?.close(); } catch {}
    connectDepth();
    await initSnapshotAndSync();
  } catch (e) {
    console.error('[depth] resync failed', e.message);
  } finally {
    state.syncing = false;
    resyncInFlight = false;
  }
}

function updateBacktest(nowMs, mid, pressure) {
  const hMs = state.bt.horizonSec * 1000;
  while (state.bt.queue.length && nowMs - state.bt.queue[0].tsMs >= hMs) {
    const old = state.bt.queue.shift();
    const retBps = ((mid / old.mid) - 1) * 10000;
    const x = old.pressure;
    const y = retBps;

    state.bt.n += 1;
    state.bt.sumX += x;
    state.bt.sumY += y;
    state.bt.sumXX += x * x;
    state.bt.sumYY += y * y;
    state.bt.sumXY += x * y;

    if (Math.sign(x) === Math.sign(y) && Math.sign(x) !== 0) state.bt.hit += 1;
  }

  state.bt.queue.push({ tsMs: nowMs, mid, pressure });

  if (state.bt.n < 10) {
    return { n: state.bt.n, corr: null, hitRate: null, horizonSec: state.bt.horizonSec };
  }

  const n = state.bt.n;
  const cov = n * state.bt.sumXY - state.bt.sumX * state.bt.sumY;
  const varX = n * state.bt.sumXX - state.bt.sumX * state.bt.sumX;
  const varY = n * state.bt.sumYY - state.bt.sumY * state.bt.sumY;
  const corr = varX > 0 && varY > 0 ? cov / Math.sqrt(varX * varY) : 0;

  return { n, corr, hitRate: state.bt.hit / Math.max(n, 1), horizonSec: state.bt.horizonSec };
}

async function sendAlert(message) {
  if (!alertWebhook) return;
  const now = Date.now();
  if (now - state.lastAlertAt < alertCooldownSec * 1000) return;
  state.lastAlertAt = now;
  try {
    await fetch(alertWebhook, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content: message }),
    });
  } catch (e) {
    console.error('[alert] send failed', e.message);
  }
}

function enforceStorageCapMaybe(nowMs) {
  if (nowMs - lastTrimCheckMs < trimCheckEverySec * 1000) return;
  lastTrimCheckMs = nowMs;

  const ratio = Math.min(Math.max(trimTargetRatio, 0.5), 0.98);
  const specs = [
    { name: 'out', path: outFile, cap: maxOutBytes },
    { name: 'book', path: bookOutFile, cap: maxBookBytes },
    { name: 'bookRaw', path: bookRawOutFile, cap: maxBookRawBytes },
    { name: 'bookBucket', path: bookBucketOutFile, cap: maxBookBucketBytes },
    { name: 'trade', path: tradeOutFile, cap: maxTradeBytes },
    { name: 'tradeCompact', path: tradeCompactOutFile, cap: maxTradeCompactBytes },
  ].filter((x) => !!x.path && Number.isFinite(x.cap) && x.cap > 0);

  for (const s of specs) {
    const sz = fileSizeSafe(s.path);
    if (sz <= s.cap) continue;
    trimFileToTailBytes(s.path, Math.floor(s.cap * ratio));
  }
}


function compactMinuteKey(tsMs, side, price) {
  const bucketMs = tradeCompactIntervalSec * 1000;
  const bucketTsMs = Math.floor(tsMs / bucketMs) * bucketMs;
  const priceBucket = Math.round(price / tradeCompactPriceBucketUsd) * tradeCompactPriceBucketUsd;
  return `${bucketTsMs}|${side}|${priceBucket.toFixed(2)}`;
}

function flushTradeCompact(nowMs, force = false) {
  if (!tradeCompactOutFile || state.tradeCompact.size === 0) return;
  const cutoffBucketMs = Math.floor(nowMs / (tradeCompactIntervalSec * 1000)) * (tradeCompactIntervalSec * 1000);
  for (const [key, row] of [...state.tradeCompact.entries()]) {
    if (!force && row.bucketTsMs >= cutoffBucketMs) continue;
    writeLine(tradeCompactStream, tradeCompactOutFile, JSON.stringify({
      ts: new Date(row.bucketTsMs).toISOString(),
      symbol: row.symbol,
      side: row.side,
      intervalSec: tradeCompactIntervalSec,
      priceBucketUsd: tradeCompactPriceBucketUsd,
      price_bucket: row.price_bucket,
      qty_sum: row.qty_sum,
      notional_sum: row.notional_sum,
      trade_count: row.trade_count,
      max_qty: row.max_qty,
      max_notional: row.max_notional,
      vwap_price: row.notional_sum / Math.max(row.qty_sum, 1e-9),
      high_price: row.high_price,
      low_price: row.low_price,
    }));
    state.tradeCompact.delete(key);
  }
}

function computeAndFlush() {
  const [bb] = bestBid();
  const [ba] = bestAsk();
  if (!bb || !ba || ba <= bb) return;

  const nowMs = Date.now();
  const mid = (bb + ba) / 2;
  const ts = new Date(nowMs).toISOString();
  const symbolUpper = symbol.toUpperCase();

  if (nowMs - state.lastBookWriteMs >= bookWriteEverySec * 1000) {
    const bookRawRow = {
      ts,
      symbol: symbolUpper,
      sourceTag,
      mid,
      bids: topLevels('bid', rawTopLevelsToSave),
      asks: topLevels('ask', rawTopLevelsToSave),
    };

    const bookBucketRow = {
      ts,
      symbol: symbolUpper,
      sourceTag,
      mid,
      bucketSizeUsd,
      bids_bucketed: aggregateToBuckets('bid', mid, bucketSizeUsd),
      asks_bucketed: aggregateToBuckets('ask', mid, bucketSizeUsd),
    };

    if (bookOutFile) writeLine(bookStream, bookOutFile, JSON.stringify({ ...bookRawRow, ...bookBucketRow }));
    if (enableBookRaw && bookRawOutFile) writeLine(bookRawStream, bookRawOutFile, JSON.stringify(bookRawRow));
    if (bookBucketOutFile) writeLine(bookBucketStream, bookBucketOutFile, JSON.stringify(bookBucketRow));
    state.lastBookWriteMs = nowMs;
  }
  flushTradeCompact(nowMs);

  if (tradeOutFile && state.tradeEvents.length) {
    for (const t of state.tradeEvents) writeLine(tradeStream, tradeOutFile, JSON.stringify({ ...t, sourceTag }));
  }

  enforceStorageCapMaybe(nowMs);
  safeWriteHealth();

  state.tradeBuyQty = 0;
  state.tradeSellQty = 0;
  state.tradeBuyNotional = 0;
  state.tradeSellNotional = 0;
  state.tradeCount = 0;
  state.tradeEvents = [];
}

function handleDepth(msg) {
  if (typeof msg?.u !== 'number') return;
  state.lastDepthMsgAt = Date.now();

  if (!state.bookReady || state.syncing) {
    state.depthBuffer.push(msg);
    if (state.depthBuffer.length > 8000) state.depthBuffer.shift();
    return;
  }

  if (msg.u <= state.lastUpdateId) return;
  const hasGap = (msg.pu !== undefined && msg.pu !== state.lastUpdateId) || msg.U > state.lastUpdateId + 1;
  if (hasGap) {
    const reason = `sequence-gap last=${state.lastUpdateId} pu=${msg.pu} U=${msg.U} u=${msg.u}`;
    if (strictSeq) {
      void resyncDepth(reason);
      return;
    }
    // Tolerant mode for parallel-run stability: accept latest delta instead of resync storm.
    safeWriteHealth('tolerated-gap');
  }

  applyDepthEvent(msg);
}

function handleTrade(msg) {
  state.lastTradeMsgAt = Date.now();
  const price = Number(msg.p);
  const qty = Number(msg.q);
  const notional = price * qty;
  state.tradeCount += 1;
  const side = msg.m ? 'sell' : 'buy';

  if (msg.m) {
    state.tradeSellQty += qty;
    state.tradeSellNotional += notional;
  } else {
    state.tradeBuyQty += qty;
    state.tradeBuyNotional += notional;
  }

  const tradeTsMs = msg.T || Date.now();
  const tradeSymbol = symbol.toUpperCase();
  state.tradeEvents.push({
    ts: new Date(tradeTsMs).toISOString(),
    symbol: tradeSymbol,
    side,
    price,
    qty,
    notional,
  });

  const compactKey = compactMinuteKey(tradeTsMs, side, price);
  const priceBucket = Math.round(price / tradeCompactPriceBucketUsd) * tradeCompactPriceBucketUsd;
  const prev = state.tradeCompact.get(compactKey) || {
    bucketTsMs: Math.floor(tradeTsMs / (tradeCompactIntervalSec * 1000)) * (tradeCompactIntervalSec * 1000),
    symbol: tradeSymbol,
    side,
    price_bucket: priceBucket,
    qty_sum: 0,
    notional_sum: 0,
    trade_count: 0,
    max_qty: 0,
    max_notional: 0,
    high_price: price,
    low_price: price,
  };
  prev.qty_sum += qty;
  prev.notional_sum += notional;
  prev.trade_count += 1;
  prev.max_qty = Math.max(prev.max_qty, qty);
  prev.max_notional = Math.max(prev.max_notional, notional);
  prev.high_price = Math.max(prev.high_price, price);
  prev.low_price = Math.min(prev.low_price, price);
  state.tradeCompact.set(compactKey, prev);
}

import { WebSocket } from 'ws';

function connectDepth() {
  const seq = ++depthSocketSeq;
  activeDepthSeq = seq;
  const ws = new WebSocket(DEPTH_WS);
  depthSocket = ws;

  ws.onopen = () => {
    if (seq !== activeDepthSeq) return;
    console.error('[depth] connected');
  };

  ws.onmessage = (ev) => {
    if (seq !== activeDepthSeq) return;
    try {
      handleDepth(JSON.parse(ev.data.toString()));
    } catch (e) {
      console.error('[depth] parse', e.message);
    }
  };

  ws.onclose = () => {
    if (seq !== activeDepthSeq) return;
    if (isShuttingDown) return;
    if (depthReconnectTimer) clearTimeout(depthReconnectTimer);
    console.error('[depth] closed, reconnecting in 1s');
    depthReconnectTimer = setTimeout(() => {
      if (!state.syncing && !resyncInFlight && !isShuttingDown) connectDepth();
    }, 1000);
  };

  ws.onerror = (e) => {
    if (seq !== activeDepthSeq) return;
    console.error('[depth] error', e.message || e.type || e);
  };
}

function connectTrade() {
  const seq = ++tradeSocketSeq;
  activeTradeSeq = seq;
  const ws = new WebSocket(TRADE_WS);
  tradeSocket = ws;

  if (tradeReconnectTimer) {
    clearTimeout(tradeReconnectTimer);
    tradeReconnectTimer = null;
  }

  ws.onopen = () => {
    if (seq !== activeTradeSeq) return;
    state.lastTradeMsgAt = 0;
    console.error('[trade] connected');
  };

  ws.onmessage = (ev) => {
    if (seq !== activeTradeSeq) return;
    try {
      handleTrade(JSON.parse(ev.data.toString()));
    } catch (e) {
      console.error('[trade] parse', e.message);
    }
  };

  ws.onclose = () => {
    if (seq !== activeTradeSeq) return;
    if (isShuttingDown) return;
    if (tradeReconnectTimer) clearTimeout(tradeReconnectTimer);
    console.error('[trade] closed, reconnecting in 1s');
    tradeReconnectTimer = setTimeout(() => {
      if (!isShuttingDown && seq === activeTradeSeq) connectTrade();
    }, 1000);
  };

  ws.onerror = (e) => {
    if (seq !== activeTradeSeq) return;
    console.error('[trade] error', e.message || e.type || e);
  };
}

function reconnectTrade(reason) {
  if (isShuttingDown) return;
  if (tradeReconnectTimer) {
    clearTimeout(tradeReconnectTimer);
    tradeReconnectTimer = null;
  }
  state.lastTradeMsgAt = 0;
  activeTradeSeq = ++tradeSocketSeq;
  try {
    if (typeof tradeSocket?.terminate === 'function') tradeSocket.terminate();
    else tradeSocket?.close();
  } catch {}
  console.error(`[trade] reconnect reason=${reason} at ${new Date().toISOString()}`);
  connectTrade();
}

function watchdog() {
  const now = Date.now();
  if (state.bookReady && state.lastDepthMsgAt && now - state.lastDepthMsgAt > staleDepthMs) {
    void resyncDepth(`stale-depth ${now - state.lastDepthMsgAt}ms`);
  }
  if (state.lastTradeMsgAt && now - state.lastTradeMsgAt > staleTradeMs) {
    console.error(`[trade] stale ${now - state.lastTradeMsgAt}ms`);
    reconnectTrade(`stale ${now - state.lastTradeMsgAt}ms`);
    safeWriteHealth('trade-reconnect');
  }
}

function shutdown() {
  isShuttingDown = true;
  try { flushTradeCompact(Date.now(), true); } catch {}
  if (depthReconnectTimer) clearTimeout(depthReconnectTimer);
  if (tradeReconnectTimer) clearTimeout(tradeReconnectTimer);
  try { depthSocket?.close(); } catch {}
  try { tradeSocket?.close(); } catch {}
  if (loopTimer) clearInterval(loopTimer);
  if (watchTimer) clearInterval(watchTimer);
  if (stopTimer) clearTimeout(stopTimer);
  try { outStream?.end(); } catch {}
  try { bookStream?.end(); } catch {}
  try { bookRawStream?.end(); } catch {}
  try { bookBucketStream?.end(); } catch {}
  try { tradeStream?.end(); } catch {}
  try { tradeCompactStream?.end(); } catch {}
  safeWriteHealth('shutdown');
  process.exit(0);
}

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

connectDepth();
connectTrade();
await initSnapshotAndSync();

loopTimer = setInterval(() => {
  if (state.bookReady) computeAndFlush();
}, loopEveryMs);

watchTimer = setInterval(watchdog, 1000);

if (seconds > 0) {
  stopTimer = setTimeout(() => {
    console.error(`[main] stop after ${seconds}s`);
    shutdown();
  }, seconds * 1000);
}
