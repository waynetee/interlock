<script lang="ts" module>
	/**
	 * idle      nothing on the wire yet
	 * dealing   the strips exist and are lying out of register
	 * searching the proof is in flight — the verifier is hunting for the seat
	 * pass/fail the verdict has landed and the strips settle onto it
	 */
	export type Stage = 'idle' | 'dealing' | 'searching' | 'pass' | 'fail';
</script>

<script lang="ts">
	/**
	 * Fingerprint register — the /lab bench, wired to the live run.
	 *
	 * Three digests come off a run: the certifier's fingerprint of the request, its
	 * fingerprint of the response, and the commitment to the model weights. Each is
	 * printed as a strip of film. Between them the three own every cell of the ground
	 * and not one cell of the word, so a registered pile closes the ground completely
	 * and the letters stay black.
	 *
	 * The strips are different heights and none of them is cropped, so they have to be
	 * SLID along Y until their patterns seat on the same rows — see $lib/fingerprint-
	 * shares for how the pile divides into a band and two dealt margins. That slide is
	 * the animation: the proof running is the strips hunting for their seat, and the
	 * verdict landing is them settling onto it.
	 *
	 * C is the backing. It is the model commitment, it is full height, and it does not
	 * move — the thing committed in advance is the thing the other two register onto.
	 * B is the output fingerprint, and it is the one the verdict decides: a response
	 * the certifier never fingerprinted is a strip of the right density that no longer
	 * fits the deal, and it is drawn in fault red.
	 *
	 * Nothing below this comment consults the stencil. `composite()` is handed the
	 * strips at their current slide and reports which of them lit each cell; the
	 * picture is whatever comes back. Drop a strip and its third punches straight out
	 * of the ground — that is the only thing holding the word up.
	 */
	import { untrack } from 'svelte';
	import {
		build,
		composite,
		homes,
		ROGUE,
		seats,
		stencil,
		strips,
		travel,
		DEFAULT_FACE,
		DEFAULT_GRID,
		DEFAULT_WORD,
		type Face,
		type Grid
	} from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';

	let {
		req = null,
		rsp = null,
		model = null,
		stage = 'idle',
		word = DEFAULT_WORD,
		face = DEFAULT_FACE,
		grid = DEFAULT_GRID,
		slack = 2,
		split = 0.5
	}: {
		/** the certifier's fingerprint of the request — strip A */
		req?: string | null;
		/** the certifier's fingerprint of the response — strip B */
		rsp?: string | null;
		/** the commitment to the weights — strip C, the backing */
		model?: string | null;
		stage?: Stage;
		/** the word the three strips add up to */
		word?: string;
		/** letter size and stroke weight, both in cells */
		face?: Face;
		/** the picture band in cells; the pixel pitch is derived to fit the column */
		grid?: Grid;
		/** spare rows on a sliding strip, and the depth of each margin */
		slack?: number;
		/** how much of each margin the sliding strip carries; the backing takes the rest */
		split?: number;
	} = $props();

	// ── the three films ────────────────────────────────────────────────────────
	// Lime, cyan and violet: the codes have to survive being seen one at a time
	// while they slide past each other, and three greens would be three greens.
	// Same three as the bench, so /lab and the demo are talking about one picture.
	const HUES = ['#b6e04c', '#3fd2ea', '#c98cf6'];
	const NAMES = ['A', 'B', 'C'];
	const ROLES = ['Input fingerprint', 'Output fingerprint', 'Model fingerprint'];
	const SUBS = ['certified inbound', 'certified outbound', 'committed in advance'];
	/** the one colour a registered pile is read in */
	const LAMP = '#35e08b';
	/** and the black the letters are left in */
	const VOID = '#05080b';
	const FAULT = '#f4593f';

	const pass = $derived(stage !== 'fail');
	const mask = $derived(stencil(word, face, grid));
	const sh = $derived(build(req ?? '', rsp ?? '', model ?? '', pass, mask));
	const st = $derived(strips(sh, grid, slack, model ?? '', split));

	/**
	 * Which strips are on the table. A and C both arrive with the request — the deal
	 * is seeded by the request digest, so C cannot be drawn before it exists even
	 * though the commitment it carries was made long beforehand. B arrives when the
	 * response is certified on the way back.
	 */
	const shown = $derived([!!req, !!rsp, !!req]);
	const sel = $derived([0, 1, 2].filter((i) => shown[i]));
	/** the same pile with the strips that have not arrived blanked, geometry intact */
	const table = $derived({
		...st,
		cells: st.cells.map((c, i) => (shown[i] ? c : new Uint8Array(c.length)))
	});

	// ── geometry ───────────────────────────────────────────────────────────────
	// The grid is in cells and the panel is in pixels, so the pitch is whatever makes
	// the one fit the other, measured off the column rather than assumed: this sits
	// under a scope that is already as wide as the page allows.
	const GAP = 1;
	let boxW = $state(0);
	const fit = (avail: number, cap: number) =>
		Math.max(3, Math.min(cap, Math.floor((Math.max(320, avail) + GAP) / grid.cols)));
	const PITCH = $derived(fit(boxW || 1152, 16));
	const CELL = $derived(PITCH - GAP);
	const W = $derived(grid.cols * PITCH - GAP);
	const H = $derived(st.pile * PITCH - GAP);
	// the three previews sit side by side under the pile, so each gets a third
	const SP = $derived(fit(((boxW || 1152) - 2 * 12) / 3, 7));
	const SW = $derived(grid.cols * SP - GAP);
	const SH = $derived(st.pile * SP - GAP);

	// ── registration ───────────────────────────────────────────────────────────
	let shift = $state([0, 0, 0]);
	const view = $derived(composite(table, shift, grid));
	const seat = $derived(seats(st, shift));
	/** registered when every strip on the table seats its pattern on the same row */
	const registered = $derived(sel.length === 3 && new Set(sel.map((i) => seat[i])).size === 1);

	/** 0 is three coloured films, 1 is the single-colour read of a registered pile */
	let blend = $state(0);
	let raf = 0;
	let rafB = 0;
	const frozen = () =>
		typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

	/** Somewhere out of register. Rejection-sampled, because most slides are not. */
	function scattered() {
		for (let n = 0; n < 64; n++) {
			const next = [0, 1, 2].map((i) => Math.floor(Math.random() * (travel(st, i) + 1)));
			if (new Set(seats(st, next)).size > 1) return next;
		}
		return [travel(st, 0), 0, 0];
	}

	/**
	 * The proof, as something you can watch. Each sliding strip ratchets through the
	 * positions open to it, one row at a time — which is what a piece of film does
	 * under a thumb — on its own interval, so the three are never in step and it
	 * reads as three independent searches rather than one scripted move. It runs for
	 * as long as the prover does; nothing here knows how long that will be.
	 */
	function hunt() {
		const STEP = [95, 135, 0];
		const t0 = performance.now();
		const step = (now: number) => {
			const t = now - t0;
			shift = [0, 1, 2].map((i) => {
				const span = travel(st, i);
				if (!span || !STEP[i]) return shift[i];
				return (Math.floor(t / STEP[i]) + i * 2) % (span + 1);
			});
			raf = requestAnimationFrame(step);
		};
		raf = requestAnimationFrame(step);
	}

	/** and the landing: staggered, eased, and quantised to whole rows on arrival */
	function settle() {
		const to = homes(st);
		const from = [...shift];
		const t0 = performance.now();
		const D = 820;
		const step = (now: number) => {
			const k = Math.min(1, (now - t0) / D);
			shift = from.map((f, i) => {
				const lane = Math.max(0, Math.min(1, (k - i * 0.1) / 0.8));
				const e = 1 - Math.pow(1 - lane, 3);
				return Math.round(f + (to[i] - f) * e);
			});
			if (k < 1) {
				raf = requestAnimationFrame(step);
			} else {
				shift = to;
				develop(1);
			}
		};
		raf = requestAnimationFrame(step);
	}

	/** the colour cross-fade, once the pile is actually seated */
	function develop(to: number) {
		cancelAnimationFrame(rafB);
		if (frozen()) {
			blend = to;
			return;
		}
		const from = blend;
		const t0 = performance.now();
		const step = (now: number) => {
			const k = Math.min(1, (now - t0) / 560);
			blend = from + (to - from) * (1 - Math.pow(1 - k, 3));
			if (k < 1) rafB = requestAnimationFrame(step);
		};
		rafB = requestAnimationFrame(step);
	}

	// Driven by the stage and nothing else. The reads inside are untracked because
	// every branch writes `shift`, and a tracked read of it would make each animation
	// frame re-enter the effect that started the animation.
	$effect(() => {
		const s = stage;
		untrack(() => {
			cancelAnimationFrame(raf);
			if (s === 'pass' || s === 'fail') {
				if (frozen()) {
					shift = homes(st);
					blend = 1;
				} else {
					settle();
				}
				return;
			}
			develop(0);
			if (s === 'idle') {
				shift = [0, 0, 0];
				return;
			}
			if (s === 'dealing' || frozen()) {
				shift = scattered();
				return;
			}
			hunt();
		});
	});

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
	const LAMP_RGB = hex2rgb(LAMP);
	const FAULT_RGB = hex2rgb(FAULT);
	const WHITE = [255, 255, 255];
	/**
	 * How far towards white a cell goes once n strips have lit it. The ground is
	 * dealt one cell to one strip, so in register almost every lit cell is n = 1 and
	 * the pile reads as a mosaic of three. The bright ones are the margins doubling
	 * up out of register, which is exactly the thing to make visible.
	 */
	const GLOW = [0, 0, 0.45, 0.8];

	/** the empty panel: a dim checker, so a register with no film in it still reads */
	const DIM = ['#0f141b', '#131922'];
	function ghost(ctx: CanvasRenderingContext2D, pitch: number) {
		ctx.globalAlpha = 0.55;
		for (let r = 0; r < st.pile; r++) {
			for (let c = 0; c < grid.cols; c++) {
				ctx.fillStyle = DIM[(r + c) & 1];
				ctx.fillRect(c * pitch, r * pitch, pitch - GAP, pitch - GAP);
			}
		}
		ctx.globalAlpha = 1;
	}

	function surface(cv: HTMLCanvasElement, w: number, h: number) {
		const dpr = window.devicePixelRatio || 1;
		cv.width = Math.round(w * dpr);
		cv.height = Math.round(h * dpr);
		cv.style.width = `${w}px`;
		cv.style.height = `${h}px`;
		const ctx = cv.getContext('2d');
		ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
		return ctx;
	}

	/**
	 * The pile: every strip at its current slide, nothing cropped. What is drawn is
	 * what the films are transmitting right now, not what they would say if they were
	 * already seated.
	 */
	function paintPile(cv: HTMLCanvasElement | null) {
		if (!cv) return;
		const ctx = surface(cv, W, H);
		if (!ctx) return;
		ctx.fillStyle = VOID;
		ctx.fillRect(0, 0, W, H);
		if (!sel.length) {
			ghost(ctx, PITCH);
			return;
		}
		for (let r = 0; r < st.pile; r++) {
			for (let c = 0; c < grid.cols; c++) {
				const by = sel.filter((k) => view[r * grid.cols + c] & (1 << k));
				if (!by.length) continue;
				// Every cell B lit, wherever it lit it. Its margin cells are doing their
				// job, so this reddens some ink that is not itself at fault — but a strip
				// that was not the one dealt is wrong as a whole, and colouring only the
				// cells that individually miss made the fault look like bad luck.
				const rogue = !pass && by.includes(ROGUE);
				const spread = by.map((k) => (k === ROGUE && rogue ? FAULT_RGB : HUE_RGB[k]));
				const avg = [0, 1, 2].map((ch) => spread.reduce((a, x) => a + x[ch], 0) / spread.length);
				const film = mix(avg, WHITE, GLOW[by.length]);
				ctx.fillStyle = rgb2hex(mix(film, rogue ? FAULT_RGB : LAMP_RGB, blend));
				ctx.fillRect(c * PITCH, r * PITCH, CELL, CELL);
			}
		}
	}

	/** One strip, drawn where it currently sits in the pile — film moving in a frame. */
	function paintStrip(cv: HTMLCanvasElement | null, i: number) {
		if (!cv) return;
		const ctx = surface(cv, SW, SH);
		if (!ctx) return;
		ctx.fillStyle = VOID;
		ctx.fillRect(0, 0, SW, SH);
		if (!shown[i]) {
			ghost(ctx, SP);
			return;
		}
		const hue = i === ROGUE && !pass ? FAULT : HUES[i];
		const drop = Math.max(0, Math.min(travel(st, i), Math.round(shift[i])));
		const strip = st.cells[i];
		for (let r = 0; r < st.pile; r++) {
			const sr = r - drop;
			const on = sr >= 0 && sr < st.heights[i];
			for (let c = 0; c < grid.cols; c++) {
				const l = on ? strip[sr * grid.cols + c] : 0;
				ctx.globalAlpha = l ? [0, 0.62, 0.76, 0.88, 1][l] : 1;
				ctx.fillStyle = l ? hue : on ? DIM[(r + c) & 1] : '#080b10';
				ctx.fillRect(c * SP, r * SP, SP - GAP, SP - GAP);
			}
		}
		ctx.globalAlpha = 1;
	}

	let pileCv = $state<HTMLCanvasElement | null>(null);
	let stripCv = $state<(HTMLCanvasElement | null)[]>([null, null, null]);

	$effect(() => {
		void [view, blend, sel, pass, PITCH];
		paintPile(pileCv);
	});
	$effect(() => {
		void [st, shift, shown, pass, SP];
		for (let i = 0; i < 3; i++) paintStrip(stripCv[i], i);
	});

	const digests = $derived([req, rsp, model]);
	const fmt = (h: string | null) => (h ? '0x' + h.slice(0, 12).toUpperCase() : '—');

	const note = $derived(
		stage === 'pass'
			? registered
				? 'in register — three thirds of one ground, and the word left black'
				: 'seating the strips'
			: stage === 'fail'
				? 'registered, but B was not the strip that was dealt — red is where it landed'
				: stage === 'searching'
					? 'proof in flight — the strips are hunting for the seat'
					: sel.length
						? 'dealt — three films on the table, out of register'
						: 'no request on the wire'
	);
</script>

<section class="border border-border bg-card">
	<div class="flex flex-wrap items-baseline justify-between gap-3 border-b border-border px-4 py-2">
		<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
			Fingerprint register · A + B + C, nothing cropped
		</span>
		<span
			class={cn(
				'font-mono text-[10px] tracking-[0.12em]',
				stage === 'fail'
					? 'text-fault'
					: stage === 'pass'
						? 'text-verified'
						: 'text-muted-foreground/70'
			)}
		>
			{note}
		</span>
	</div>

	<div class="flex flex-col items-center gap-3 overflow-x-auto p-4" bind:clientWidth={boxW}>
		<div
			class="relative shrink-0"
			style="width:{W}px;height:{H}px"
			role="img"
			aria-label="fingerprint register — {note}"
		>
			<div
				class="pointer-events-none absolute -inset-6 transition-opacity duration-700"
				style="opacity:{stage === 'pass'
					? 1
					: 0};background:radial-gradient(ellipse at center,color-mix(in oklab,var(--verified) 16%,transparent),transparent 70%)"
			></div>
			<div
				class="pointer-events-none absolute -inset-6 transition-opacity duration-700"
				style="opacity:{stage === 'fail'
					? 1
					: 0};background:radial-gradient(ellipse at center,color-mix(in oklab,var(--fault) 15%,transparent),transparent 68%)"
			></div>
			<canvas bind:this={pileCv} class="absolute top-0 left-0" aria-hidden="true"></canvas>
		</div>

		<div class="grid w-full shrink-0 grid-cols-3 gap-3" style="width:{W}px">
			{#each NAMES as name, i (name)}
				<div
					class={cn(
						'flex flex-col gap-1.5 transition-opacity duration-500',
						shown[i] ? 'opacity-100' : 'opacity-30'
					)}
				>
					<div class="flex items-baseline gap-2">
						<span
							class="size-2 shrink-0 self-center"
							style="background:{i === ROGUE && !pass ? FAULT : HUES[i]}"
						></span>
						<span class="font-mono text-[11px] font-semibold" style="color:{HUES[i]}">{name}</span>
						<span class="font-mono text-[9px] tracking-[0.14em] text-muted-foreground uppercase">
							{ROLES[i]}
						</span>
					</div>
					<div
						class="tabular font-mono text-[13px] leading-none font-semibold"
						style="color:{i === ROGUE && !pass ? FAULT : HUES[i]}"
					>
						{fmt(digests[i])}
					</div>
					<div class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground/70 uppercase">
						{SUBS[i]}{i === st.backing ? ' · backing, does not move' : ''}
					</div>
					<canvas bind:this={stripCv[i]} class="mt-0.5" aria-hidden="true"></canvas>
				</div>
			{/each}
		</div>
	</div>
</section>
