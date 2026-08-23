<script lang="ts">
	/**
	 * Fingerprint register.
	 *
	 * Three digests come off a run: the certifier's fingerprint of the request, its
	 * fingerprint of the response, and the commitment to the model weights. Each is
	 * one share of a (3,3) visual secret sharing scheme — see $lib/fingerprint-shares.
	 *
	 * Each sheet LIGHTS a third of the panel, and the sheets are laid over one another
	 * so the light adds. The ground was dealt out between the three, one cell to one
	 * sheet, so together they fill it exactly; no sheet lights a letter cell at all, so
	 * the word stays black however many sheets go down.
	 *
	 * What you see stacked is the union, cell for cell. There is no threshold pass and
	 * no second resolution — a cell was lit by somebody or it was not.
	 *
	 * Everything is composited into one canvas at the sheets' current positions, so
	 * the slide is three sheets actually moving, not a dissolve between two pictures.
	 * Nothing here knows the message — there is no mask lookup below this comment.
	 * Drop a sheet and the word goes; that is the only thing holding it up.
	 */
	import { untrack } from 'svelte';
	import { build, union, COLS, N, ROWS, type Shares } from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';

	type Stage = 'hidden' | 'stacked' | 'register' | 'resolved' | 'clash';

	let {
		req = null,
		rsp = null,
		model = null,
		stage = 'hidden',
		only = null
	}: {
		req?: string | null;
		rsp?: string | null;
		model?: string | null;
		stage?: Stage;
		/** testbed only: show a single sheet */
		only?: number | null;
	} = $props();

	// 91 cells across, one per message pixel: at a 9 px pitch that is 818, the widest
	// the demo page's column takes without scrolling.
	const CELL = 8;
	const GAP = 1;
	const PITCH = CELL + GAP;
	const W = COLS * PITCH - GAP; // 818
	const H = ROWS * PITCH - GAP; // 260
	// Decked, the three sit side by side across the width they will occupy stacked, so
	// the slide is a convergence rather than a jump.
	const DECK_GAP = 18;
	const DECK_W = (W - 2 * DECK_GAP) / 3;
	const DECK = DECK_W / W;
	const BOX = H;
	const INK = [0, 0.45, 0.62, 0.82, 1]; // a sheet's own four ink levels

	const decoded = $derived(stage === 'resolved' || stage === 'clash');
	/**
	 * The deck converges only once the THIRD sheet has been dealt, which is when the
	 * verdict lands. An earlier cut slid the two wire sheets together while the proof
	 * was still running, so by the time the model sheet existed there was nothing left
	 * to stack: it appeared already merged and the one moment worth watching happened
	 * off-screen. Now all three are on the table, side by side, before anything moves.
	 */
	const converging = $derived(decoded);
	/** how long the completed deck is held before it slides, so the third sheet reads */
	const DEAL_HOLD = 550;
	const EMPTY = new Uint8Array(N);

	// Sheet C is the only one the outcome touches; A and B are byte-identical either
	// way, so the deck cannot be read ahead of the verdict.
	const shares = $derived<Shares | null>(
		req ? build(req, rsp ?? '', model ?? '', stage !== 'clash') : null
	);

	const cards = $derived([
		{
			key: 'in',
			tag: 'Input fingerprint',
			sub: 'certified inbound',
			hex: req,
			lv: shares?.a ?? null
		},
		{
			key: 'out',
			tag: 'Output fingerprint',
			sub: 'certified outbound',
			hex: rsp,
			lv: rsp ? (shares?.b ?? null) : null
		},
		{
			key: 'model',
			tag: 'Model fingerprint',
			sub: 'committed in advance',
			hex: model,
			lv: model ? (shares?.c ?? null) : null
		}
	]);

	const live = $derived(
		cards.map((c, i) => ({ i, lv: c.lv })).filter((c) => c.lv && (only === null || only === c.i))
	);

	let view = $state<HTMLCanvasElement | null>(null);
	let hues = $state<string[]>(['#8fdc4a', '#4ae8a8', '#3fd8d0', '#4ae8a8']);
	let fault = $state('#ff6b5e');
	let ground = $state('#242c39');
	/** the black the letters are cut out in — the read's only other colour */
	const VOID = '#05080b';
	let dpr = 1;

	// Read once. An earlier cut of this read hues[] to supply its own fallbacks while
	// assigning a fresh hues array, so the effect re-triggered itself forever and
	// pegged the tab -- hence the `ready` latch and the literal fallbacks.
	let ready = $state(false);
	function readPalette() {
		const cs = getComputedStyle(document.documentElement);
		const v = (n: string, fb: string) => cs.getPropertyValue(n).trim() || fb;
		hues = [
			v('--fp-in', '#8fdc4a'),
			v('--fp-out', '#4ae8a8'),
			v('--fp-model', '#3fd8d0'),
			v('--verified', '#4ae8a8')
		];
		fault = v('--fault', '#ff6b5e');
		ground = v('--grid', '#242c39');
	}

	function surface() {
		const cv = document.createElement('canvas');
		cv.width = Math.round(W * dpr);
		cv.height = Math.round(H * dpr);
		const ctx = cv.getContext('2d');
		ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
		return { cv, ctx };
	}

	const dot = (ctx: CanvasRenderingContext2D, r: number, c: number) => {
		ctx.beginPath();
		ctx.roundRect(c * PITCH, r * PITCH, CELL, CELL, 1.5);
		ctx.fill();
	};

	/**
	 * One sheet's lit cells, pre-rendered so a frame costs three drawImage calls
	 * instead of twenty-three thousand rectangles. Transparent everywhere the sheet is
	 * dark, so laying the three down really is adding their light together.
	 *
	 * 'ghost' lays down every cell instead, so an empty slot still reads as a grid.
	 */
	function bake(lv: Uint8Array, hue: string, mode: 'light' | 'ghost', faint: boolean) {
		const { cv, ctx } = surface();
		if (!ctx) return cv;
		for (let r = 0; r < ROWS; r++) {
			for (let c = 0; c < COLS; c++) {
				const l = lv[r * COLS + c];
				if (mode !== 'ghost' && !l) continue;
				ctx.globalAlpha = mode === 'ghost' ? 1 : INK[l];
				ctx.fillStyle = faint ? ground : hue;
				dot(ctx, r, c);
			}
		}
		return cv;
	}

	/**
	 * The same union, in one colour instead of three. Opaque and full-bleed so it
	 * cross-fades over the coloured stack cleanly.
	 *
	 * This is a recolour and nothing else: the lit cells are exactly the cells the
	 * three sheets lit, counted by `union()`, which is handed the sheets and knows
	 * nothing else. Dropping a sheet punches its third straight out of the ground.
	 */
	function bakeUnion(u: Uint8Array, hue: string) {
		const { cv, ctx } = surface();
		if (!ctx) return cv;
		ctx.fillStyle = VOID;
		ctx.fillRect(0, 0, W, H);
		ctx.fillStyle = hue;
		for (let r = 0; r < ROWS; r++) {
			for (let c = 0; c < COLS; c++) {
				if (u[r * COLS + c]) dot(ctx, r, c);
			}
		}
		return cv;
	}

	let sheets = $state<(HTMLCanvasElement | null)[]>([null, null, null]);
	let ghost = $state<HTMLCanvasElement | null>(null);
	let plate = $state<HTMLCanvasElement | null>(null);

	// eased 0 -> 1 PER SHEET: 0 is that sheet out in its slot of the deck, 1 is it in
	// register with the others. One number per sheet rather than one for the panel,
	// because the sheets do not arrive together: the two wire digests are certified
	// while the proof is still running and converge then, and the model sheet cannot
	// be drawn until the verdict says which one it is. Sharing a single progress made
	// the third sheet appear already merged — it never visibly landed, which is the
	// one moment in the animation that is actually load-bearing.
	let prog = $state([0, 0, 0]);
	// eased 0 -> 1: 0 is the raw subcell union, 1 is the message-resolution read
	let develop = $state(0);
	let rafP = [0, 0, 0];
	let rafD = 0;
	const still = () =>
		typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

	function tween(
		from: number,
		to: number,
		ms: number,
		delay: number,
		put: (v: number) => void,
		cancel: number
	) {
		cancelAnimationFrame(cancel);
		if (from === to) return 0;
		// Honour reduced motion — and it doubles as the static path for screenshots,
		// which never see a canvas whose last paint happened inside a rAF callback.
		if (still()) {
			put(to);
			return 0;
		}
		const t0 = performance.now() + delay;
		const step = (now: number) => {
			const k = Math.min(1, Math.max(0, (now - t0) / ms));
			const e = 1 - Math.pow(1 - k, 3);
			put(from + (to - from) * e);
			if (k < 1) h = requestAnimationFrame(step);
		};
		let h = requestAnimationFrame(step);
		return h;
	}

	function paint() {
		const cv = view;
		if (!cv) return;
		const ctx = cv.getContext('2d');
		if (!ctx) return;
		if (cv.width !== Math.round(W * dpr)) {
			cv.width = Math.round(W * dpr);
			cv.height = Math.round(H * dpr);
			cv.style.width = `${W}px`;
			cv.style.height = `${H}px`;
		}
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		ctx.clearRect(0, 0, W, H);

		const place = (i: number) => {
			const p = prog[i];
			const x0 = i * (DECK_W + DECK_GAP);
			const y0 = (BOX - H * DECK) / 2;
			return { x: x0 * (1 - p), y: y0 * (1 - p), s: DECK + (1 - DECK) * p };
		};

		// sheets with no digest yet hold their slot open
		if (ghost) {
			for (let i = 0; i < 3; i++) {
				if (cards[i].lv) continue;
				const { x, y, s: k } = place(i);
				ctx.save();
				ctx.globalAlpha = 0.3 * (1 - prog[i]);
				ctx.translate(x, y);
				ctx.scale(k, k);
				ctx.drawImage(ghost, 0, 0, W, H);
				ctx.restore();
			}
		}

		// the sheets themselves. Transparent where dark, so laying all three down adds
		// their light — which is what the word is made of.
		for (const c of live) {
			const sh = sheets[c.i];
			if (!sh) continue;
			const { x, y, s: k } = place(c.i);
			ctx.save();
			ctx.translate(x, y);
			ctx.scale(k, k);
			ctx.drawImage(sh, 0, 0, W, H);
			ctx.restore();
		}

		// pass three: the same union, read at message resolution
		if (plate && develop > 0) {
			ctx.save();
			ctx.globalAlpha = develop;
			ctx.drawImage(plate, 0, 0, W, H);
			ctx.restore();
		}
	}

	$effect(() => {
		if (ready) return;
		dpr = window.devicePixelRatio || 1;
		readPalette();
		ghost = bake(EMPTY, ground, 'ghost', true);
		ready = true;
	});

	$effect(() => {
		const unify = stage === 'resolved';
		sheets = cards.map((c, i) =>
			c.lv ? bake(c.lv, unify ? hues[3] : hues[i], 'light', false) : null
		);
	});

	$effect(() => {
		// The plate is a read of the sheets on the table and nothing else. `only` is
		// honoured, which is how the testbed shows that one sheet decodes to a slab.
		void ready;
		plate = live.length
			? bakeUnion(union(live.map((c) => c.lv as Uint8Array)), stage === 'clash' ? fault : hues[3])
			: null;
	});

	// Both tweens read the value they are about to write, so the reads are untracked:
	// a tracked one would make each rAF frame re-run the effect that started it, which
	// is the loop that pegged the tab the last time this component grew a tween. The
	// effects depend on the STAGE flags and nothing else.
	$effect(() => {
		const want = cards.map((c) => (converging && c.lv ? 1 : 0));
		untrack(() => {
			for (let i = 0; i < 3; i++) {
				// hold the finished deck a beat before it moves, so the sheet that just
				// arrived is seen as a sheet rather than as a flicker
				const hold = want[i] > prog[i] ? DEAL_HOLD : 0;
				rafP[i] = tween(prog[i], want[i], 950, hold, (v) => (prog[i] = v), rafP[i]);
			}
		});
	});

	$effect(() => {
		const to = decoded ? 1 : 0;
		const n = live.length;
		untrack(() => {
			// Develop only once every sheet on the table is actually in register, so
			// the wait is set by the LAST one to land — deal hold included.
			const behind = n ? Math.min(...live.map((c) => prog[c.i])) : 1;
			const wait = to ? (behind === 0 ? DEAL_HOLD : 0) + (1 - behind) * 950 + 120 : 0;
			rafD = tween(develop, to, 620, wait, (v) => (develop = v), rafD);
		});
	});

	$effect(() => {
		// touch everything a frame depends on
		void [sheets, ghost, plate, prog[0], prog[1], prog[2], develop, only, stage, ready];
		paint();
	});

	const fmt = (h: string | null) => (h ? '0x' + h.slice(0, 12).toUpperCase() : '—');
</script>

<section class="border border-border bg-card">
	<div class="flex items-baseline justify-between gap-4 border-b border-border px-4 py-2">
		<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
			Fingerprint register
		</span>
		<span
			class={cn(
				'font-mono text-[10px] tracking-[0.12em]',
				stage === 'clash' ? 'text-fault' : 'text-muted-foreground/70'
			)}
		>
			{#if stage === 'resolved'}
				three thirds of one ground — together they leave none of it dark
			{:else if stage === 'clash'}
				the third sheet was not the one dealt — the ground never closes
			{:else if stage === 'register'}
				proof in flight — the third sheet has not landed
			{:else}
				one sheet per digest · each lights a third of the panel
			{/if}
		</span>
	</div>

	<div class="flex flex-col items-center gap-3 overflow-x-auto p-4">
		<div class="flex shrink-0 gap-[18px]" style="width:{W}px">
			{#each cards as d, i (d.key)}
				<div
					class={cn(
						'flex flex-col gap-1 transition-opacity duration-500',
						d.hex ? 'opacity-100' : 'opacity-25'
					)}
					style="width:{DECK_W}px"
				>
					<div class="flex items-center gap-2">
						<span class="size-2 shrink-0" style="background:{hues[i]}"></span>
						<span class="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
							{d.tag}
						</span>
					</div>
					<div
						class="tabular font-mono text-[15px] leading-none font-semibold"
						style="color:{hues[i]}"
					>
						{fmt(d.hex)}
					</div>
					<div class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground/70 uppercase">
						{d.sub}
					</div>
				</div>
			{/each}
		</div>

		<div class="relative shrink-0" style="height:{BOX}px;width:{W}px">
			<div
				class="pointer-events-none absolute -inset-8 transition-opacity duration-700"
				style="opacity:{stage === 'resolved'
					? 1
					: 0};background:radial-gradient(ellipse at center,color-mix(in oklab,var(--verified) 18%,transparent),transparent 70%)"
			></div>
			<div
				class="pointer-events-none absolute -inset-8 transition-opacity duration-700"
				style="opacity:{stage === 'clash'
					? 1
					: 0};background:radial-gradient(ellipse at center,color-mix(in oklab,var(--fault) 16%,transparent),transparent 68%)"
			></div>
			<canvas bind:this={view} class="absolute top-0 left-0" aria-hidden="true"></canvas>
		</div>
	</div>
</section>
