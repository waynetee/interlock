<script lang="ts">
	/**
	 * /lab — testbed for the fingerprint register.
	 *
	 * Drives the register through every state with no hardware, no wire and no model,
	 * so the animation can be looked at and argued about on its own. Not linked from
	 * anywhere; the demo page never routes here.
	 */
	import FingerprintRegister from '$lib/components/fingerprint-register.svelte';
	import { onMount } from 'svelte';
	import {
		build,
		stats,
		MSG_COLS,
		MSG_ROWS,
		BLK,
		ROWS,
		COLS,
		LIT,
		PER,
		type Polarity
	} from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';

	type Stage = 'hidden' | 'stacked' | 'register' | 'resolved' | 'clash';

	const rand = () =>
		Array.from({ length: 40 }, () => '0123456789abcdef'[(Math.random() * 16) | 0]).join('');

	let req = $state('4f74f5c6b3a19e02d81c7745aa30bb61c4e9f0d2');
	let rsp = $state('a1b93de77c04582fe61099ab3d5c77e0114fa2b8');
	let model = $state('6e6001da2106d4757498752a021df6c2bdc332c6');
	let stage = $state<Stage>('resolved');
	let only = $state<number | null>(null);
	let polarity = $state<Polarity>('cutout');
	let readout = $state<'ink' | 'light'>('ink');
	let speed = $state(1);
	let playing = $state(false);

	// what the register is actually handed at each point in a real run
	const shown = $derived({
		req: stage === 'hidden' ? null : req,
		rsp: stage === 'hidden' ? null : rsp,
		model: stage === 'hidden' || stage === 'stacked' || stage === 'register' ? null : model
	});

	const measured = $derived.by(() => {
		const s = build(req, rsp, model, stage !== 'clash', polarity);
		return stats(s);
	});

	let gen = 0;
	async function hold(ms: number, g: number) {
		await new Promise((r) => setTimeout(r, ms / speed));
		return g === gen;
	}

	async function play(outcome: 'pass' | 'fail') {
		const g = ++gen;
		playing = true;
		only = null;
		stage = 'hidden';
		if (!(await hold(500, g))) return;
		stage = 'stacked'; // input + output fingerprints deck as the wire certifies them
		if (!(await hold(2200, g))) return;
		stage = 'register'; // proof in flight: the two wire shares slide together
		if (!(await hold(1400, g))) return;
		stage = outcome === 'pass' ? 'resolved' : 'clash'; // the model share lands
		playing = false;
	}

	function set(s: Stage) {
		gen++;
		playing = false;
		stage = s;
	}

	// ?stage=&polarity=&only= so a state can be linked, or screenshotted headlessly
	onMount(() => {
		const q = new URLSearchParams(location.search);
		const st = q.get('stage');
		const po = q.get('polarity');
		const on = q.get('only');
		if (st && STAGES.includes(st as Stage)) stage = st as Stage;
		if (po === 'solid' || po === 'cutout') polarity = po;
		const rd = q.get('readout');
		if (rd === 'ink' || rd === 'light') readout = rd;
		if (on !== null) only = on === 'all' ? null : Number(on);
	});

	const STAGES: Stage[] = ['hidden', 'stacked', 'register', 'resolved', 'clash'];
	const pct = (n: number) => `${(n * 100).toFixed(1)}%`;
</script>

<svelte:head><title>Fingerprint register — testbed</title></svelte:head>

<div class="min-h-svh bg-background text-foreground">
	<header class="border-b border-border">
		<div class="mx-auto flex max-w-7xl items-baseline justify-between gap-4 px-6 py-3">
			<span class="font-mono text-sm font-semibold tracking-[0.22em]">INTERLOCK · LAB</span>
			<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
				fingerprint register testbed · no hardware attached
			</span>
		</div>
	</header>

	<main class="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6">
		<FingerprintRegister
			req={shown.req}
			rsp={shown.rsp}
			model={shown.model}
			{stage}
			{only}
			{polarity}
			{readout}
		/>

		<div class="grid gap-4 lg:grid-cols-[1.55fr_1fr]">
			<!-- controls -->
			<div class="flex flex-col gap-4 border border-border bg-card p-4">
				<div class="flex flex-wrap items-center gap-2">
					<span class="w-24 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
						Sequence
					</span>
					<button
						class="border border-signal bg-signal/10 px-4 py-1.5 font-mono text-[11px] tracking-[0.14em] text-signal uppercase transition-colors hover:bg-signal/20"
						onclick={() => play('pass')}>Play pass</button
					>
					<button
						class="border border-border px-4 py-1.5 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase transition-colors hover:border-fault hover:text-fault"
						onclick={() => play('fail')}>Play fail</button
					>
					<label class="ml-2 flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
						SPEED
						<input type="range" min="0.25" max="3" step="0.25" bind:value={speed} class="w-28" />
						<span class="tabular w-8">{speed}×</span>
					</label>
					{#if playing}<span class="font-mono text-[10px] text-signal">running…</span>{/if}
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span class="w-24 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
						Stage
					</span>
					{#each STAGES as s (s)}
						<button
							class={cn(
								'border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors',
								stage === s
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => set(s)}>{s}</button
						>
					{/each}
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span class="w-24 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
						Polarity
					</span>
					{#each [{ v: 'cutout', l: 'Word lit' }, { v: 'solid', l: 'Word dark' }] as o (o.v)}
						<button
							class={cn(
								'border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors',
								polarity === o.v
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => (polarity = o.v as Polarity)}>{o.l}</button
						>
					{/each}
					<span class="font-mono text-[10px] text-muted-foreground/70">
						whichever side is solid is the exact one; the other carries the texture
					</span>
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span class="w-24 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
						Readout
					</span>
					{#each [{ v: 'ink', l: 'Through ink' }, { v: 'light', l: 'Emitted' }] as o (o.v)}
						<button
							class={cn(
								'border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors',
								readout === o.v
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => (readout = o.v as 'ink' | 'light')}>{o.l}</button
						>
					{/each}
					<span class="font-mono text-[10px] text-muted-foreground/70">
						same union either way — darken through ink, or lighten as emitted light
					</span>
				</div>

				<div class="flex flex-wrap items-center gap-2">
					<span class="w-24 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
						Isolate
					</span>
					{#each ['all', 'input', 'output', 'model'] as label, i (label)}
						<button
							class={cn(
								'border px-3 py-1.5 font-mono text-[11px] tracking-[0.12em] uppercase transition-colors',
								(only === null ? 0 : only + 1) === i
									? 'border-foreground text-foreground'
									: 'border-border text-muted-foreground hover:text-foreground'
							)}
							onclick={() => (only = i === 0 ? null : i - 1)}>{label}</button
						>
					{/each}
					<span class="font-mono text-[10px] text-muted-foreground/70">
						one share alone is uniform noise — that is the point
					</span>
				</div>

				<div class="flex flex-col gap-2">
					{#each [{ k: 'req', label: 'Input digest' }, { k: 'rsp', label: 'Output digest' }, { k: 'model', label: 'Model digest' }] as f (f.k)}
						<div class="flex items-center gap-2">
							<span
								class="w-24 shrink-0 font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase"
							>
								{f.label}
							</span>
							{#if f.k === 'req'}
								<input bind:value={req} class="lab-hex" spellcheck="false" />
							{:else if f.k === 'rsp'}
								<input bind:value={rsp} class="lab-hex" spellcheck="false" />
							{:else}
								<input bind:value={model} class="lab-hex" spellcheck="false" />
							{/if}
						</div>
					{/each}
					<div class="flex gap-2 pl-26">
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
							onclick={() => (rsp = rand())}>New output digest</button
						>
					</div>
				</div>
			</div>

			<!-- measurements, not claims -->
			<div class="min-w-[290px] border border-border bg-card p-4 font-mono text-[11px]">
				<div class="mb-3 text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
					Measured on the shares above
				</div>
				<dl class="tabular flex flex-col gap-1.5">
					{#each measured.density as d, i (i)}
						<div class="flex justify-between gap-6">
							<dt class="text-muted-foreground">share {i + 1} density</dt>
							<dd class={Math.abs(d - LIT / PER) < 0.0005 ? 'text-verified' : 'text-caution'}>
								{pct(d)}
							</dd>
						</div>
					{/each}
					<div class="my-1 h-px bg-border"></div>
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">union · inside letters</dt>
						<dd class={measured.letters > measured.field ? 'text-verified' : ''}>
							{pct(measured.letters)}
						</dd>
					</div>
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">union · outside letters</dt>
						<dd class={measured.field > measured.letters ? 'text-verified' : ''}>
							{pct(measured.field)}
						</dd>
					</div>
					<div class="flex justify-between gap-6">
						<dt class="text-muted-foreground">contrast</dt>
						<dd
							class={measured.field - measured.letters > 0.2 ? 'text-verified' : 'text-fault'}
						>
							{pct(Math.abs(measured.field - measured.letters))}
						</dd>
					</div>
					<div class="my-1 h-px bg-border"></div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>message</dt>
						<dd>{MSG_ROWS} × {MSG_COLS}</dd>
					</div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>rendered</dt>
						<dd>{ROWS} × {COLS} ({BLK}× expansion)</dd>
					</div>
					<div class="flex justify-between gap-6 text-muted-foreground/70">
						<dt>lit per block</dt>
						<dd>{LIT} of {PER}</dd>
					</div>
				</dl>
				<p class="mt-3 leading-relaxed text-muted-foreground/70">
					Every share is {pct(LIT / PER)} dense whatever the digests are. Change one above and
					watch the texture change while the densities do not.
				</p>
			</div>
		</div>
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
	.lab-hex:focus {
		outline: 1px solid var(--ring);
		outline-offset: -1px;
	}
</style>
