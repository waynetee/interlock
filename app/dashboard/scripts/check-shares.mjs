/**
 * Properties of the tiled-ground scheme, measured rather than asserted.
 *
 *   pnpm check:shares
 *
 * Nothing here is a claim about the construction -- every line reads the sheets
 * `build()` actually produced and counts. Check 2 is the one the whole thing exists
 * for: the stack is the stencil exactly, with no threshold in between.
 *
 * Check 6 is different in kind. It measures the gap the construction is KNOWN to
 * have -- the word is faintly visible in a single sheet -- so the cost shows up as a
 * number in the output rather than a footnote nobody reads.
 */
import {
	build,
	union,
	stats,
	MASK,
	N,
	ROWS,
	COLS,
	DENSITY
} from '../src/lib/fingerprint-shares.ts';

const hex = (s) =>
	[...Array(40)].map((_, i) => '0123456789abcdef'[(Math.imul(i + 1, s) >>> 3) & 15]).join('');

let bad = 0;
const fail = (m) => {
	console.log('  FAIL ' + m);
	bad++;
};

const letters = MASK.reduce((n, v) => n + v, 0);
const target = Math.round(N * DENSITY);
console.log(`grid    ${ROWS} x ${COLS} = ${N} cells, one per message pixel, no expansion`);
console.log(`sheets  ${target} lit cells each = ${((target / N) * 100).toFixed(2)}% of the panel`);
console.log(`stencil ${letters} of ${N} cells are letter (${((letters / N) * 100).toFixed(1)}%)\n`);

let ghostAcc = 0;
let dropAcc = 0;
let failGround = 0;
let failLetters = 0;
const runs = 200;

for (let t = 0; t < runs; t++) {
	const [r, s, m] = [hex(t * 7 + 1), hex(t * 13 + 5), hex(t * 29 + 11)];
	const tag = `t${t}`;

	const p = build(r, s, m, true);
	const L = [p.a, p.b, p.c];
	const st = stats(p);

	// 1. every sheet lights the same number of cells, whatever the digests are
	for (const [i, d] of st.density.entries()) {
		if (Math.round(d * N) !== target)
			fail(`${tag} sheet ${i} lit ${Math.round(d * N)}, want ${target}`);
	}

	// 2. the stack IS the stencil, cell for cell. No threshold, no second resolution.
	const u = union(L);
	for (let i = 0; i < N; i++) {
		const want = MASK[i] ? 0 : 1;
		if (u[i] !== want) {
			fail(`${tag} stacked cell ${i}: ${u[i]} want ${want}`);
			break;
		}
	}
	if (st.stacked.letters !== 0 || st.stacked.field !== 1) {
		fail(`${tag} stacked letters=${st.stacked.letters} field=${st.stacked.field}`);
	}

	// 3. nothing on the table lights nothing
	if (union([]).some((v) => v !== 0)) fail(`${tag} the empty stack is not black`);

	// 4. drop any one sheet and the ground no longer fills -- every sheet is load
	//    bearing, because the ground was partitioned between them
	for (const [i, j] of [
		[0, 1],
		[0, 2],
		[1, 2]
	]) {
		const two = stats(
			Object.fromEntries([
				['a', i === 0 || j === 0 ? L[0] : undefined],
				['b', i === 1 || j === 1 ? L[1] : undefined],
				['c', i === 2 || j === 2 ? L[2] : undefined]
			])
		);
		const filled = two.stacked.field;
		if (filled >= 1) fail(`${tag} sheets ${i}+${j} already fill the ground`);
		dropAcc += filled;
	}

	// 5. A and B are byte-identical pass or fail; C keeps its density either way
	const f = build(r, s, m, false);
	if (!p.a.every((v, i) => v === f.a[i])) fail(`${tag} sheet A differs pass/fail`);
	if (!p.b.every((v, i) => v === f.b[i])) fail(`${tag} sheet B differs pass/fail`);
	const sf = stats(f);
	if (Math.round(sf.density[2] * N) !== target)
		fail(`${tag} fail sheet C lit ${sf.density[2] * N}`);
	// a C that does not fit leaves the ground holed AND puts light in the letters
	const fg = sf.stacked.field;
	const fl = sf.stacked.letters;
	failGround += fg;
	failLetters += fl;
	if (fg >= 0.999) fail(`${tag} a non-completing C still filled the ground`);
	if (fl <= 0.001) fail(`${tag} a non-completing C left the letters clean`);

	ghostAcc += st.ghost.reduce((a, b) => a + b, 0) / 3;
}

// 6. THE KNOWN GAP, measured. A stack that is completely black over the letters means
//    no sheet lit a letter cell, so every sheet has a hole shaped like the word. This
//    is how big that hole is, and it is 0 by construction rather than by accident.
console.log(
	`single sheet: ${((ghostAcc / runs) * 100).toFixed(1)}% of its lit cells fall inside the letters`
);
console.log(`              (33.3% everywhere else, so the word is there as an absence)`);
console.log(
	`two sheets:   ground ${((dropAcc / (runs * 3)) * 100).toFixed(1)}% filled -- visibly holed, not blank`
);
console.log(
	`non-fitting C: ground ${((failGround / runs) * 100).toFixed(1)}% filled, letters ${((failLetters / runs) * 100).toFixed(1)}% lit`
);

if (ghostAcc / runs !== 0) fail(`sheets are lighting letter cells: ${ghostAcc / runs}`);

console.log(bad ? `\n${bad} FAILURES` : '\nall checks pass');
