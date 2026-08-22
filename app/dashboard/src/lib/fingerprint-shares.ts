/**
 * Fingerprint shares — a (3,3) visual secret sharing scheme over the run's digests.
 *
 * The three fingerprint grids are not three pictures that get swapped for a fourth
 * at the end. They are three SHARES, and the word is what their union actually is.
 * Stacking them is the reveal; nothing downstream of `build()` knows the message.
 *
 * Construction, per message pixel, expanded into a 3x3 block of nine subcells:
 *
 *   share A   three of the nine, chosen by a stream seeded from the request digest
 *   share B   letter pixel -> the same three as A
 *             field  pixel -> three of the six A left, seeded from the response digest
 *   share C   pass -> whatever is still dark: A ∪ B ∪ C = all nine on field pixels,
 *                     and exactly A's three on letter pixels
 *             fail -> three drawn from the six A ∪ B already covers, so the union
 *                     is six everywhere and no shape survives
 *
 * The properties that make this worth the trouble:
 *
 *   - every share lights exactly three of every nine subcells, everywhere, so each
 *     grid on its own is uniform 33.3% noise and reveals nothing. That is a
 *     property of the construction, not a claim: check it in /lab.
 *   - on a pass the union is 33% inside the letters against 100% outside them.
 *   - on a fail it is ~67% both inside and outside — no contrast, no word.
 *   - A and B are identical either way. Only C differs, so nothing about the
 *     outcome is visible until the third share lands.
 *
 * WHAT THIS IS NOT: the shares are not three independent functions of three
 * independent digests. They cannot be — no three hashes chosen by the world union
 * to a word chosen by us. A is free; B and C are the shares that complete it. The
 * honest claim is the one the panel makes: the word is genuinely the union, and it
 * only completes when the third share is the completing one.
 */

export const MSG_ROWS = 11; // 9 for the face, one row of margin above and below
export const MSG_COLS = 42; // 5 glyphs x 6 wide + 4 gaps x 2 + 2 margin each side
export const BLK = 3; // 3x3 subcell expansion
export const ROWS = MSG_ROWS * BLK; // 33
export const COLS = MSG_COLS * BLK; // 126
export const N = ROWS * COLS;
export const PER = BLK * BLK; // 9 subcells
export const LIT = 3; // subcells each share lights, per block, always

/**
 * 6x9 face at message resolution, every stroke two message pixels thick — so six
 * rendered cells, which is what it takes to stay legible against a field that is
 * never quieter than 33% noise. A one-pixel stroke was tried first and vanished.
 */
const GLYPHS: Record<string, string[]> = {
	V: ['##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '.####.', '.####.', '..##..'],
	A: ['.####.', '##..##', '##..##', '##..##', '######', '##..##', '##..##', '##..##', '##..##'],
	L: ['##....', '##....', '##....', '##....', '##....', '##....', '##....', '##....', '######'],
	I: ['######', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..', '..##..', '######'],
	D: ['#####.', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '##..##', '#####.']
};
const GW = 6;
const GK = 2;

export function stencil(word: string) {
	const mask = new Uint8Array(MSG_ROWS * MSG_COLS);
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

/** Partial Fisher–Yates: k of pool, without replacement. */
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

const ALL = [0, 1, 2, 3, 4, 5, 6, 7, 8];
const not = (s: number[]) => ALL.filter((k) => !s.includes(k));

export type Shares = {
	/** levels per rendered cell: 0 = unlit, 1..4 = ink level */
	a: Uint8Array;
	b: Uint8Array;
	c: Uint8Array;
};

/**
 * Which side of the stencil is the sparse one.
 *
 *   'cutout'  the letters are the sparse blocks, so the FIELD is the fully-inked side.
 *             Read as ink this makes the ground the geometrically exact one — not a
 *             single stray bright cell in it — and the word comes through at 67%.
 *             That is the legible way round: a solid ground gives the letterforms a
 *             clean edge, and a 67% shape reads as a shape. Default.
 *   'solid'   the other way: exact letters on a 67% ground. Measures identically and
 *             reads worse, because the ground's own holes are the same colour as the
 *             letters and the eye cannot separate them.
 *
 * Three shares can never make a block sparser than 3 of 9, because 3 x 3 = 9 is
 * exactly what it takes to cover a block at all and every share must light the same
 * count everywhere. So one side of the stencil is always 33% rather than empty, and
 * 33% reads far better as a letter than as a hole in one.
 */
export type Polarity = 'solid' | 'cutout';

/**
 * Build the three shares. `pass` decides share C only — A and B are byte-identical
 * either way, which is why the deck gives nothing away before the verdict lands.
 */
export function build(
	req: string,
	rsp: string,
	model: string,
	pass: boolean,
	polarity: Polarity = 'cutout'
): Shares {
	const a = new Uint8Array(N);
	const b = new Uint8Array(N);
	const c = new Uint8Array(N);
	const nA = stream(req, 1);
	const nB = stream(rsp, 2);
	const nC = stream(model, 3);
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
			const sparse = polarity === 'cutout' ? inWord : !inWord;
			const sa = pick(ALL, LIT, nA);
			const sb = sparse ? sa.slice() : pick(not(sa), LIT, nB);
			let sc: number[];
			if (pass) {
				// whatever A and B have not covered — on a covered pixel that is exactly
				// the remaining three, on a sparse pixel it is A again
				sc = sparse ? sa.slice() : not(sa.concat(sb));
			} else {
				// drawn only from what A and B already cover, so C adds nothing new and
				// the union is six subcells whichever side of the stencil this pixel is
				sc = pick(sparse ? not(sa) : sa.concat(sb), LIT, nC);
			}
			put(a, mr, mc, sa, lA);
			put(b, mr, mc, sb, lB);
			put(c, mr, mc, sc, lC);
		}
	}
	return { a, b, c };
}

/** Measured, not asserted — /lab prints these so the scheme can be checked by eye. */
export function stats(s: Partial<Shares>) {
	const layers = [s.a, s.b, s.c].filter(Boolean) as Uint8Array[];
	const density = layers.map((l) => l.reduce((n, v) => n + (v ? 1 : 0), 0) / N);
	let litL = 0,
		nL = 0,
		litF = 0,
		nF = 0;
	for (let i = 0; i < N; i++) {
		const on = layers.some((l) => l[i] > 0);
		const mr = Math.floor(i / COLS / BLK);
		const mc = Math.floor((i % COLS) / BLK);
		if (MASK[mr * MSG_COLS + mc]) {
			nL++;
			if (on) litL++;
		} else {
			nF++;
			if (on) litF++;
		}
	}
	return { density, letters: litL / nL, field: litF / nF, layers: layers.length };
}
