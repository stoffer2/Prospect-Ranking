// List prospects that are FREE AGENTS (unowned) — uses same logic as index.html
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const csv = fs.readFileSync('Fantrax-Players- Mike Zunino Memorial League (3).csv', 'utf8');

const rawMatch = html.match(/const RAW_DATA = \[([\s\S]*?)\];/);
const RAW_DATA = eval('[' + rawMatch[1] + ']');
const prospectNames = RAW_DATA.map(p => p.name);

// --- Exact copies from index.html ---
function looksLikeMlbTeam(s) {
  const v = (s || '').trim();
  if (!v || v.length > 6) return false;
  return /^[A-Z]{2,3}$/i.test(v) || /^(tb|sd|sf|la|nyy|nym|chw|chc|kc|stl|ari|atl|bal|bos|cle|col|det|hou|mil|min|oak|sea|tex|tor|was|wsh|mia|phi|cws|cin)$/i.test(v);
}
function looksLikeId(s) {
  const v = (s || '').trim();
  if (!v || v.length < 8) return false;
  return /^[0-9a-f]{8,}$/i.test(v) || (/^[a-z0-9]{10,}$/i.test(v) && !/[aeiou]/i.test(v));
}
function looksLikePercentOrStat(s) {
  const v = (s || '').trim();
  if (!v) return false;
  if (/%$/.test(v)) return true;
  const n = parseFloat(v.replace(/%/g, ''));
  return !isNaN(n) && v.replace(/[\d.\s%]/g, '').length === 0;
}
function parseCsvLine(line, sep) {
  if (sep === '\t') return line.split(sep).map(c => c.replace(/^"|"$/g, '').trim());
  const out = [];
  let cur = '', inQuote = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') inQuote = !inQuote;
    else if (ch === ',' && !inQuote) {
      out.push(cur.replace(/^"|"$/g, '').trim());
      cur = '';
    } else cur += ch;
  }
  out.push(cur.replace(/^"|"$/g, '').trim());
  return out;
}
function parseFantasyCsv(text) {
  const lines = text.trim().split(/[\r\n]+/).filter(l => l.trim());
  if (lines.length < 2) return {};
  const sep = lines[0].includes('\t') ? '\t' : ',';
  const cols = parseCsvLine(lines[0], sep).map(c => c.toLowerCase());
  const parseRow = i => parseCsvLine(lines[i], sep);

  let playerIdx = cols.findIndex(c => /^player$|^name$|^hitter$|^pitcher$/.test(c));
  if (playerIdx === -1) playerIdx = cols.findIndex(c => c.includes('player') || c.includes('name'));
  if (playerIdx === -1) playerIdx = 0;

  const statHeaders = /^(pos|position|slot|elig|ab|hr|rbi|avg|ip|k|whip|era|sv|id|player.?id|owned|owned.?%|own.?%|ownership|%|pct)$/i;
  const ownerHeaders = /^owner$|^fantasy|^fantasy.?team$|^team.?owner$|^manager$|^owned.?by$|^drafted.?by$|^franchise$|^gm$/;

  let ownerIdx = -1;
  const statusIdx = cols.findIndex(c => /^status$/i.test(c));
  if (statusIdx >= 0) {
    const statusVals = [];
    for (let r = 1; r < Math.min(lines.length, 51); r++) {
      const v = (parseRow(r)[statusIdx] || '').trim();
      if (v) statusVals.push(v);
    }
    const hasFa = statusVals.some(v => /^fa$/i.test(v));
    const valid = statusVals.filter(v => !looksLikePercentOrStat(v)).length;
    if (hasFa || valid >= statusVals.length * 0.8) ownerIdx = statusIdx;
  }
  let bestScore = -1;

  for (let c = 0; c < cols.length && ownerIdx === -1; c++) {
    if (c === playerIdx || statHeaders.test(cols[c])) continue;
    const vals = [];
    for (let r = 1; r < Math.min(lines.length, 101); r++) {
      const v = (parseRow(r)[c] || '').trim();
      if (v) vals.push(v);
    }
    if (vals.length < 3) continue;

    const mlbLike = vals.filter(v => looksLikeMlbTeam(v)).length;
    const idLike = vals.filter(v => looksLikeId(v)).length;
    const percentLike = vals.filter(v => looksLikePercentOrStat(v)).length;
    const validVals = vals.filter(v => !looksLikeMlbTeam(v) && !looksLikeId(v) && !looksLikePercentOrStat(v));
    const unique = new Set(validVals).size;

    if (mlbLike >= vals.length * 0.6) continue;
    if (idLike >= vals.length * 0.4) continue;
    if (percentLike >= vals.length * 0.5) continue;
    if (unique < 2 || unique > vals.length * 0.95) continue;

    const leagueSized = unique >= 3 && unique <= 24;
    const headerMatch = ownerHeaders.test(cols[c]);
    const teamHeaderOk = /^team$/.test(cols[c]) && mlbLike < vals.length * 0.3;

    let score = validVals.length * 2 + unique;
    if (headerMatch) score += 500;
    else if (teamHeaderOk) score += 50;
    if (leagueSized) score += 100;

    if (score > bestScore) {
      bestScore = score;
      ownerIdx = c;
    }
  }

  if (ownerIdx === -1) {
    const explicit = cols.findIndex(c => ownerHeaders.test(c) && !statHeaders.test(c));
    if (explicit >= 0) {
      const exVals = [];
      for (let r = 1; r < Math.min(lines.length, 21); r++) {
        const v = (parseRow(r)[explicit] || '').trim();
        if (v) exVals.push(v);
      }
      if (exVals.filter(v => looksLikePercentOrStat(v)).length < exVals.length * 0.5) ownerIdx = explicit;
    }
    if (ownerIdx === -1) ownerIdx = cols.length > 2 ? cols.length - 1 : 1;
  }

  const map = {};
  for (let i = 1; i < lines.length; i++) {
    const cells = parseRow(i);
    const name = (cells[playerIdx] || '').trim();
    const owner = (cells[ownerIdx] || '').trim();
    if (!name) continue;
    const ownerUpper = owner.toUpperCase();
    if (ownerUpper === 'FA' || /^fa$/i.test(owner)) continue;
    if (ownerIdx !== statusIdx && (looksLikeMlbTeam(owner) || looksLikePercentOrStat(owner))) continue;
    if (!owner || owner.length < 1) continue;
    const n = normalizeName(name);
    map[n] = owner;
  }
  return map;
}
function normalizeName(s) {
  return s.replace(/\s+/g, ' ').trim().toLowerCase();
}
function lastNameFromParts(parts) {
  if (!parts.length) return '';
  const last = parts[parts.length - 1]?.toLowerCase() || '';
  const suffix = /^(jr\.?|iii?|iv|ii|sr\.?)$/i.test(last);
  return suffix && parts.length >= 2 ? parts[parts.length - 2]?.toLowerCase() || '' : last;
}
function fuzzyMatchProspect(prospectName, ownershipMap) {
  const n = normalizeName(prospectName);
  if (ownershipMap[n]) return ownershipMap[n];
  const prospectParts = prospectName.trim().split(/\s+/);
  const prospectFirst = prospectParts[0]?.toLowerCase() || '';
  const prospectLast = lastNameFromParts(prospectParts);
  const prospectInitial = prospectFirst.charAt(0);
  for (const [k, v] of Object.entries(ownershipMap)) {
    const csvParts = k.trim().split(/\s+/);
    const csvLast = lastNameFromParts(csvParts);
    const csvFirst = csvParts[0]?.toLowerCase() || '';
    if (csvLast !== prospectLast) continue;
    const csvInitial = csvFirst.charAt(0);
    if (prospectInitial && csvInitial && prospectInitial !== csvInitial) continue;
    return v;
  }
  return null;
}

// Build ownership map (owned players only) — same as site
const ownershipMap = parseFantasyCsv(csv);
const unowned = prospectNames.filter(name => !fuzzyMatchProspect(name, ownershipMap));
unowned.sort((a, b) => a.localeCompare(b));

unowned.forEach(n => console.log(n));
console.log('\nTotal: ' + unowned.length + ' prospects are free agents (highlighted on site)');
