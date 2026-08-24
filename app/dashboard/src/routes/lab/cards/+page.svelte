<script lang="ts">
	/**
	 * /lab/cards — the three films as a credit-card deck.
	 *
	 * Same optics as /lab/print (ink is opaque, the three films ink every cell of
	 * the ground and none of the word, so the word glows through the stack), cut
	 * down to CR80 — 85.6 × 54.0 mm, the size of every card in your wallet — so
	 * the deck can be carried, dealt onto a table, and stacked by hand.
	 *
	 * REGISTRATION BY PUNCH HOLE. On the A4 films you find the alignment by
	 * sliding until the word appears. At card size that stays the fun part, but a
	 * card wants to LOCK once found, so each card carries two punch marks whose
	 * height encodes that card's own registration offset: punch them out, slide
	 * the cards until the three pairs of holes line up, and the patterns are
	 * seated — push a screw post or peg through and the stack cannot drift. The
	 * holes sit in the clear margin above the pattern, so they cost no ink and
	 * hide nothing.
	 *
	 * EVERYTHING PRINTED SHOWS IN THE STACK — the films are clear, so three
	 * labels laid at the same spot would pile into mush. Each card writes its
	 * label and footer in its own third of the card face, so the assembled deck
	 * reads A · B · C side by side through its own front.
	 *
	 * ORIENTATION. A transparency flipped over is a mirrored pattern that will
	 * never register. Every card carries an INK UP arrow; if the arrow reads
	 * backwards, the film is upside down.
	 *
	 * Same query parameters as /lab/print (req, rsp, model, word, size, weight,
	 * cols, rows, slack, split), so the deck can be printed for any run's
	 * digests.
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

	const NAMES = ['A', 'B', 'C'];
	const ROLES = ['THE QUESTION', 'THE ANSWER', 'THE MODEL'];
	const SUBS = ['fingerprinted going in', 'fingerprinted coming out', 'fixed in advance'];
	const SLACK = 2;
	const SPLIT = 0.5;

	let text = $state(DEFAULT_WORD);
	let size = $state(DEFAULT_FACE.size);
	let weight = $state(DEFAULT_FACE.weight);
	let cols = $state(DEFAULT_GRID.cols);
	let rows = $state(DEFAULT_GRID.rows);
	let slack = $state(SLACK);
	let split = $state(SPLIT * 100);
	let req = $state('4f74f5c6b3a19e02d81c7745aa30bb61c4e9f0d2');
	let rsp = $state('a1b93de77c04582fe61099ab3d5c77e0114fa2b8');
	let model = $state('6e6001da2106d4757498752a021df6c2bdc332c6');
	let ready = $state(false);

	const grid = $derived({ rows, cols });
	const word = $derived(text.toUpperCase());
	const mask = $derived(stencil(word, { size, weight }, grid));
	const shares = $derived(build(req, rsp, model, true, mask));
	const st = $derived(strips(shares, grid, slack, model, split / 100));
	/**
	 * The registered DROP of each film in the pile -- homes(), not st.offsets:
	 * offsets is where the word band sits INSIDE each strip's own cells, and the
	 * printed pattern already carries that. What a hand has to reproduce is the
	 * drop.
	 */
	const HOME = $derived(homes(st));
	const digests = $derived([req, rsp, model]);

	// ── card geometry, all in mm ───────────────────────────────────────────────
	// CR80: the ISO/IEC 7810 ID-1 card, 85.60 × 53.98, corner radius 3.18.
	const CW = 85.6;
	const CH = 54;
	const CR = 3.18;
	/** the pattern is width-limited: the full pile has to sit inside the card */
	const PATW = 76;
	const P = $derived(PATW / cols);
	const X0 = $derived((CW - PATW) / 2);
	/** pattern window top: below the label zone and the punch band */
	const Y0 = 24;
	const PILE = $derived(rows + 2 * slack);
	/**
	 * Punch centres. Fixed in the REGISTERED frame (3.5 mm above the pile top),
	 * so each card prints its marks at that height MINUS its own registration
	 * drop — line the punched holes up and the drops are dialled in exactly.
	 */
	const HX = [8, CW - 8];
	const holeY = (i: number) => Y0 - 3.5 - HOME[i] * P;
	/** each card's text lane, so the stacked labels read side by side */
	const LANE = [5, 32.5, 58];

	onMount(() => {
		const q = new URLSearchParams(location.search);
		const num = (k: string, set: (v: number) => void) => {
			const v = Number(q.get(k));
			if (q.get(k) !== null && Number.isFinite(v) && v) set(v);
		};
		num('size', (v) => (size = v));
		num('weight', (v) => (weight = v));
		num('cols', (v) => (cols = v));
		num('rows', (v) => (rows = v));
		num('slack', (v) => (slack = v));
		if (q.get('split') !== null) split = Number(q.get('split'));
		for (const [k, set] of [
			['text', (v: string) => (text = v)],
			['req', (v: string) => (req = v)],
			['rsp', (v: string) => (rsp = v)],
			['model', (v: string) => (model = v)]
		] as [string, (v: string) => void][]) {
			const v = q.get(k);
			if (v !== null) set(v);
		}
		ready = true;
	});
</script>

<svelte:head><title>Fingerprint deck</title></svelte:head>

{#snippet cardframe()}
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

{#snippet punch(x: number, y: number)}
	<!-- a 6 mm circle for a standard ¼" punch, with a crosshair to centre it -->
	<circle cx={x} cy={y} r="3" fill="none" stroke="#000" stroke-width="0.25" />
	<line x1={x - 1.2} y1={y} x2={x + 1.2} y2={y} stroke="#000" stroke-width="0.15" />
	<line x1={x} y1={y - 1.2} x2={x} y2={y + 1.2} stroke="#000" stroke-width="0.15" />
{/snippet}

<div class="page">
	<section class="cover">
		<h1>The fingerprint deck</h1>
		<p>
			Three transparent cards, credit-card size. Card A is the certifier's fingerprint of the
			question, B its fingerprint of the answer, C the commitment to the model weights. Each is
			opaque where it is inked, and between them the three ink every cell of the ground and not one
			cell of the word — hold the registered stack against light and <strong>{word}</strong> glows
			through. Slide any card and the word drowns; swap in a card from a different run and it never
			appears at all. That is the proof, in your hands.
		</p>
		<h2>Print</h2>
		<p>
			Page 2 goes on <strong>one transparency sheet at 100% scale</strong> — never “fit to page”,
			which changes the cell pitch and stops the films registering. Laser toner is the most opaque
			ink; on inkjet, use the transparency media setting and let it dry. Page 3 goes on white
			cardstock: it is the backer that sits behind the stack so the word reads without a lamp.
		</p>
		<h2>Cut, punch, stack</h2>
		<p>
			Cut on the dashed outlines (a guillotine keeps the edges parallel; a corner punch rounds them
			to the real CR80 radius). Punch out the two marked circles on each card with a ¼" (6 mm)
			punch — the marks sit at a different height on each card <em>on purpose</em>: each pair is
			printed at that card's own registration offset. Stack the films ink-side up (the ▲ tells
			you), slide them until the word appears — then check yourself: all six holes line up exactly
			when the patterns are seated. Push a screw post, peg or binder ring through to lock the
			deck; the card edges will sit a few millimetres staggered, and that stagger IS the
			registration, on display.
		</p>
		<h2>Materials that stack well</h2>
		<ul>
			<li>
				<strong>Film:</strong> 100 µm laser/copier OHP transparency film (PET). Toner is dense
				enough in one pass; pigment-ink inkjet film wants two passes for a truly opaque ground.
			</li>
			<li>
				<strong>Stiffness:</strong> mount each film on a clear 0.76 mm PVC card blank (sold as
				“CR80 clear cards”) with clear double-sided tape under the label strip only — never over
				the pattern. Or skip blanks and sleeve the finished stack in a rigid trading-card
				toploader.
			</li>
			<li>
				<strong>Fasteners:</strong> 6 mm aluminium screw posts (“Chicago screws”) through the
				punched holes — loose to slide, tightened to lock. A small binder ring works and lets the
				deck fan out.
			</li>
			<li>
				<strong>Light:</strong> the cardstock backer from page 3, a phone torch, or — the nice
				version — a frosted 2 mm acrylic card cut to CR80 as a diffuser at the back of the stack.
			</li>
			<li>
				<strong>Tools:</strong> guillotine or craft knife + steel rule, ¼" hole punch, corner
				rounder punch (R3 or R3.5).
			</li>
		</ul>
		<dl>
			<div><dt>word</dt><dd>{word}</dd></div>
			<div><dt>picture</dt><dd>{rows} × {cols} cells at {P.toFixed(2)} mm</dd></div>
			<div><dt>films</dt><dd>A {st.heights[0]} · B {st.heights[1]} · C {st.heights[2]} rows</dd></div>
			<div><dt>pile</dt><dd>{PILE} × {cols} cells</dd></div>
			<div><dt>registration</dt><dd class="spoiler">drops {HOME.join(' · ')}</dd></div>
		</dl>
		<p class="fine">
			The registration offsets are printed above, and encoded in the punch marks, because a demo
			that cannot be reset is not much of a demo. They are not a secret in any useful sense:
			{(slack + 1) ** 3} slides is nothing to search.
		</p>
	</section>

	{#if ready}
		<section class="sheet">
			<p class="sheetnote">
				page 2 · print on ONE transparency sheet · 100% scale · cut on the dashed lines
			</p>
			{#each NAMES as n, i (n)}
				<svg
					class="card"
					width="{CW}mm"
					height="{CH}mm"
					viewBox="0 0 {CW} {CH}"
					xmlns="http://www.w3.org/2000/svg"
				>
					{@render cardframe()}
					<!-- label, in this card's own lane so the stack reads A · B · C -->
					<text x={LANE[i]} y="7" class="t-badge">{n}</text>
					<text x={LANE[i] + 5} y="7" class="t-role">{ROLES[i]}</text>
					<text x={LANE[i]} y="10.4" class="t-digest">0x{digests[i].slice(0, 12).toUpperCase()}</text>
					<text x={LANE[i]} y="12.8" class="t-sub">{SUBS[i]}</text>
					<!-- registration punches: height encodes this card's own offset -->
					{@render punch(HX[0], holeY(i))}
					{@render punch(HX[1], holeY(i))}
					<!-- the film itself: edge-to-edge ink, gaps transmit and would leak light -->
					<g transform="translate({X0},{Y0})">
						{#each { length: st.heights[i] } as _r, r (r)}
							{#each { length: cols } as _c, c (c)}
								{#if st.cells[i][r * cols + c] > 0}
									<rect x={c * P} y={r * P} width={P + 0.03} height={P + 0.03} fill="#000" />
								{/if}
							{/each}
						{/each}
					</g>
					<!-- orientation: a flipped film is a mirrored pattern that never registers -->
					<text x={LANE[i]} y="51" class="t-foot">film {i + 1}/3 · INK UP ▲</text>
				</svg>
			{/each}
		</section>

		<section class="sheet">
			<p class="sheetnote">page 3 · print on white cardstock · the backer, goes behind the stack</p>
			<svg
				class="card backer"
				width="{CW}mm"
				height="{CH}mm"
				viewBox="0 0 {CW} {CH}"
				xmlns="http://www.w3.org/2000/svg"
			>
				{@render cardframe()}
				<text x="5" y="9" class="t-badge">INTERLOCK</text>
				<text x="5" y="13.4" class="t-sub">three fingerprints · one word · {word}</text>
				<text x="5" y="27" class="t-step">1 · films ink-side up, this card at the back</text>
				<text x="5" y="31.5" class="t-step">2 · slide the films until the word glows through</text>
				<text x="5" y="36" class="t-step">3 · the six punched holes agree — peg them</text>
				<text x="5" y="43" class="t-sub">a changed answer is a film that fits nowhere:</text>
				<text x="5" y="46.5" class="t-sub">the ground never closes, and the word never comes.</text>
				{@render punch(HX[0], Y0 - 3.5)}
				{@render punch(HX[1], Y0 - 3.5)}
				<text x="5" y="51" class="t-foot">backer · white side to the films</text>
			</svg>
		</section>
	{/if}
</div>

<style>
	@page {
		size: A4 portrait;
		margin: 14mm;
	}
	.page {
		background: #fff;
		color: #000;
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	section {
		break-after: page;
		padding: 6mm 0;
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
	p {
		max-width: 150mm;
		font-size: 10pt;
		line-height: 1.6;
		margin: 0 0 4mm;
	}
	ul {
		max-width: 150mm;
		font-size: 9.5pt;
		line-height: 1.55;
		margin: 0 0 4mm;
		padding-left: 5mm;
	}
	li {
		margin-bottom: 2mm;
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
		width: 30mm;
		color: #555;
		text-transform: uppercase;
		letter-spacing: 0.12em;
	}
	dd {
		margin: 0;
		font-weight: 600;
	}
	.spoiler {
		letter-spacing: 0.2em;
	}
	.sheet {
		display: flex;
		flex-direction: column;
		gap: 7mm;
		align-items: flex-start;
	}
	.sheetnote {
		font-size: 8pt;
		color: #555;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		margin: 0;
	}
	.card {
		display: block;
	}
	.card text {
		font-family: var(--font-mono, ui-monospace, monospace);
	}
	.t-badge {
		font-size: 4.2px;
		font-weight: 700;
		letter-spacing: 0.06em;
	}
	.t-role {
		font-size: 2.4px;
		letter-spacing: 0.14em;
		fill: #444;
	}
	.t-digest {
		font-size: 2.6px;
		font-weight: 600;
	}
	.t-sub {
		font-size: 2.1px;
		fill: #444;
	}
	.t-step {
		font-size: 2.6px;
		font-weight: 600;
	}
	.t-foot {
		font-size: 2px;
		fill: #555;
		letter-spacing: 0.1em;
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
