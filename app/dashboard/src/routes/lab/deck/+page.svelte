<script lang="ts">
	/**
	 * /lab/deck — six hand cards, 94 × 63 mm landscape, for narrating the demo.
	 *
	 * Two message cards (double-sided: plaintext on the face, the run's REAL
	 * ciphertext on the flip), three fingerprint cards in three greens, and one
	 * red impostor. The fingerprint cards use the same share optics as
	 * /lab/print: each inks its own share of the ground and none of the word, so
	 * films stacked on the solid model card close the ground and the word reads
	 * out in white. Swap the green OUTPUT film for the red scrambled one — the
	 * datacenter claiming an answer the certifier never saw — and the ground
	 * never closes: no word, and red where the lie sits.
	 *
	 * STACKING IS THE DESIGN CONSTRAINT. All four fingerprint cards share one
	 * geometry: the same grid position and the same header band. Each card fills
	 * only its own slot of that band (INPUT left, OUTPUT centre, MODEL right),
	 * so an aligned stack composes a single complete header instead of three
	 * labels mashed into mush. Cards are pre-registered: corners flush =
	 * patterns seated -- the card edges themselves are the registration.
	 *
	 * The defaults below are values captured off a real PASSing run with the few-shot prompt (2026-08-25);
	 * override any of them with query parameters (q, answer, ctin, ctout, req,
	 * rsp, model, text for the word).
	 */
	import {
		build,
		homes,
		stencil,
		strips,
		DEFAULT_FACE,
		DEFAULT_GRID,
		DEFAULT_WORD
	} from '$lib/fingerprint-shares';
	import { onMount } from 'svelte';

	// ── the run on the cards (a real one; params override) ─────────────────────
	let q = $state('What does IAEA stand for?');
	let answer = $state('International Atomic Energy Agency');
	let ctin = $state(
		'ba98330dd9a87875aa050d51b9c32e37065e2e286dcb9fc8ec20b3b8dbb4dcff424574bad386ab29e619b184e2fec7c93e9da4965b9483be7f99af614d7d9e7d693611b26871089e200449953e70b2e2de8ab193b8ad669551056696516aefb1f6e1a1abe3e80cb802956c68f10fa312'
	);
	let ctout = $state(
		'7d1bf2757998a67262771478da0c47d8fcfaadc2'
	);
	let req = $state('a9368f47e724515062810b54c7b1c19c2c797aad57b61c678831193d7407a50a');
	let rsp = $state('9ddad76a4dd8226a729e9942652142380b80bbe64d506377466ad8396ddd12f9');
	let model = $state('6e6001da2106d4757498752a021df6c2bdc332c650aae4bae6b0c004dcf14933');
	let text = $state(DEFAULT_WORD);
	let ready = $state(false);

	// ── the shares ─────────────────────────────────────────────────────────────
	const word = $derived(text.toUpperCase());
	const grid = DEFAULT_GRID;
	const mask = $derived(stencil(word, DEFAULT_FACE, grid));
	const shares = $derived(build(req, rsp, model, true, mask));
	const SLACK = 2;
	const st = $derived(strips(shares, grid, SLACK, model, 0.5));
	/** registered drop per strip; the cards are printed pre-seated at these */
	const HOME = $derived(homes(st));

	// ── card geometry, mm ──────────────────────────────────────────────────────
	const CW = 94;
	const CH = 63;
	const CR = 0;
	const PATW = 86;
	const P = $derived(PATW / grid.cols);
	const X0 = (CW - PATW) / 2;
	const Y0 = 26;
	const PILE = $derived(grid.rows + 2 * SLACK);

	// Three greens with real distance between them: films read apart in the
	// hand, overlaps darken toward the backing, and the word stays the one
	// white thing. Red is reserved for the impostor.
	const INK = { A: '#5ea44b', B: '#2e7d43', C: '#14532d', X: '#c62828' };
	const ROLES = ['INPUT', 'OUTPUT', 'MODEL'];
	/** header slots: left / centre / right, identical on every card */
	const SLOT = [
		{ x: 4, anchor: 'start' },
		{ x: CW / 2, anchor: 'middle' },
		{ x: CW - 4, anchor: 'end' }
	];
	const digests = $derived([req, rsp, model]);
	const short = (h: string) => '0x' + h.slice(0, 8).toUpperCase();

	// ── the impostor ───────────────────────────────────────────────────────────
	/** deterministic scramble: B's geometry, nobody's share */
	function scrambleCells(n: number, density = 0.34, seed = 0x7a3b91) {
		let s = seed >>> 0;
		const cells = new Uint8Array(n);
		for (let i = 0; i < n; i++) {
			s ^= s << 13;
			s >>>= 0;
			s ^= s >> 17;
			s ^= s << 5;
			s >>>= 0;
			cells[i] = s % 1000 < density * 1000 ? 1 + (s % 4) : 0;
		}
		return cells;
	}
	const xCells = $derived(scrambleCells(st.heights[1] * grid.cols));
	const xDigest = $derived(
		'0x' + rsp.slice(0, 8).split('').reverse().join('').toUpperCase()
	);

	// ── text layout helpers ────────────────────────────────────────────────────
	function wrap(s: string, max: number) {
		const out: string[] = [];
		let line = '';
		for (const w of s.split(/\s+/)) {
			if (line && (line + ' ' + w).length > max) {
				out.push(line);
				line = w;
			} else line = line ? line + ' ' + w : w;
		}
		if (line) out.push(line);
		return out;
	}
	/**
	 * The flip side's hex, illustrative rather than exhaustive: big chunky lines
	 * off the front of the real ciphertext, ending in an ellipsis. The full
	 * bytes are on the wire and in the transcript; the card's job is to LOOK
	 * like ciphertext from across a table.
	 */
	function hexBig(h: string, lines = 6, per = 12) {
		const s = '0x' + h.toUpperCase();
		const out: string[] = [];
		for (let i = 0; i < lines && i * per < s.length; i++)
			out.push(s.slice(i * per, (i + 1) * per));
		// an ellipsis only where there really is more: a short ciphertext is
		// shown whole, and a lone '…' line is nobody's idea of bytes
		if (s.length > lines * per)
			out[out.length - 1] = out[out.length - 1].slice(0, per - 1) + '…';
		return out;
	}

	onMount(() => {
		const p = new URLSearchParams(location.search);
		for (const [k, set] of [
			['q', (v: string) => (q = v)],
			['answer', (v: string) => (answer = v)],
			['ctin', (v: string) => (ctin = v)],
			['ctout', (v: string) => (ctout = v)],
			['req', (v: string) => (req = v)],
			['rsp', (v: string) => (rsp = v)],
			['model', (v: string) => (model = v)],
			['text', (v: string) => (text = v)]
		] as [string, (v: string) => void][]) {
			const v = p.get(k);
			if (v !== null) set(v);
		}
		ready = true;
	});
</script>

<svelte:head><title>Interlock hand deck</title></svelte:head>

{#snippet paper(base: string, id: string, dot: string)}
	<!-- SVG fills, not CSS backgrounds, so the stock prints even with
	     "background graphics" off: a soft paper tone under a fine dot grain -->
	<defs>
		<pattern id={id} width="3.5" height="3.5" patternUnits="userSpaceOnUse">
			<circle cx="1.75" cy="1.75" r="0.17" fill={dot} />
		</pattern>
	</defs>
	<rect x="0.3" y="0.3" width={CW - 0.6} height={CH - 0.6} rx={CR} fill={base} />
	<rect x="0.3" y="0.3" width={CW - 0.6} height={CH - 0.6} rx={CR} fill="url(#{id})" />
{/snippet}

{#snippet outline()}
	<rect
		x="0.1"
		y="0.1"
		width={CW - 0.2}
		height={CH - 0.2}
		rx={CR}
		fill="none"
		stroke="#999"
		stroke-width="0.2"
		stroke-dasharray="1.4 1"
	/>
{/snippet}

{#snippet slot(i: number, role: string, digest: string, ink: string)}
	<text x={SLOT[i].x} y="10" text-anchor={SLOT[i].anchor} class="t-name" fill={ink}>{role}</text>
	<text x={SLOT[i].x} y="15.6" text-anchor={SLOT[i].anchor} class="t-hex" fill={ink}
		>{digest}</text
	>
{/snippet}

{#snippet film(cells: Uint8Array, height: number, drop: number, ink: string)}
	<!-- nothing around the grid: the cards are printed pre-seated, so the card
	     edges themselves are the registration -->
	<g transform="translate({X0},{Y0 + drop * P})">
		{#each { length: height } as _r, r (r)}
			{#each { length: grid.cols } as _c, c (c)}
				{#if cells[r * grid.cols + c] > 0}
					<rect x={c * P} y={r * P} width={P + 0.02} height={P + 0.02} fill={ink} />
				{/if}
			{/each}
		{/each}
	</g>
{/snippet}

{#snippet fpCard(
	slotIdx: number,
	role: string,
	digest: string,
	ink: string,
	cells: Uint8Array,
	height: number,
	drop: number,
	opaque: boolean
)}
	<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
		{#if opaque}
			{@render paper('#f6f3ec', 'stock-paper', 'rgba(24,24,24,0.055)')}
		{/if}
		{@render outline()}
		{@render slot(slotIdx, role, digest, ink)}
		{@render film(cells, height, drop, ink)}
	</svg>
{/snippet}

{#snippet msgFront(label: string, big: string)}
	<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
		{@render paper('#f6f3ec', 'stock-paper', 'rgba(24,24,24,0.055)')}
		{@render outline()}
		<text x="6" y="12" class="t-eyebrow">{label}</text>
		<line x1="6" y1="15.5" x2={CW - 6} y2="15.5" stroke="#000" stroke-width="0.3" />
		{#each wrap(big, 22) as line, i (i)}
			<text x="6" y={30 + i * 8.6} class="t-big">{line}</text>
		{/each}
	</svg>
{/snippet}

{#snippet msgBack(label: string, hex: string)}
	<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
		{@render paper('#f6f3ec', 'stock-paper', 'rgba(24,24,24,0.055)')}
		{@render outline()}
		<text x="6" y="12" class="t-eyebrow">{label} · ENCRYPTED</text>
		<!-- closed padlock: sized to the header band, sitting on its rule -->
		<g
			transform="translate({CW - 15},4.6)"
			fill="none"
			stroke="#000"
			stroke-width="0.85"
			stroke-linecap="round"
		>
			<rect x="0" y="4.6" width="9" height="6.3" rx="0.9" />
			<path d="M 2.1 4.6 V 2.8 a 2.4 2.4 0 0 1 4.8 0 v 1.8" />
		</g>
		<line x1="6" y1="15.5" x2={CW - 6} y2="15.5" stroke="#000" stroke-width="0.3" />
		{#each hexBig(hex, 4, 16) as row, i (i)}
			<text x="6" y={30 + i * 8.6} class="t-ct">{row}</text>
		{/each}
	</svg>
{/snippet}

<div class="page">
	<section class="cover">
		<h1>The hand deck</h1>
		<p>
			Six cards, 94 × 63 mm landscape, printed two-up — one print run yields two decks — that tell the run in the audience's hands. The two message cards are
			double-sided: the words on the face, and on the flip the <em>actual ciphertext bytes</em> that
			crossed the cable for this exchange — the only form the datacenter's wire ever saw them in.
			The fingerprint cards stack: lay the two green films on the solid model card, corners flush,
			and the ground closes everywhere except the word — <strong>{word}</strong> reads out in white.
			Then swap the green OUTPUT film for the red one (an answer the certifier never fingerprinted):
			the ground never closes, no word comes, and the red shows exactly where the lie sits.
		</p>
		<h2>Print</h2>
		<ul>
			<li><strong>Page 2</strong> — message card faces: cardstock.</li>
			<li>
				<strong>Page 3</strong> — message card flip sides: print as the REVERSE of page 2 (duplex,
				flip on long edge), or print single-sided and glue back-to-back. The cards sit in one
				centred column so a long-edge flip lands each back on its own face.
			</li>
			<li><strong>Page 4</strong> — INPUT + OUTPUT fingerprints: transparency film, 100% scale.</li>
			<li><strong>Page 5</strong> — MODEL fingerprint: cardstock (it is the backing).</li>
			<li><strong>Page 6</strong> — the red impostor: transparency film, 100% scale.</li>
		</ul>
		<p class="fine">
			Never “fit to page” — it changes the cell pitch between sheets and the films stop
			registering. Cut on the dashed lines; a guillotine keeps edges square, and square edges are
			the registration: the cards are printed pre-seated, so corners flush = patterns aligned,
			and the corner ticks on the grid frame stack into a single crisp mark when you have it
			right.
		</p>
		<dl>
			<div><dt>question</dt><dd>{q}</dd></div>
			<div><dt>answer</dt><dd>{answer}</dd></div>
			<div><dt>word</dt><dd>{word} · {grid.rows} × {grid.cols} cells at {P.toFixed(2)} mm</dd></div>
			<div><dt>digests</dt><dd>IN {short(req)} · OUT {short(rsp)} · MODEL {short(model)}</dd></div>
		</dl>
	</section>

	{#if ready}
		<section class="sheet">
			<p class="sheetnote">page 2 · message card faces · cardstock</p>
			<div class="pair">{@render msgFront('REQUEST', q)}{@render msgFront('REQUEST', q)}</div>
			<div class="pair">{@render msgFront('RESPONSE', answer)}{@render msgFront('RESPONSE', answer)}</div>
		</section>

		<section class="sheet">
			<p class="sheetnote">
				page 3 · flip sides · duplex reverse of page 2 (long edge), or glue back-to-back
			</p>
			<div class="pair">{@render msgBack('REQUEST', ctin)}{@render msgBack('REQUEST', ctin)}</div>
			<div class="pair">{@render msgBack('RESPONSE', ctout)}{@render msgBack('RESPONSE', ctout)}</div>
		</section>

		<section class="sheet">
			<p class="sheetnote">page 4 · input + output fingerprints · transparency film · 100% scale</p>
			<div class="pair">
				{@render fpCard(0, ROLES[0], short(digests[0]), INK.A, st.cells[0], st.heights[0], HOME[0], false)}
				{@render fpCard(0, ROLES[0], short(digests[0]), INK.A, st.cells[0], st.heights[0], HOME[0], false)}
			</div>
			<div class="pair">
				{@render fpCard(1, ROLES[1], short(digests[1]), INK.B, st.cells[1], st.heights[1], HOME[1], false)}
				{@render fpCard(1, ROLES[1], short(digests[1]), INK.B, st.cells[1], st.heights[1], HOME[1], false)}
			</div>
		</section>

		<section class="sheet">
			<p class="sheetnote">page 5 · model fingerprint · cardstock — the backing</p>
			<div class="pair">
				{@render fpCard(2, ROLES[2], short(digests[2]), INK.C, st.cells[2], st.heights[2], HOME[2], true)}
				{@render fpCard(2, ROLES[2], short(digests[2]), INK.C, st.cells[2], st.heights[2], HOME[2], true)}
			</div>
		</section>

		<section class="sheet">
			<p class="sheetnote">page 6 · the impostor · transparency film · 100% scale</p>
			<div class="pair">
				{@render fpCard(1, ROLES[1], xDigest, INK.X, xCells, st.heights[1], HOME[1], false)}
				{@render fpCard(1, ROLES[1], xDigest, INK.X, xCells, st.heights[1], HOME[1], false)}
			</div>
		</section>
	{/if}
</div>

<style>
	@page {
		size: A4 portrait;
		margin: 10mm 8mm;
	}
	/* the app's theme paints the body graphite; this route is a paper document */
	:global(body) {
		background: #fff;
	}
	.page {
		background: #fff;
		color: #000;
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	section {
		break-after: page;
		padding: 5mm 0;
	}
	section:last-child {
		break-after: auto;
	}
	h1 {
		font-size: 20pt;
		letter-spacing: 0.06em;
		margin: 0 0 6mm;
	}
	h2 {
		font-size: 11pt;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		margin: 6mm 0 2mm;
	}
	p,
	ul {
		max-width: 150mm;
		font-size: 10pt;
		line-height: 1.6;
		margin: 0 0 4mm;
	}
	ul {
		padding-left: 5mm;
	}
	li {
		margin-bottom: 1.5mm;
	}
	.fine {
		font-size: 8.5pt;
		color: #444;
	}
	dl {
		display: grid;
		gap: 1.5mm;
		margin: 6mm 0;
		font-size: 9pt;
	}
	dl div {
		display: flex;
		gap: 4mm;
	}
	dt {
		width: 24mm;
		color: #555;
		text-transform: uppercase;
		letter-spacing: 0.12em;
		flex-shrink: 0;
	}
	dd {
		margin: 0;
		font-weight: 600;
		overflow-wrap: anywhere;
	}
	.sheet {
		display: flex;
		flex-direction: column;
		gap: 6mm;
		align-items: flex-start;
	}
	/* two copies of each card, side by side: one print run yields two decks.
	   The columns are identical, so the duplex flip still lands every back on
	   a front of the same card. */
	.pair {
		display: flex;
		gap: 2mm;
	}
	.sheetnote {
		font-size: 8pt;
		color: #555;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		margin: 0;
		align-self: flex-start;
	}
	.card {
		display: block;
	}
	.card text {
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	.t-eyebrow {
		font-size: 3.2px;
		letter-spacing: 0.35px;
		font-weight: 700;
	}
	.t-big {
		font-size: 5.6px;
		font-weight: 700;
		letter-spacing: 0.05px;
	}
	.t-ct {
		font-size: 5.6px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}
	.t-name {
		font-size: 4.6px;
		font-weight: 700;
		letter-spacing: 0.5px;
	}
	.t-hex {
		font-size: 3.8px;
		font-weight: 600;
	}
	@media screen {
		.page {
			max-width: 210mm;
			margin: 0 auto;
			padding: 10mm;
		}
		section {
			border-bottom: 1px dashed #bbb;
		}
		.card {
			box-shadow: 0 1px 6px rgba(0, 0, 0, 0.18);
		}
	}
</style>
