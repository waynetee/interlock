<script lang="ts">
	/**
	 * Fingerprint register.
	 *
	 * Three digests come off a run: the certifier's fingerprint of the request, its
	 * fingerprint of the response, and the commitment to the model weights. Each is
	 * one share of a (3,3) visual secret sharing scheme — see $lib/fingerprint-shares.
	 *
	 * Each share is drawn as INK on a clear sheet, and the sheets are laid over one
	 * another. Ink is opaque, so a cell survives bright only where none of the three
	 * inked it: hold three inked transparencies up to a lamp and this is the picture
	 * you get. That is still exactly the union — read in transmitted light rather than
	 * emitted — and it is worth the inversion. The field is the side the three shares
	 * ink disjointly, so it goes fully opaque: a ground with not one stray bright cell
	 * in it, which is what gives the letterforms a clean edge. The word itself comes
	 * through at 67%, and a 67% shape reads as a shape. The emitted-light reading
	 * cannot get there; it puts the solid side and the textured side the other way up.
	 *
	 * Everything is composited into one canvas at the sheets' current positions, so
	 * the slide is three sheets actually moving, not a dissolve between two pictures.
	 * Nothing here knows the message — there is no mask lookup below this comment.
	 * Drop a sheet and the word goes; that is the only thing holding it up.
	 */
	import { build, COLS, N, ROWS, type Polarity, type Shares } from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';

	type Stage = 'hidden' | 'stacked' | 'register' | 'resolved' | 'clash';
	type Readout = 'ink' | 'light';

	let {
		req = null,
		rsp = null,
		model = null,
		stage = 'hidden',
		only = null,
		polarity = 'cutout',
		readout = 'ink'
	}: {
		req?: string | null;
		rsp?: string | null;
		model?: string | null;
		stage?: Stage;
		/** testbed only: show a single sheet, to see for yourself that it says nothing */
		only?: number | null;
		polarity?: Polarity;
		/** 'ink' = light through stacked ink; 'light' = the emitted-light reading */
		readout?: Readout;
	} = $props();

	const CELL = 6;
	const GAP = 1;
	const PITCH = CELL + GAP;
	const W = COLS * PITCH - GAP;
	const H = ROWS * PITCH - GAP;
	// Decked, the three sit side by side across the width they will occupy stacked, so
	// the slide is a convergence rather than a jump.
	const DECK_GAP = 18;
	const DECK_W = (W - 2 * DECK_GAP) / 3;
	const DECK = DECK_W / W;
	const BOX = H;
	const INK = [0, 0.45, 0.62, 0.82, 1]; // a sheet's own four ink levels

	const registered = $derived(stage === 'register' || stage === 'resolved' || stage === 'clash');
	const EMPTY = new Uint8Array(N);

	// Sheet C is the only one the outcome touches; A and B are byte-identical either
	// way, so the deck cannot be read ahead of the verdict.
	const shares = $derived<Shares | null>(
		req ? build(req, rsp ?? '', model ?? '', stage !== 'clash', polarity) : null
	);

	const cards = $derived([
		{ key: 'in', tag: 'Input fingerprint', sub: 'certified inbound', hex: req, lv: shares?.a ?? null },
		{ key: 'out', tag: 'Output fingerprint', sub: 'certified outbound', hex: rsp, lv: rsp ? (shares?.b ?? null) : null },
		{ key: 'model', tag: 'Model fingerprint', sub: 'committed in advance', hex: model, lv: model ? (shares?.c ?? null) : null }
	]);

	let view = $state<HTMLCanvasElement | null>(null);
	let hues = $state<string[]>(['#8fdc4a', '#4ae8a8', '#3fd8d0', '#4ae8a8']);
	let ground = $state('#242c39');
	let card = $state('#1a1f2b');
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
		ground = v('--grid', '#242c39');
		card = v('--card', '#1a1f2b');
	}

	/**
	 * One sheet, pre-rendered so a frame costs three drawImage calls instead of
	 * twelve thousand rectangles.
	 *   ink   opaque everywhere, punched transparent where the sheet is clear
	 *   light the sheet's lit cells only, transparent elsewhere
	 */
	function bake(lv: Uint8Array, hue: string, mode: Readout | 'ghost', faint: boolean) {
		const cv = document.createElement('canvas');
		cv.width = Math.round(W * dpr);
		cv.height = Math.round(H * dpr);
		const ctx = cv.getContext('2d');
		if (!ctx) return cv;
		ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
		if (mode === 'ink') {
			ctx.fillStyle = card;
			ctx.fillRect(0, 0, W, H);
			ctx.globalCompositeOperation = 'destination-out';
		}
		for (let r = 0; r < ROWS; r++) {
			for (let c = 0; c < COLS; c++) {
				const l = lv[r * COLS + c];
				// 'ghost' lays down every cell, so an empty slot still reads as a grid
				const on = mode === 'ghost' ? true : mode === 'ink' ? !l : !!l;
				if (!on) continue;
				ctx.globalAlpha = mode === 'light' ? INK[l] : 1;
				ctx.fillStyle = faint ? ground : hue;
				ctx.beginPath();
				ctx.roundRect(c * PITCH, r * PITCH, CELL, CELL, 1.5);
				ctx.fill();
			}
		}
		return cv;
	}

	let sheets = $state<(HTMLCanvasElement | null)[]>([null, null, null]);
	let ghost = $state<HTMLCanvasElement | null>(null);

	// eased 0 -> 1: 0 is three sheets abreast, 1 is all three in register
	let progress = $state(0);
	let raf = 0;
	const still = () =>
		typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

	function tween(to: number) {
		cancelAnimationFrame(raf);
		const from = progress;
		if (from === to) return;
		// Honour reduced motion — and it doubles as the static path for screenshots,
		// which never see a canvas whose last paint happened inside a rAF callback.
		if (still()) {
			progress = to;
			return;
		}
		const t0 = performance.now();
		const ms = 950;
		const step = (now: number) => {
			const k = Math.min(1, (now - t0) / ms);
			const e = 1 - Math.pow(1 - k, 3);
			progress = from + (to - from) * e;
			if (k < 1) raf = requestAnimationFrame(step);
		};
		raf = requestAnimationFrame(step);
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

		const p = progress;
		const s = DECK + (1 - DECK) * p;
		const place = (i: number) => {
			const x0 = i * (DECK_W + DECK_GAP);
			const y0 = (BOX - H * DECK) / 2;
			return { x: x0 * (1 - p), y: y0 * (1 - p), s };
		};

		const live = cards
			.map((c, i) => ({ i, lv: c.lv }))
			.filter((c) => c.lv && (only === null || only === c.i));

		// sheets with no digest yet hold their slot open
		if (ghost) {
			for (let i = 0; i < 3; i++) {
				if (cards[i].lv) continue;
				const { x, y, s: k } = place(i);
				ctx.save();
				ctx.globalAlpha = 0.3 * (1 - p);
				ctx.translate(x, y);
				ctx.scale(k, k);
				ctx.drawImage(ghost, 0, 0, W, H);
				ctx.restore();
			}
		}

		if (readout === 'ink') {
			// pass one: the lamp behind each sheet
			for (const c of live) {
				const { x, y, s: k } = place(c.i);
				ctx.save();
				ctx.translate(x, y);
				ctx.scale(k, k);
				ctx.fillStyle = stage === 'resolved' ? hues[3] : hues[c.i];
				ctx.fillRect(0, 0, W, H);
				ctx.restore();
			}
		}
		// pass two: the ink itself. Opaque, so laying all three down IS the union.
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
	}

	$effect(() => {
		if (ready) return;
		dpr = window.devicePixelRatio || 1;
		readPalette();
		ghost = bake(EMPTY, ground, 'ghost', true);
		ready = true;
	});

	$effect(() => {
		const mode = readout;
		const unify = stage === 'resolved';
		sheets = cards.map((c, i) => (c.lv ? bake(c.lv, unify ? hues[3] : hues[i], mode, false) : null));
	});

	$effect(() => {
		tween(registered ? 1 : 0);
	});

	$effect(() => {
		// touch everything a frame depends on
		void [sheets, ghost, progress, only, readout, stage, ready];
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
				three sheets of ink — light gets through only where all three are clear
			{:else if stage === 'clash'}
				the third sheet does not complete — nothing survives the stack
			{:else if stage === 'register'}
				stacking…
			{:else}
				one sheet per digest · each inks 3 of every 9 cells, everywhere
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
					<div class="tabular font-mono text-[15px] leading-none font-semibold" style="color:{hues[i]}">
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
