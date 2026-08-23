/**
 * Properties of the (3,3) share scheme, measured rather than asserted.
 *
 *   pnpm check:shares
 *
 * Nothing here is a claim about the construction — every line reads the shares
 * `build()` actually produced and counts. If a future edit trades away the
 * two-sheet security for a prettier picture, check 4 is the one that fails.
 */
import {
	build,
	resolve,
	stats,
	MASK,
	M,
	N,
	MSG_ROWS,
	MSG_COLS,
	ROWS,
	COLS,
	LIT,
	PER
} from '../src/lib/fingerprint-shares.ts';

const hex = (s) =>
	[...Array(40)].map((_, i) => '0123456789abcdef'[(Math.imul(i + 1, s) >>> 3) & 15]).join('');

let bad = 0;
const fail = (m) => {
	console.log('  FAIL ' + m);
	bad++;
};

console.log(
	`grid: message ${MSG_ROWS}x${MSG_COLS} (${M})  rendered ${ROWS}x${COLS} (${N})  lit ${LIT}/${PER}`
);

for (let t = 0; t < 200; t++) {
	const [r, s, m] = [hex(t * 7 + 1), hex(t * 13 + 5), hex(t * 29 + 11)];

	// ---- PASS -------------------------------------------------------------
	const p = build(r, s, m, true);
	const st = stats(p);

	// 1. every share exactly 50% dense
	for (const [i, d] of st.density.entries())
		if (Math.abs(d - LIT / PER) > 1e-12) fail(`t${t} share ${i} density ${d}`);

	// 2. decoded picture is EXACTLY the stencil
	const dec = resolve([p.a, p.b, p.c]);
	for (let i = 0; i < M; i++)
		if (dec[i] !== MASK[i]) {
			fail(`t${t} decoded pixel ${i}: ${dec[i]} vs mask ${MASK[i]}`);
			break;
		}
	if (st.decoded.letters !== 1 || st.decoded.field !== 0)
		fail(`t${t} decoded letters=${st.decoded.letters} field=${st.decoded.field}`);

	// 3. any ONE sheet decodes to a solid slab (no information)
	for (const [i, l] of [p.a, p.b, p.c].entries()) {
		const d1 = resolve([l]);
		if (d1.some((v) => v !== 1)) fail(`t${t} sheet ${i} alone is not a solid slab`);
	}

	// 4. any TWO sheets decode to a solid slab — the early-leak property
	for (const [i, j] of [
		[0, 1],
		[0, 2],
		[1, 2]
	]) {
		const L = [p.a, p.b, p.c];
		const d2 = resolve([L[i], L[j]]);
		if (d2.some((v) => v !== 1)) fail(`t${t} sheets ${i}+${j} leak the word`);
	}

	// 5. raw subcell contrast is the textbook 1-in-4 vs 0-in-4
	if (Math.abs(st.raw.letters - 0.25) > 1e-12 || st.raw.field !== 0)
		fail(`t${t} raw letters=${st.raw.letters} field=${st.raw.field}`);

	// ---- FAIL -------------------------------------------------------------
	const f = build(r, s, m, false);
	// 6. A and B byte-identical to the pass deck
	if (!p.a.every((v, i) => v === f.a[i])) fail(`t${t} share A differs pass/fail`);
	if (!p.b.every((v, i) => v === f.b[i])) fail(`t${t} share B differs pass/fail`);
	// 7. C is the same 50% density
	const sf = stats(f);
	if (Math.abs(sf.density[2] - 0.5) > 1e-12) fail(`t${t} fail share C density ${sf.density[2]}`);
}

// 8. across many runs the failed decode is statistically flat: lit fraction inside
//    the letters must match outside, so the speckle carries no shape
let accL = 0,
	accF = 0,
	nRuns = 400;
for (let t = 0; t < nRuns; t++) {
	const sf = stats(build(hex(t * 3 + 2), hex(t * 17 + 4), hex(t * 41 + 6), false));
	accL += sf.decoded.letters;
	accF += sf.decoded.field;
}
const mL = accL / nRuns,
	mF = accF / nRuns;
console.log(
	`failed decode: lit inside letters ${(mL * 100).toFixed(2)}%  outside ${(mF * 100).toFixed(2)}%  gap ${((mL - mF) * 100).toFixed(3)}pp`
);
if (Math.abs(mL - mF) > 0.02) fail(`failed decode carries a shape: gap ${(mL - mF).toFixed(4)}`);
if (Math.abs(mL - 0.5) > 0.03) fail(`failed decode not ~50% lit: ${mL}`);

console.log(bad ? `\n${bad} FAILURES` : '\nall checks pass');
