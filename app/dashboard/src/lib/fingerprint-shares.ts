/**
 * Fingerprint shares — three sheets of light that tile the ground.
 *
 * The three fingerprint grids are not three pictures that get swapped for a fourth
 * at the end. Each carries a third of the lit cells, and the picture is what they
 * add up to when you lay them over one another. Stacking them is the reveal; nothing
 * downstream of `build()` knows the message.
 *
 * ── the construction ────────────────────────────────────────────────────────────
 *
 * One cell per message pixel — no subcell expansion, no threshold, no read. What you
 * see stacked is literally the union of the three sheets, cell for cell.
 *
 *   LETTER cell   no sheet lights it. Ever. It is black on all three sheets and it
 *                 is black in the stack, which is the point.
 *   GROUND cell   dealt to exactly one of the three sheets. Every ground cell is
 *                 owned by somebody, so the three together leave none of it dark.
 *
 * Lay the sheets down and the ground fills completely while the letters stay black.
 * There is nothing between those two states because there is nothing to threshold:
 * a cell was lit by somebody or it was not.
 *
 * Sheets are then topped up to a third of the WHOLE panel. Owning a third of the
 * ground is a third of the panel minus a third of the letters, so each sheet also
 * lights a few cells another sheet already owns. That costs nothing — a cell lit
 * twice looks the same in the stack as a cell lit once — and it buys a density that
 * is the same 33% on every sheet however big the word is.
 *
 * ── what this costs, stated plainly ─────────────────────────────────────────────
 *
 * A single sheet is 33% dense over the ground and 0% dense over the letters, so the
 * word is faintly there in each one, as an absence. That is not a bug to be fixed
 * later; it is forced. A stack that is COMPLETELY black over the letters means no
 * sheet lit a letter cell, and a sheet that never lights a letter cell has a hole in
 * it shaped like the word.
 *
 * Hiding that hole is what pixel expansion buys, and it costs the thing that was
 * wanted more: with expansion the letters can only ever be a third lit rather than
 * black, and getting them to black again needs a threshold pass over the subcells.
 * This file takes the other side of that trade on purpose — a true black word in a
 * true solid ground, read straight off the cells, at the price of a legible ghost in
 * each sheet.
 *
 * ── what this is NOT ────────────────────────────────────────────────────────────
 *
 * The sheets are not three independent functions of three independent digests. They
 * cannot be — no three hashes chosen by the world tile a word chosen by us. The
 * request digest deals the ground out; each sheet's own digest picks its top-up; the
 * model digest is the sheet that either fits the deal or does not. The honest claim
 * is the one the panel makes: the picture is genuinely the union of the three, and it
 * is only whole when the third sheet is the one that was dealt.
 */

export const ROWS = 29; // 21 for the face, four rows of margin above and below
export const COLS = 91; // 5 glyphs x 13 wide + 4 gaps x 4 + 5 margin each side
export const N = ROWS * COLS;
/** what every sheet lights, as a fraction of the whole panel */
export const DENSITY = 1 / 3;

/**
 * 13x21 face, every stroke ONE cell wide.
 *
 * A hairline is affordable because a cell is either lit or it is not — there is no
 * dither for a thin stroke to get lost in. The face is drawn large in cells rather
 * than large on screen for the reason a typeface is: at 7x11 a one-cell stroke is a
 * seventh of the letter and the diagonals climb in four visible steps; at 13x21 it is
 * a thirteenth, and the V descends in twenty-one.
 */
const GLYPHS: Record<string, string[]> = {
	V: [
		'#...........#',
		'#...........#',
		'.#.........#.',
		'.#.........#.',
		'.#.........#.',
		'..#.......#..',
		'..#.......#..',
		'..#.......#..',
		'..#.......#..',
		'...#.....#...',
		'...#.....#...',
		'...#.....#...',
		'....#...#....',
		'....#...#....',
		'....#...#....',
		'....#...#....',
		'.....#.#.....',
		'.....#.#.....',
		'.....#.#.....',
		'......#......',
		'......#......'
	],
	A: [
		'......#......',
		'......#......',
		'.....#.#.....',
		'.....#.#.....',
		'.....#.#.....',
		'....#...#....',
		'....#...#....',
		'....#...#....',
		'....#...#....',
		'...#.....#...',
		'...#.....#...',
		'...#.....#...',
		'..#.......#..',
		'..#.......#..',
		'..#########..',
		'..#.......#..',
		'.#.........#.',
		'.#.........#.',
		'.#.........#.',
		'#...........#',
		'#...........#'
	],
	L: [
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#............',
		'#############'
	],
	I: [
		'#############',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'......#......',
		'#############'
	],
	D: [
		'###########..',
		'#..........#.',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#...........#',
		'#..........#.',
		'###########..'
	]
};
const GW = 13;
const GK = 4;

export function stencil(word: string) {
	const mask = new Uint8Array(N);
	const gh = GLYPHS[word[0]].length;
	const x0 = Math.floor((COLS - (word.length * (GW + GK) - GK)) / 2);
	const y0 = Math.floor((ROWS - gh) / 2);
	for (let li = 0; li < word.length; li++) {
		const g = GLYPHS[word[li]];
		for (let r = 0; r < gh; r++) {
			for (let c = 0; c < GW; c++) {
				if (g[r][c] === '#') mask[(y0 + r) * COLS + x0 + li * (GW + GK) + c] = 1;
			}
		}
	}
	return mask;
}

export const MASK = stencil('VALID');

/** FNV-1a over the hex, then xorshift32. Tagged so one digest can drive two streams. */
function stream(hex: string, tag: number) {
	let h = (0x811c9dc5 ^ tag) >>> 0;
	for (let i = 0; i < hex.length; i++) {
		h ^= hex.charCodeAt(i);
		h = Math.imul(h, 0x01000193) >>> 0;
	}
	let s = h || 0x9e3779b9;
	return () => {
		s ^= s << 13;
		s >>>= 0;
		s ^= s >>> 17;
		s ^= s << 5;
		s >>>= 0;
		return s;
	};
}

/** Partial Fisher–Yates: k of pool, without replacement. k === pool.length shuffles. */
function pick(pool: number[], k: number, next: () => number) {
	const a = pool.slice();
	const n = Math.min(k, a.length);
	for (let i = 0; i < n; i++) {
		const j = i + (next() % (a.length - i));
		const t = a[i];
		a[i] = a[j];
		a[j] = t;
	}
	return a.slice(0, n);
}

/**
 * There is no polarity switch here, and that is a consequence rather than an
 * omission. Inverting it would make the LETTERS the side that fills — 8.5% of the
 * panel — and three sheets at a third of the panel each cannot fit inside 8.5% of
 * it. A solid ground with a black word is the only way round this construction goes.
 */

export type Shares = {
	/** per cell: 0 = unlit, 1..4 = brightness (texture only, never read as data) */
	a: Uint8Array;
	b: Uint8Array;
	c: Uint8Array;
};

/**
 * Build the three sheets. `pass` decides sheet C only — A and B are byte-identical
 * either way, so the deck gives nothing away before the verdict lands.
 */
export function build(req: string, rsp: string, model: string, pass: boolean): Shares {
	const nDeal = stream(req, 1); // how the ground is dealt out
	const tops = [stream(req, 5), stream(rsp, 6), stream(model, 7)]; // each sheet's top-up
	const nMiss = stream(model, 9); // sheet C when it does not fit the deal
	const lvl = [stream(req, 17), stream(rsp, 18), stream(model, 19)];

	// the cells that must stay dark on every sheet
	const ground: number[] = [];
	for (let i = 0; i < N; i++) if (!MASK[i]) ground.push(i);

	// Deal every ground cell to exactly one sheet. This is the whole trick: the union
	// covers the ground because the ground was partitioned, not because it happened to
	// come out that way.
	const dealt = pick(ground, ground.length, nDeal);
	const own: number[][] = [[], [], []];
	for (let k = 0; k < dealt.length; k++) own[k % 3].push(dealt[k]);

	const target = Math.round(N * DENSITY);
	const sets = own.map((mine, s) => {
		if (mine.length >= target) return pick(mine, target, tops[s]);
		// top up from ground somebody else already owns — invisible in the stack,
		// and it is what makes every sheet the same density as every other
		const taken = new Set(mine);
		const spare = ground.filter((i) => !taken.has(i));
		return mine.concat(pick(spare, target - mine.length, tops[s]));
	});

	if (!pass) {
		// A sheet that does not fit the deal: the same count of cells, drawn from the
		// whole panel with no regard for the deal or for the word. Same density, so C
		// alone is indistinguishable — it just no longer completes anything.
		const all = Array.from({ length: N }, (_, i) => i);
		sets[2] = pick(all, target, nMiss);
	}

	const out = [new Uint8Array(N), new Uint8Array(N), new Uint8Array(N)];
	for (let s = 0; s < 3; s++) {
		for (const i of sets[s]) out[s][i] = 1 + (lvl[s]() % 4);
	}
	return { a: out[0], b: out[1], c: out[2] };
}

/**
 * The stack: a cell is lit if any sheet handed in lit it. That is the entire read —
 * there is no threshold and no second resolution, which is why what you see is what
 * the sheets are. No MASK below this line.
 */
export function union(layers: Uint8Array[]): Uint8Array {
	const out = new Uint8Array(N);
	for (let i = 0; i < N; i++) out[i] = layers.some((l) => l[i]) ? 1 : 0;
	return out;
}

/** How many of the handed-in sheets lit each cell — what the stack is coloured by. */
export function depth(layers: Uint8Array[]): Uint8Array {
	const out = new Uint8Array(N);
	for (let i = 0; i < N; i++) {
		let n = 0;
		for (const l of layers) if (l[i]) n++;
		out[i] = n;
	}
	return out;
}

/** Measured, not asserted — /lab prints these so the scheme can be checked by eye. */
export function stats(s: Partial<Shares>) {
	const layers = [s.a, s.b, s.c].filter(Boolean) as Uint8Array[];
	const density = layers.map((l) => l.reduce((n, v) => n + (v ? 1 : 0), 0) / N);

	const u = union(layers);
	let litL = 0;
	let litF = 0;
	let nL = 0;
	let nF = 0;
	for (let i = 0; i < N; i++) {
		if (MASK[i]) {
			nL++;
			if (u[i]) litL++;
		} else {
			nF++;
			if (u[i]) litF++;
		}
	}

	// how much of each single sheet falls inside the letters — the ghost, measured
	const ghost = layers.map((l) => {
		let n = 0;
		let t = 0;
		for (let i = 0; i < N; i++)
			if (MASK[i]) {
				t++;
				if (l[i]) n++;
			}
		return t ? n / t : 0;
	});

	return {
		density,
		ghost,
		stacked: { letters: nL ? litL / nL : 0, field: nF ? litF / nF : 0 },
		layers: layers.length
	};
}
