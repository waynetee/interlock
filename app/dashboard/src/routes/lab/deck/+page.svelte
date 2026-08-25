<script lang="ts">
	/**
	 * /lab/deck — six hand cards, 85 × 64 mm, for narrating the demo.
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
	 * geometry: the same grid frame, the same corner ticks, the same header
	 * band. Each card fills only its own slot of that band (A · INPUT left,
	 * B · OUTPUT centre, C · MODEL right), so an aligned stack composes a single
	 * complete header instead of three labels mashed into mush -- and the frames
	 * land on each other exactly, which is how you SEE that the stack is
	 * aligned. Cards are pre-registered: corners flush = patterns seated.
	 *
	 * The defaults below are values captured off a real PASSing run (2026-08-25);
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
	let answer = $state('IAEA stands for International Atomic Energy Agency.');
	let ctin = $state(
		'2a8431cb3904b66911ec7a9c32efa61dfa6b68deb1a00749bc6fd3f8c7cd3404c286d5e70b9d54b96560597600f9cbf2ec75055e38f9742c'
	);
	let ctout = $state(
		'f3995d6c8e199913dd5f699abe7f145ea800054b42835ae6498aed110ad10f188d4d93f53e16a1050e6163a4'
	);
	let req = $state('60a2bf5fe1dcfd03cd18974f61282931cd9697aaa9b138a7de96ba34356de0e2');
	let rsp = $state('da0e9d728bbf39ac8fe703d55703cb8180ed93f7a442159f90dd1c2e771e65b4');
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
	const CW = 63;
	const CH = 94;
	const CR = 3;
	const PATW = 55;
	const P = $derived(PATW / grid.cols);
	const X0 = (CW - PATW) / 2;
	const Y0 = 44;
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
		for (let i = 0; i < lines; i++) out.push(s.slice(i * per, (i + 1) * per));
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

{#snippet ticks(ink: string)}
	<!-- corner registration ticks on the grid frame: identical on every
	     fingerprint card, so an aligned stack draws ONE crisp mark -->
	{#each [
		[X0 - 0.8, Y0 - 0.8, 1, 0, 0, 1],
		[X0 + PATW + 0.8, Y0 - 0.8, -1, 0, 0, 1],
		[X0 - 0.8, Y0 + PILE * P + 0.8, 1, 0, 0, -1],
		[X0 + PATW + 0.8, Y0 + PILE * P + 0.8, -1, 0, 0, -1]
	] as [x, y, dx, , , dy] (x + ':' + y)}
		<path
			d="M {x + dx * 3} {y} L {x} {y} L {x} {y + dy * 3}"
			fill="none"
			stroke={ink}
			stroke-width="0.4"
		/>
	{/each}
{/snippet}

{#snippet slot(i: number, role: string, digest: string, ink: string)}
	<text x={SLOT[i].x} y="8" text-anchor={SLOT[i].anchor} class="t-name" fill={ink}>{role}</text>
	<text x={SLOT[i].x} y="11.6" text-anchor={SLOT[i].anchor} class="t-hex" fill={ink}
		>{digest}</text
	>
{/snippet}

{#snippet film(cells: Uint8Array, height: number, drop: number, ink: string)}
	<!-- grid frame at the shared position; edge-to-edge cells at this strip's
	     registered drop, so flush corners mean seated patterns -->
	<rect
		x={X0 - 0.8}
		y={Y0 - 0.8}
		width={PATW + 1.6}
		height={PILE * P + 1.6}
		fill="none"
		stroke={ink}
		stroke-width="0.3"
	/>
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

{#snippet msgFront(label: string, big: string)}
	<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
		{@render outline()}
		<rect x="0.3" y="0.3" width={CW - 0.6} height={CH - 0.6} rx={CR} fill="#fff" />
		{@render outline()}
		<text x="6" y="12" class="t-eyebrow">{label}</text>
		<line x1="6" y1="15.5" x2={CW - 6} y2="15.5" stroke="#000" stroke-width="0.3" />
		{#each wrap(big, 14) as line, i (i)}
			<text x="6" y={30 + i * 8.6} class="t-big">{line}</text>
		{/each}
	</svg>
{/snippet}

{#snippet msgBack(label: string, hex: string)}
	<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
		{@render outline()}
		<rect x="0.3" y="0.3" width={CW - 0.6} height={CH - 0.6} rx={CR} fill="#fff" />
		{@render outline()}
		<text x="6" y="12" class="t-eyebrow">{label} · ENCRYPTED</text>
		<!-- closed padlock -->
		<g transform="translate({CW - 9.5},6.5)" fill="none" stroke="#000" stroke-width="0.7">
			<rect x="0" y="3.4" width="6" height="4.6" rx="0.6" />
			<path d="M 1.4 3.4 V 2 a 1.6 1.6 0 0 1 3.2 0 v 1.4" />
		</g>
		<line x1="6" y1="15.5" x2={CW - 6} y2="15.5" stroke="#000" stroke-width="0.3" />
		{#each hexBig(hex) as row, i (i)}
			<text x="6" y={30 + i * 8.6} class="t-ct">{row}</text>
		{/each}
	</svg>
{/snippet}

<div class="page">
	<section class="cover">
		<h1>The hand deck</h1>
		<p>
			Six cards, 63 × 94 mm, that tell the run in the audience's hands. The two message cards are
			double-sided: the words on the face, and on the flip the <em>actual ciphertext bytes</em> that
			crossed the cable for this exchange — the only form the datacenter's wire ever saw them in.
			The fingerprint cards stack: lay the two green films on the solid model card, corners flush,
			and the ground closes everywhere except the word — <strong>{word}</strong> reads out in white.
			Then swap the green OUTPUT film for the red one (an answer the certifier never fingerprinted):
			the ground never closes, no word comes, and the red shows exactly where the lie sits.
		</p>
		<h2>Print</h2>
		<ul>
			<li><strong>Page 2</strong> — message card faces: white cardstock.</li>
			<li>
				<strong>Page 3</strong> — message card flip sides: print as the REVERSE of page 2 (duplex,
				flip on long edge), or print single-sided and glue back-to-back. The cards sit in one
				centred column so a long-edge flip lands each back on its own face.
			</li>
			<li><strong>Page 4</strong> — INPUT + OUTPUT fingerprints: transparency film, 100% scale.</li>
			<li><strong>Page 5</strong> — MODEL fingerprint: white cardstock (it is the backing).</li>
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
			<p class="sheetnote">page 2 · message card faces · white cardstock</p>
			{@render msgFront('REQUEST', q)}
			{@render msgFront('RESPONSE', answer)}
		</section>

		<section class="sheet">
			<p class="sheetnote">
				page 3 · flip sides · duplex reverse of page 2 (long edge), or glue back-to-back
			</p>
			{@render msgBack('REQUEST', ctin)}
			{@render msgBack('RESPONSE', ctout)}
		</section>

		<section class="sheet">
			<p class="sheetnote">page 4 · input + output fingerprints · transparency film · 100% scale</p>
			<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
				{@render outline()}
				{@render slot(0, ROLES[0], short(digests[0]), INK.A)}
				{@render ticks(INK.A)}
				{@render film(st.cells[0], st.heights[0], HOME[0], INK.A)}
			</svg>
			<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
				{@render outline()}
				{@render slot(1, ROLES[1], short(digests[1]), INK.B)}
				{@render ticks(INK.B)}
				{@render film(st.cells[1], st.heights[1], HOME[1], INK.B)}
			</svg>
		</section>

		<section class="sheet">
			<p class="sheetnote">page 5 · model fingerprint · white cardstock — the backing</p>
			<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
				{@render outline()}
				<rect x="0.3" y="0.3" width={CW - 0.6} height={CH - 0.6} rx={CR} fill="#fff" />
				{@render outline()}
				{@render slot(2, ROLES[2], short(digests[2]), INK.C)}
				{@render ticks(INK.C)}
				{@render film(st.cells[2], st.heights[2], HOME[2], INK.C)}
			</svg>
		</section>

		<section class="sheet">
			<p class="sheetnote">page 6 · the impostor · transparency film · 100% scale</p>
			<svg class="card" width="{CW}mm" height="{CH}mm" viewBox="0 0 {CW} {CH}">
				{@render outline()}
				{@render slot(1, ROLES[1], xDigest, INK.X)}
				{@render ticks(INK.X)}
				{@render film(xCells, st.heights[1], HOME[1], INK.X)}
			</svg>
		</section>
	{/if}
</div>

<style>
	@page {
		size: A4 portrait;
		margin: 12mm;
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
		gap: 7mm;
		align-items: center;
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
		font-size: 2.8px;
		font-weight: 700;
		letter-spacing: 0.3px;
	}
	.t-hex {
		font-size: 2.2px;
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
