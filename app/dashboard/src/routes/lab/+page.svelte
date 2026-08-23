<script lang="ts">
	/**
	 * /lab — the share bench.
	 *
	 * Three sheets, A B C. Each lights a third of the panel; between them they own
	 * every cell of the ground and not one cell of the word. Stack them and the ground
	 * closes while the letters stay black — and that stack is the picture, cell for
	 * cell, with no threshold pass and no second resolution anywhere in it.
	 *
	 * The bench exists so the claim can be checked rather than taken: switch a sheet
	 * off and watch its third punch straight out of the ground.
	 *
	 * Nothing here consults the stencil to decide what to draw. `union()` is handed
	 * whichever sheets are switched on and counts light; the picture is whatever comes
	 * back. MASK appears in one place only, in the measurements panel, and only to
	 * score a picture that was already drawn.
	 */
	import FingerprintRegister from '$lib/components/fingerprint-register.svelte';
	import {
		build,
		stats,
		stencil,
		layout,
		ALPHABET,
		FACE_LIMITS,
		GRID_LIMITS,
		DEFAULT_FACE,
		DEFAULT_GRID,
		DEFAULT_WORD
	} from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';
	import { onMount } from 'svelte';

	// ── palette ────────────────────────────────────────────────────────────────
	// The three sheets are colour-coded, and the codes have to survive being seen one
	// at a time: three greens would be three greens. Lime, cyan and violet sit far
	// enough apart on the wheel to be named across a room.
	const HUES = ['#b6e04c', '#3fd2ea', '#c98cf6'];
	const NAMES = ['A', 'B', 'C'];
	const ROLES = ['input fingerprint', 'output fingerprint', 'model fingerprint'];
	const SUBS = ['certified inbound', 'certified outbound', 'committed in advance'];
	/** the one colour the finished stack is read in */
	const LAMP = '#35e08b';
	/** and the black the letters are left in */
	const VOID = '#05080b';

	// ── state ──────────────────────────────────────────────────────────────────
	const rand = () =>
		Array.from({ length: 40 }, () => '0123456789abcdef'[(Math.random() * 16) | 0]).join('');

	let req = $state('4f74f5c6b3a19e02d81c7745aa30bb61c4e9f0d2');
	let rsp = $state('a1b93de77c04582fe61099ab3d5c77e0114fa2b8');
	let model = $state('6e6001da2106d4757498752a021df6c2bdc332c6');
	let on = $state([true, true, true]);
	let pass = $state(true);
	let tint = $state<'one' | 'sheet'>('one');
	let showSeq = $state(false);
	let text = $state(DEFAULT_WORD);
	let size = $state(DEFAULT_FACE.size);
	let weight = $state(DEFAULT_FACE.weight);
	let cols = $state(DEFAULT_GRID.cols);
	let rows = $state(DEFAULT_GRID.rows);

	const grid = $derived({ rows, cols });
	const KEEP = new RegExp(`[^${ALPHABET.replace(/[-^\]\\]/g, '\\$&')} ]`, 'g');
	const word = $derived(text.toUpperCase().replace(KEEP, ''));

	/**
	 * The grid is in cells and the panels are in pixels, so each pitch is whatever
	 * makes the one fit the other. A coarse grid gets fat cells and a fine one small
	 * ones; the panel stays the same width either way, which is what keeps the layout
	 * still while a slider is being dragged.
	 */
	const GAP = 1;
	const fitPitch = (max: number, cap: number) =>
		Math.max(2, Math.min(cap, Math.floor((max + GAP) / cols)));
	const ST_PITCH = $derived(fitPitch(944, 16));
	const ST_CELL = $derived(ST_PITCH - GAP);
	const ST_W = $derived(cols * ST_PITCH - GAP);
	const ST_H = $derived(rows * ST_PITCH - GAP);
	const SH_PITCH = $derived(fitPitch(734, 10));
	const SH_CELL = $derived(SH_PITCH - GAP);
	const SH_W = $derived(cols * SH_PITCH - GAP);
	const SH_H = $derived(rows * SH_PITCH - GAP);

	// `metrics` is the face the stencil will ACTUALLY use, which is not always the one
	// the sliders asked for: a stroke cannot be thicker than the counter it has to
	// leave behind, so weight is clamped against the glyph width. Reading the clamped
	// value back is why the panel can say what it drew rather than what it was told.
	const face = $derived(layout(word, { size, weight }, grid));
	const mask = $derived(stencil(word, { size, weight }, grid));
	const N = $derived(rows * cols);
	const wordCells = $derived(mask.reduce((n, v) => n + v, 0));
	const shares = $derived(build(req, rsp, model, pass, mask));
	const layers = $derived([shares.a, shares.b, shares.c]);
	const sel = $derived([0, 1, 2].filter((i) => on[i]));
	const measured = $derived(stats(shares, mask));
	const partial = $derived(
		stats(
			{
				a: on[0] ? layers[0] : undefined,
				b: on[1] ? layers[1] : undefined,
				c: on[2] ? layers[2] : undefined
			},
			mask
		)
	);

	const count = $derived(sel.length);
	const verdict = $derived(
		count < 3
			? `${count} of 3 sheets — the missing third is a hole in the ground`
			: pass
				? 'three thirds of one ground — it closes, and the word stays black'
				: 'three sheets, but the third was not the one dealt'
	);

	// ── painting ───────────────────────────────────────────────────────────────
	const hex2rgb = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
	const rgb2hex = (c: number[]) =>
		'#' +
		c
			.map((v) =>
				Math.max(0, Math.min(255, Math.round(v)))
					.toString(16)
					.padStart(2, '0')
			)
			.join('');
	/** t = 0 is all of a, t = 1 is all of b */
	const mix = (a: number[], b: number[], t: number) => a.map((v, i) => v + (b[i] - v) * t);
	const HUE_RGB = HUES.map(hex2rgb);
	const WHITE = [255, 255, 255];
	/**
	 * How far towards white a cell goes once n sheets have lit it. The deal gives each
	 * ground cell to one sheet, so almost every lit cell is n = 1 and the ground reads
	 * as a mosaic of the three. The few brighter ones are the top-up: cells a sheet
	 * lit that another already owned, which is what evens the densities out.
	 */
	const GLOW = [0, 0, 0.45, 0.8];

	function fit(cv: HTMLCanvasElement, w: number, h: number) {
		const dpr = window.devicePixelRatio || 1;
		cv.width = Math.round(w * dpr);
		cv.height = Math.round(h * dpr);
		cv.style.width = `${w}px`;
		cv.style.height = `${h}px`;
		const ctx = cv.getContext('2d');
		ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
		return ctx;
	}

	function paintStack(cv: HTMLCanvasElement | null, which: number[], mode: 'one' | 'sheet') {
		if (!cv) return;
		const ctx = fit(cv, ST_W, ST_H);
		if (!ctx) return;
		ctx.fillStyle = VOID;
		ctx.fillRect(0, 0, ST_W, ST_H);
		for (let r = 0; r < rows; r++) {
			for (let c = 0; c < cols; c++) {
				const i = r * cols + c;
				const by = which.filter((k) => layers[k][i] > 0);
				if (!by.length) continue;
				if (mode === 'one') {
					ctx.fillStyle = LAMP;
				} else {
					const avg = [0, 1, 2].map((ch) => by.reduce((s, k) => s + HUE_RGB[k][ch], 0) / by.length);
					ctx.fillStyle = rgb2hex(mix(avg, WHITE, GLOW[by.length]));
				}
				ctx.fillRect(c * ST_PITCH, r * ST_PITCH, ST_CELL, ST_CELL);
			}
		}
	}

	function paintSheet(cv: HTMLCanvasElement | null, lv: Uint8Array, hue: string, live: boolean) {
		if (!cv) return;
		const ctx = fit(cv, SH_W, SH_H);
		if (!ctx) return;
		ctx.fillStyle = VOID;
		ctx.fillRect(0, 0, SH_W, SH_H);
		const dim = ['#0f141b', '#131922'];
		for (let r = 0; r < rows; r++) {
			for (let c = 0; c < cols; c++) {
				const l = lv[r * cols + c];
				ctx.globalAlpha = l ? (live ? [0, 0.62, 0.76, 0.88, 1][l] : 0.22) : 1;
				ctx.fillStyle = l ? hue : dim[(r + c) & 1];
				ctx.fillRect(c * SH_PITCH, r * SH_PITCH, SH_CELL, SH_CELL);
			}
		}
		ctx.globalAlpha = 1;
	}

	let stackCv = $state<HTMLCanvasElement | null>(null);
	let sheetCv = $state<(HTMLCanvasElement | null)[]>([null, null, null]);

	$effect(() => {
		void [layers, mask];
		paintStack(stackCv, sel, tint);
	});
	$effect(() => {
		void mask;
		for (let i = 0; i < 3; i++) paintSheet(sheetCv[i], layers[i], HUES[i], on[i]);
	});

	// ?a=0&b=1&c=1&outcome=fail&tint=sheet so a state can be linked, or shot headlessly
	onMount(() => {
		const q = new URLSearchParams(location.search);
		['a', 'b', 'c'].forEach((k, i) => {
			const v = q.get(k);
			if (v !== null) on[i] = v !== '0';
		});
		if (q.get('outcome') === 'fail') pass = false;
		const ti = q.get('tint');
		if (ti === 'one' || ti === 'sheet') tint = ti;
		const num = (k: string, set: (v: number) => void) => {
			const v = Number(q.get(k));
			if (q.get(k) !== null && Number.isFinite(v) && v) set(v);
		};
		num('size', (v) => (size = v));
		num('weight', (v) => (weight = v));
		num('cols', (v) => (cols = v));
		num('rows', (v) => (rows = v));
		const tx = q.get('text');
		if (tx !== null) text = tx;
		if (q.get('seq') === '1') showSeq = true;
	});

	const fmt = (h: string) => '0x' + h.slice(0, 12).toUpperCase();
	const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
</script>

<svelte:head><title>Share bench</title></svelte:head>

<div class="min-h-svh bg-background text-foreground">
	<header class="border-b border-border">
		<div class="mx-auto flex max-w-[1040px] items-baseline justify-between gap-4 px-6 py-3">
			<span class="font-mono text-sm font-semibold tracking-[0.22em]">INTERLOCK · LAB</span>
			<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
				share bench · no hardware attached
			</span>
		</div>
	</header>

	<main class="mx-auto flex max-w-[1040px] flex-col gap-4 px-6 py-6">
		<!-- ── the stack ────────────────────────────────────────────────────── -->
		<section class="border border-border bg-card">
			<div
				class="flex flex-wrap items-baseline justify-between gap-4 border-b border-border px-4 py-2"
			>
				<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
					The stack · A + B + C, cell for cell
				</span>
				<div class="flex items-center gap-2">
					<span
						class={cn(
							'font-mono text-[10px] tracking-[0.12em]',
							count === 3 && pass ? 'text-verified' : 'text-muted-foreground/70'
						)}
					>
						{verdict}
					</span>
					{#each [{ v: 'one', l: 'one colour' }, { v: 'sheet', l: 'by sheet' }] as o (o.v)}
						<button
							class={cn(
								'border px-2 py-0.5 font-mono text-[9px] tracking-[0.12em] uppercase transition-colors',
								tint === o.v
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => (tint = o.v as 'one' | 'sheet')}>{o.l}</button
						>
					{/each}
				</div>
			</div>
			<div class="flex justify-center overflow-x-auto p-4">
				<canvas bind:this={stackCv} class="shrink-0" aria-hidden="true"></canvas>
			</div>
		</section>

		<!-- ── the sheets ───────────────────────────────────────────────────── -->
		<div class="flex flex-col gap-2">
			{#each NAMES as name, i (name)}
				<div
					class={cn(
						'flex items-center gap-4 border bg-card p-3 transition-colors',
						on[i] ? 'border-border' : 'border-border/40'
					)}
				>
					<div class="flex w-[180px] shrink-0 flex-col gap-1.5">
						<div class="flex items-center gap-2">
							<span
								class="size-2.5 shrink-0 transition-opacity"
								style="background:{HUES[i]};opacity:{on[i] ? 1 : 0.3}"
							></span>
							<span class="font-mono text-[15px] font-semibold" style="color:{HUES[i]}">
								{name}
							</span>
							<span class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground uppercase">
								{ROLES[i]}
							</span>
						</div>
						<span
							class="tabular font-mono text-[12px] transition-opacity"
							style="color:{HUES[i]};opacity:{on[i] ? 1 : 0.4}"
						>
							{fmt([req, rsp, model][i])}
						</span>
						<span class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground/60 uppercase">
							{SUBS[i]} · {measured.lit[i]} cells, {pct(measured.density[i])} of panel
						</span>
						<button
							class={cn(
								'mt-0.5 w-fit border px-3 py-1 font-mono text-[10px] tracking-[0.16em] uppercase transition-colors',
								on[i]
									? 'border-current bg-current/10'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							style={on[i] ? `color:${HUES[i]}` : ''}
							aria-pressed={on[i]}
							onclick={() => (on[i] = !on[i])}
						>
							{on[i] ? 'on' : 'off'}
						</button>
					</div>
					<div class="overflow-x-auto">
						<canvas bind:this={sheetCv[i]} class="shrink-0" aria-hidden="true"></canvas>
					</div>
				</div>
			{/each}
		</div>

		<div class="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
			<!-- ── controls ─────────────────────────────────────────────────── -->
			<div class="flex flex-col gap-4 border border-border bg-card p-4">
				<div class="flex flex-wrap items-center gap-2">
					<span
						class="w-20 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
					>
						Sheets
					</span>
					<button
						class="border border-border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
						onclick={() => (on = [true, true, true])}>All on</button
					>
					{#each NAMES as n, i (n)}
						<button
							class="border border-border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
							onclick={() => (on = on.map((_, k) => k === i))}>{n} only</button
						>
					{/each}
					<button
						class="border border-border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
						onclick={() => (on = on.map((_, k) => k !== 2))}>A + B</button
					>
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span
						class="w-20 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
					>
						Sheet C
					</span>
					{#each [{ v: true, l: 'was dealt' }, { v: false, l: 'was not' }] as o (o.l)}
						<button
							class={cn(
								'border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors',
								pass === o.v
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => (pass = o.v)}>{o.l}</button
						>
					{/each}
					<span class="font-mono text-[10px] text-muted-foreground/70">
						A and B are byte-identical either way — only C changes
					</span>
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span
						class="w-20 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
					>
						Word
					</span>
					<input bind:value={text} class="lab-hex lab-word" spellcheck="false" maxlength="16" />
					<span class="font-mono text-[10px] whitespace-nowrap text-muted-foreground/70">
						A–Z 0–9
					</span>
				</div>

				<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
					<span
						class="w-20 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
					>
						Face
					</span>
					<label class="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
						SIZE
						<input
							type="range"
							min={FACE_LIMITS.size[0]}
							max={FACE_LIMITS.size[1]}
							step="1"
							bind:value={size}
							class="w-36"
							aria-label="letter height in cells"
						/>
						<span class="tabular w-10 text-foreground">{face.h}</span>
					</label>
					<label class="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
						WEIGHT
						<input
							type="range"
							min={FACE_LIMITS.weight[0]}
							max={FACE_LIMITS.weight[1]}
							step="1"
							bind:value={weight}
							class="w-24"
							aria-label="stroke thickness in cells"
						/>
						<span class="tabular w-10 text-foreground">{face.t}</span>
					</label>
					<span class="font-mono text-[10px] text-muted-foreground/70">
						glyph {face.w}×{face.h}, gap {face.gap}
					</span>
				</div>

				<div class="flex flex-wrap items-center gap-x-4 gap-y-2">
					<span
						class="w-20 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
					>
						Grid
					</span>
					<label class="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
						WIDTH
						<input
							type="range"
							min={GRID_LIMITS.cols[0]}
							max={GRID_LIMITS.cols[1]}
							step="1"
							bind:value={cols}
							class="w-36"
							aria-label="grid width in cells"
						/>
						<span class="tabular w-10 text-foreground">{cols}</span>
					</label>
					<label class="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
						HEIGHT
						<input
							type="range"
							min={GRID_LIMITS.rows[0]}
							max={GRID_LIMITS.rows[1]}
							step="1"
							bind:value={rows}
							class="w-24"
							aria-label="grid height in cells"
						/>
						<span class="tabular w-10 text-foreground">{rows}</span>
					</label>
					<span class="font-mono text-[10px] text-muted-foreground/70">
						{N} cells at {ST_CELL}px
					</span>
				</div>

				{#if !face.fits}
					<p class="font-mono text-[10px] leading-relaxed text-fault">
						The word wants {face.span} × {face.h} cells and the grid is {cols} × {rows}. It is drawn
						from the left rather than cropped down the middle — widen the grid, or take the size
						down.
					</p>
				{/if}

				<div class="flex flex-col gap-2">
					{#each [{ k: 'a', label: 'A · input' }, { k: 'b', label: 'B · output' }, { k: 'c', label: 'C · model' }] as f, i (f.k)}
						<div class="flex items-center gap-2">
							<span
								class="w-20 shrink-0 font-mono text-[10px] tracking-[0.14em] uppercase"
								style="color:{HUES[i]}"
							>
								{f.label}
							</span>
							{#if f.k === 'a'}
								<input bind:value={req} class="lab-hex" spellcheck="false" />
							{:else if f.k === 'b'}
								<input bind:value={rsp} class="lab-hex" spellcheck="false" />
							{:else}
								<input bind:value={model} class="lab-hex" spellcheck="false" />
							{/if}
						</div>
					{/each}
					<div class="flex gap-2 pl-22">
						<button
							class="border border-border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
							onclick={() => {
								req = rand();
								rsp = rand();
								model = rand();
							}}>Randomise all</button
						>
						<button
							class="border border-border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] text-muted-foreground uppercase transition-colors hover:text-foreground"
							onclick={() => (showSeq = !showSeq)}
							aria-pressed={showSeq}>{showSeq ? 'Hide' : 'Show'} sequence</button
						>
					</div>
				</div>
			</div>

			<!-- ── measurements, not claims ─────────────────────────────────── -->
			<div class="min-w-[280px] border border-border bg-card p-4 font-mono text-[11px]">
				<div class="mb-3 text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
					Measured on the sheets above
				</div>
				<dl class="tabular flex flex-col gap-1.5">
					{#each NAMES as n, i (n)}
						<div class="flex justify-between gap-6">
							<dt style="color:{HUES[i]}">sheet {n} of ground</dt>
							<dd class={measured.ofGround[i] > 0.32 ? 'text-verified' : 'text-caution'}>
								{pct(measured.ofGround[i])}
							</dd>
						</div>
					{/each}
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">…of which inside the word</dt>
						<dd class={measured.ghost.every((g) => g === 0) ? 'text-verified' : 'text-fault'}>
							{pct(Math.max(...measured.ghost))}
						</dd>
					</div>
					<div class="my-1 h-px bg-border"></div>
					<div class="text-[10px] tracking-[0.14em] text-muted-foreground/70 uppercase">
						stacked, {count} sheet{count === 1 ? '' : 's'} on
					</div>
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">ground lit</dt>
						<dd class={partial.stacked.field === 1 ? 'text-verified' : 'text-caution'}>
							{pct(partial.stacked.field)}
						</dd>
					</div>
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">word lit</dt>
						<dd class={partial.stacked.letters === 0 ? 'text-verified' : 'text-fault'}>
							{pct(partial.stacked.letters)}
						</dd>
					</div>
					<div class="my-1 h-px bg-border"></div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>grid</dt>
						<dd>{rows} × {cols} = {N} · {ST_CELL}px cells</dd>
					</div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>held per sheet</dt>
						<dd>{measured.lit.join(' / ')}</dd>
					</div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>word</dt>
						<dd>{wordCells} cells ({pct(wordCells / N)})</dd>
					</div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>stroke</dt>
						<dd>{face.t} cell{face.t === 1 ? '' : 's'}</dd>
					</div>
				</dl>
				<p class="mt-3 leading-relaxed text-muted-foreground/70">
					The ground is dealt out a cell at a time, so all three sheets are load bearing: switch one
					off and its third goes black where it stood, which is the holed ground above rather than a
					blank panel.
				</p>
				<p class="mt-2 leading-relaxed text-caution/80">
					The word being <em>completely</em> black in the stack means no sheet lit a single cell of it
					— so each sheet has a hole shaped like the word, and you can find it if you look. That is forced,
					not sloppy: hiding the hole needs subcell expansion, and expansion is what puts a third of the
					light back into the letters.
				</p>
			</div>
		</div>

		{#if showSeq}
			<section class="flex flex-col gap-2">
				<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
					Sequence preview — the register as the demo page drives it
				</span>
				<FingerprintRegister
					req={on[0] ? req : null}
					rsp={on[1] ? rsp : null}
					model={on[2] ? model : null}
					stage={count === 3 ? (pass ? 'resolved' : 'clash') : 'stacked'}
					{word}
					face={{ size, weight }}
					{grid}
				/>
			</section>
		{/if}
	</main>
</div>

<style>
	.lab-hex {
		flex: 1;
		min-width: 0;
		border: 1px solid var(--border);
		background: var(--background);
		padding: 0.35rem 0.6rem;
		font-family: var(--font-mono);
		font-size: 11px;
		font-variant-numeric: tabular-nums;
		color: var(--foreground);
	}
	.lab-word {
		text-transform: uppercase;
		letter-spacing: 0.14em;
	}
	.lab-hex:focus {
		outline: 1px solid var(--ring);
		outline-offset: -1px;
	}
</style>
