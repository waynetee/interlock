/**
 * Fingerprint shares — a (3,3) visual secret sharing scheme over the run's digests.
 *
 * The three fingerprint grids are not three pictures that get swapped for a fourth
 * at the end. They are three SHARES, and the word is what their union actually is.
 * Stacking them is the reveal; nothing downstream of `build()` knows the message.
 *
 * ── the construction ────────────────────────────────────────────────────────────
 *
 * Naor–Shamir (3,3), the textbook one, four subcells per message pixel laid out
 * 2x2. A share's row is a set of subcells it INKS. Two base matrices, rows written
 * as the index sets of their ones:
 *
 *   CLEAR pixel   {2,3} {1,3} {1,2}   union {1,2,3}  -> subcell 0 stays clear
 *   OPAQUE pixel  {0,1} {0,2} {0,3}   union all four -> nothing gets through
 *
 * Per pixel we draw a random permutation of the four columns and a random
 * assignment of the three rows to the three shares, then hand one row to each.
 *
 * Four facts fall out of that, and all four are checkable in /lab:
 *
 *   1. every row of both matrices has exactly two ones, so every share inks exactly
 *      two of every four subcells everywhere. One sheet is uniform 50% noise and
 *      carries nothing.
 *   2. ANY TWO sheets are also uniform. The union of two rows is three subcells in
 *      both matrices, and under a random column permutation it is a uniformly random
 *      three-subset either way — identically distributed. Two of the three sheets
 *      tell you nothing about the pixel. This is the property the previous cut of
 *      this file did not have, and it is why the word cannot leak early.
 *   3. all three sheets separate perfectly: one clear subcell against none.
 *   4. share C is the only one the verdict touches. A and B are byte-identical pass
 *      or fail, so the deck gives nothing away before the third sheet lands.
 *
 * ── the readout ─────────────────────────────────────────────────────────────────
 *
 * One clear subcell in four is a 25% grey against black — true, but faint. So the
 * stack is read at MESSAGE resolution, which is the resolution the message was
 * written at in the first place: a message pixel is lit if ANY light gets through
 * its 2x2 block, dark if none does. That is `resolve()`, and it is the same
 * thresholding a human eye does to a physical transparency stack it cannot resolve
 * the subcells of — just done honestly and exactly instead of by squinting.
 *
 * It turns 25%-vs-0% into 100%-vs-0%. Solid word, solid ground, no dither anywhere.
 *
 * `resolve()` never looks at MASK. Hand it one sheet or two and every block has
 * light through it, so it returns a solid slab and no word — which is fact 2 above,
 * rendered. Hand it three that do not complete and it returns coin-flip speckle.
 *
 * ── what this is NOT ────────────────────────────────────────────────────────────
 *
 * The shares are not three independent functions of three independent digests. They
 * cannot be — no three hashes chosen by the world union to a word chosen by us. The
 * request digest drives the column permutation, the response digest the row
 * assignment, the model digest share C's fallback. A is free; B and C are the shares
 * that complete it. The honest claim is the one the panel makes: the word is
 * genuinely the union, and it only completes when the third share is the completing
 * one.
 */

export const MSG_ROWS = 13; // 11 for the face, one row of margin above and below
export const MSG_COLS = 52; // 5 glyphs x 8 wide + 4 gaps x 2 + 2 margin each side
export const BLK = 2; // 2x2 subcell expansion
export const ROWS = MSG_ROWS * BLK; // 26
export const COLS = MSG_COLS * BLK; // 104
export const N = ROWS * COLS;
export const M = MSG_ROWS * MSG_COLS;
export const PER = BLK * BLK; // 4 subcells
export const LIT = 2; // subcells each share inks, per block, always

/**
 * 8x11 face at message resolution, every stroke two message pixels thick. The
 * decode is binary, so the stroke no longer has to fight a noise floor — it is
 * this heavy because at 16x22 rendered cells a heavy stroke is simply easier to
 * read across a room, which is where this gets looked at.
 */
const GLYPHS: Record<string, string[]> = {
	V: [
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'.##..##.',
		'.##..##.',
		'..####..',
		'...##...'
	],
	A: [
		'..####..',
		'.##..##.',
		'##....##',
		'##....##',
		'##....##',
		'########',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##'
	],
	L: [
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'##......',
		'########'
	],
	I: [
		'########',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'...##...',
		'########'
	],
	D: [
		'######..',
		'##...##.',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##....##',
		'##...##.',
		'######..'
	]
};
const GW = 8;
const GK = 2;

export function stencil(word: string) {
	const mask = new Uint8Array(M);
	const gh = GLYPHS[word[0]].length;
	const x0 = Math.floor((MSG_COLS - (word.length * (GW + GK) - GK)) / 2);
	const y0 = Math.floor((MSG_ROWS - gh) / 2);
	for (let li = 0; li < word.length; li++) {
		const g = GLYPHS[word[li]];
		for (let r = 0; r < gh; r++) {
			for (let c = 0; c < GW; c++) {
				if (g[r][c] === '#') mask[(y0 + r) * MSG_COLS + x0 + li * (GW + GK) + c] = 1;
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
	for (let i = 0; i < k; i++) {
		const j = i + (next() % (a.length - i));
		const t = a[i];
		a[i] = a[j];
		a[j] = t;
	}
	return a.slice(0, k);
}

const COLUMNS = [0, 1, 2, 3];
const SLOTS = [0, 1, 2];

/**
 * The two base matrices, rows as index sets of the subcells that row INKS.
 * Rows of CLEAR union to three of four; rows of OPAQUE union to all four.
 */
const CLEAR: number[][] = [
	[2, 3],
	[1, 3],
	[1, 2]
];
const OPAQUE: number[][] = [
	[0, 1],
	[0, 2],
	[0, 3]
];

export type Polarity = 'solid' | 'cutout';

export type Shares = {
	/** levels per rendered subcell: 0 = uninked, 1..4 = ink level (texture only) */
	a: Uint8Array;
	b: Uint8Array;
	c: Uint8Array;
};

/**
 * Build the three shares. `pass` decides share C only.
 *
 * `polarity` picks which side of the stencil is the side light gets through:
 * 'solid' lights the letters against a solid ground, 'cutout' lights the ground
 * and leaves the letters as exact holes in it. Both decode to a hard binary
 * picture; 'solid' is the one that reads as a word.
 */
export function build(
	req: string,
	rsp: string,
	model: string,
	pass: boolean,
	polarity: Polarity = 'solid'
): Shares {
	const a = new Uint8Array(N);
	const b = new Uint8Array(N);
	const c = new Uint8Array(N);
	const nCol = stream(req, 1); // column permutation
	const nRow = stream(rsp, 2); // which share gets which row
	const nC = stream(model, 3); // share C's fallback when it does not complete
	const lA = stream(req, 17);
	const lB = stream(rsp, 18);
	const lC = stream(model, 19);

	const put = (buf: Uint8Array, mr: number, mc: number, set: number[], lvl: () => number) => {
		for (const k of set) {
			const r = mr * BLK + Math.floor(k / BLK);
			const cc = mc * BLK + (k % BLK);
			buf[r * COLS + cc] = 1 + (lvl() % 4);
		}
	};

	for (let mr = 0; mr < MSG_ROWS; mr++) {
		for (let mc = 0; mc < MSG_COLS; mc++) {
			const inWord = MASK[mr * MSG_COLS + mc] === 1;
			// the side light gets through
			const lit = polarity === 'solid' ? inWord : !inWord;
			const basis = lit ? CLEAR : OPAQUE;

			const perm = pick(COLUMNS, 4, nCol); // subcell perm(i) plays the part of i
			const slot = pick(SLOTS, 3, nRow); // share i is handed row slot[i]
			const row = (j: number) => basis[slot[j]].map((k) => perm[k]);

			const sa = row(0);
			const sb = row(1);
			// A non-completing C is drawn from the same distribution as a completing
			// one — two of the four, uniformly — so C on its own is indistinguishable
			// either way. What it loses is the correlation with A and B, which is the
			// only thing that was ever holding the word up.
			const sc = pass ? row(2) : pick(COLUMNS, LIT, nC);

			put(a, mr, mc, sa, lA);
			put(b, mr, mc, sb, lB);
			put(c, mr, mc, sc, lC);
		}
	}
	return { a, b, c };
}

/**
 * Read the stack at message resolution: a message pixel is lit if ANY of its four
 * subcells is left uninked by every sheet handed in, dark if all four are inked.
 *
 * Takes whichever sheets are actually on the table, which is what makes it a
 * decode rather than a lookup. One sheet or two and every block has light through
 * it, so this returns a solid slab. No MASK below this line.
 */
export function resolve(layers: Uint8Array[]): Uint8Array {
	const out = new Uint8Array(M);
	if (!layers.length) return out;
	for (let mr = 0; mr < MSG_ROWS; mr++) {
		for (let mc = 0; mc < MSG_COLS; mc++) {
			let clear = 0;
			for (let k = 0; k < PER; k++) {
				const i = (mr * BLK + Math.floor(k / BLK)) * COLS + mc * BLK + (k % BLK);
				if (!layers.some((l) => l[i])) clear++;
			}
			out[mr * MSG_COLS + mc] = clear > 0 ? 1 : 0;
		}
	}
	return out;
}

/** Measured, not asserted — /lab prints these so the scheme can be checked by eye. */
export function stats(s: Partial<Shares>) {
	const layers = [s.a, s.b, s.c].filter(Boolean) as Uint8Array[];
	const density = layers.map((l) => l.reduce((n, v) => n + (v ? 1 : 0), 0) / N);

	// raw subcell union, before the message-resolution read
	let rawL = 0,
		rawF = 0,
		nL = 0,
		nF = 0;
	for (let i = 0; i < N; i++) {
		const clear = !layers.some((l) => l[i]);
		const mr = Math.floor(i / COLS / BLK);
		const mc = Math.floor((i % COLS) / BLK);
		if (MASK[mr * MSG_COLS + mc]) {
			nL++;
			if (clear) rawL++;
		} else {
			nF++;
			if (clear) rawF++;
		}
	}

	// and after it — this is what actually gets drawn
	const dec = resolve(layers);
	let decL = 0,
		decF = 0,
		mL = 0,
		mF = 0;
	for (let i = 0; i < M; i++) {
		if (MASK[i]) {
			mL++;
			if (dec[i]) decL++;
		} else {
			mF++;
			if (dec[i]) decF++;
		}
	}

	return {
		density,
		raw: { letters: rawL / nL, field: rawF / nF },
		decoded: { letters: decL / mL, field: decF / mF },
		layers: layers.length
	};
}
