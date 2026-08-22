<script lang="ts">
	/**
	 * Interlock — hardware-attested inference.
	 *
	 * Driven by demo_server.py (interlock/app), which orchestrates a Raspberry Pi
	 * holding the certified wire and a Spark running the model behind a PolarFire
	 * FPGA that fingerprints every packet in both directions. Every value rendered
	 * here arrived over that wire. The only thing this file invents is the pacing.
	 */
	import FingerprintRegister from '$lib/components/fingerprint-register.svelte';
	import { cn } from '$lib/utils';
	import { io, type Socket } from 'socket.io-client';
	import { onDestroy, onMount } from 'svelte';

	type Verdict = { verdict: string; U: string; verify: string; keybind: string };
	type FpStage = 'hidden' | 'stacked' | 'register' | 'resolved' | 'clash';

	let socket: Socket;
	let connected = $state(false);
	let agentUp = $state(false);
	let wireOk = $state(false);
	let wireFault = $state('');
	let modelName = $state('');
	let modeText = $state('1 token-layer of ~460 · not a proof of the forward pass');
	let tampered = $state(false);
	let busy = $state(false);

	let caption = $state('Idle.');
	let detail = $state('Press RUN to send a request across the certified link.');
	let phase = $state<'idle' | 'req' | 'gen' | 'rsp' | 'prove' | 'done'>('idle');
	let hotFpga = $state(false);
	let hotSpark = $state(false);

	let pktX = $state(6);
	let pktLabel = $state('PROMPT');
	let pktEnc = $state(false);
	let pktShown = $state(false);

	let reqFp = $state<string | null>(null);
	let rspFp = $state<string | null>(null);
	let modelFp = $state<string | null>(null);
	let converge = $state(false);
	let answer = $state('');
	let verdict = $state<Verdict | null>(null);
	let elapsed = $state('');
	let trace = $state<string[]>([]);

	const short = (h: string | null, n = 8) => (h ? h.slice(0, n).toUpperCase() : '—');
	const log = (s: string) => (trace = [...trace.slice(-40), s]);

	let pending: Record<string, any> = {};
	let chain: Promise<unknown> = Promise.resolve();
	let generation = 0;
	const queue = (fn: () => Promise<void>) => (chain = chain.then(fn).catch(console.error));

	/** Sleep that resolves to false if a newer run started while we waited. */
	async function step(ms: number, gen: number) {
		await new Promise((r) => setTimeout(r, ms));
		return gen === generation;
	}

	function reset() {
		phase = 'idle';
		caption = 'Idle.';
		detail = 'Press RUN to send a request across the certified link.';
		hotFpga = hotSpark = false;
		pktShown = pktEnc = false;
		pktX = 6;
		reqFp = rspFp = null;
		converge = false;
		answer = '';
		verdict = null;
		elapsed = '';
		trace = [];
		tampered = false;
		busy = false;
	}

	async function runRequest(d: any, gen: number) {
		phase = 'req';
		pktLabel = 'PROMPT';
		pktEnc = false;
		pktX = 6;
		pktShown = true;
		caption = 'A request arrives.';
		detail = '';
		if (!(await step(750, gen))) return;

		pktEnc = true;
		pktLabel = 'CIPHERTEXT';
		caption = 'Sealed before it reaches the cable.';
		detail = `${d.n_tokens} tokens → ${(d.ct_in ?? '').length / 2} bytes · AES-128-GCM`;
		log(`SEAL   ${d.n_tokens} tok → ${(d.ct_in ?? '').length / 2}B`);
		if (!(await step(900, gen))) return;

		pktX = 38;
		hotFpga = true;
		if (!(await step(950, gen))) return;
		reqFp = d.request_digest ?? null;
		caption = 'The certifier fingerprints it in passing.';
		detail = `inbound byte-audit ${d.request_audit ? 'PASS' : 'FAIL'}`;
		log(`CERT   inbound  ${short(reqFp, 16)}`);
		if (!(await step(850, gen))) return;

		pktX = 79;
		hotFpga = false;
		hotSpark = true;
		if (!(await step(950, gen))) return;
		pktShown = false;
	}

	async function runResponse(d: any, text: string, gen: number) {
		phase = 'gen';
		caption = 'The datacenter runs the model and seals the answer.';
		detail = '';
		if (!(await step(800, gen))) return;

		phase = 'rsp';
		pktLabel = 'CIPHERTEXT';
		pktEnc = true;
		pktX = 79;
		pktShown = true;
		if (!(await step(550, gen))) return;
		pktX = 38;
		hotSpark = false;
		hotFpga = true;
		if (!(await step(950, gen))) return;

		rspFp = d.response_digest ?? null;
		caption = 'The output is fingerprinted too.';
		detail = `outbound byte-audit ${d.response_audit ? 'PASS' : 'FAIL'}`;
		log(`CERT   outbound ${short(rspFp, 16)}`);
		if (!(await step(850, gen))) return;

		pktX = 6;
		hotFpga = false;
		if (!(await step(950, gen))) return;
		pktEnc = false;
		pktLabel = 'PLAINTEXT';
		caption = 'Only the key holder can open it.';
		detail = '';
		if (!(await step(850, gen))) return;
		pktShown = false;
		answer = text;
		log(`OPEN   ${text}`);
	}

	async function runProve(gen: number) {
		phase = 'prove';
		hotSpark = true;
		caption = 'The datacenter proves the fingerprints came from the approved model.';
		detail = 'zero-knowledge — weights, prompt and answer all stay private';
		if (!(await step(1100, gen))) return;
	}

	async function runVerdict(d: any, gen: number) {
		converge = true;
		if (!(await step(1000, gen))) return;
		verdict = d.result as Verdict;
		elapsed = d.secs ? `${d.secs}s` : '';
		phase = 'done';
		hotSpark = false;
		const ok = verdict?.verdict === 'PASS';
		caption = ok ? 'The fingerprints match the model.' : 'The fingerprints do not match.';
		detail = ok
			? 'the certified ciphertext opens, under a pre-committed key, to the proven tokens'
			: 'the datacenter claimed an output the certifier never fingerprinted';
		log(`PROOF  ${verdict?.verdict}  verify=${verdict?.verify}  binding=${verdict?.keybind}`);
		busy = false;
	}

	onMount(() => {
		socket = io('/demo', { transports: ['websocket'] });
		socket.on('connect', () => (connected = true));
		socket.on('disconnect', () => (connected = false));
		socket.on('hello', (d: any) => {
			agentUp = !!d.agent;
			wireOk = !!d.wire;
			modelName = d.model ?? '';
			if (d.mode) modeText = d.mode;
			if (d.model_fp) modelFp = d.model_fp;
		});
		socket.on('wire:agent', (d: any) => {
			agentUp = !!d.up;
			if (!d.up) wireOk = false;
		});
		socket.on('wire:ready', () => {
			wireOk = true;
			wireFault = '';
			if (phase === 'idle') detail = 'Press RUN to send a request across the certified link.';
		});
		// The board goes quiet a few hours after power-up. Say so on screen rather
		// than letting someone press RUN and find out twelve seconds later.
		socket.on('wire:fault', (d: any) => {
			wireOk = false;
			wireFault = d?.error ?? 'no sync stream';
			caption = 'Wire fault.';
			detail = 'the interlock is not emitting sync — power-cycle it; this re-arms automatically';
		});
		socket.on('beat:armed', () => (tampered = true));
		socket.on('beat:reset', reset);
		socket.on('beat:start', () => {
			generation += 1; // orphans any in-flight animation from a previous run
			chain = Promise.resolve();
			reset();
			busy = true;
		});
		socket.on('beat:tokenized', (d: any) => (pending = { ...pending, ...d }));
		socket.on('beat:certified', (d: any) => (pending = { ...pending, ...d }));
		socket.on('beat:answer', (d: any) => {
			const gen = generation;
			queue(async () => {
				if (gen !== generation) return;
				await runRequest(pending, gen);
				await runResponse(pending, d.ok ? d.text : 'could not decrypt', gen);
				await runProve(gen);
			});
		});
		socket.on('beat:verdict', (d: any) => {
			if (d.model_fp) modelFp = d.model_fp;
			const gen = generation;
			queue(() => runVerdict(d, gen));
		});
		socket.on('beat:proof_status', (d: any) => {
			const m = String(d.line)
				.replace(/^\s*\[status\]\s*/, '')
				.trim();
			if (m) log(`PROVE  ${m.slice(0, 58)}`);
		});
		socket.on('beat:error', (d: any) => {
			caption = 'Fault.';
			detail = d.error ?? '';
			busy = false;
		});
	});
	onDestroy(() => socket?.disconnect());

	function start(tamper = false) {
		socket.emit('demo:reset');
		setTimeout(() => socket.emit(tamper ? 'demo:tamper' : 'demo:run', {}), 250);
	}

	// The register decks a grid as each digest lands, slides them together when the
	// proof is in flight, and only resolves once the server has ruled.
	const fpStage = $derived(
		(verdict
			? verdict.verdict === 'PASS'
				? 'resolved'
				: 'clash'
			: converge
				? 'register'
				: reqFp
					? 'stacked'
					: 'hidden') as FpStage
	);

	const lamps = $derived([
		{ k: 'LINK', on: connected, colour: 'bg-verified' },
		{ k: 'WIRE', on: wireOk, colour: 'bg-verified' },
		{ k: 'BUSY', on: busy, colour: 'bg-signal' },
		{ k: 'FAULT', on: verdict?.verdict === 'FAIL' || !!wireFault, colour: 'bg-fault' }
	]);
</script>

<div class="min-h-svh bg-background text-foreground">
	<!-- front panel -->
	<header class="border-b border-border">
		<div class="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-3">
			<div class="flex items-baseline gap-4">
				<span class="font-mono text-sm font-semibold tracking-[0.22em] text-foreground"
					>INTERLOCK</span
				>
				<span class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">
					network certifier · {modelName || 'no model'}
				</span>
			</div>
			<div class="flex items-center gap-5">
				{#each lamps as l (l.k)}
					<div class="flex items-center gap-1.5">
						<span
							class={cn(
								'size-1.5 rounded-full transition-all duration-300',
								l.on ? `${l.colour} shadow-[0_0_7px_currentColor]` : 'bg-border'
							)}
						></span>
						<span
							class={cn(
								'font-mono text-[9px] tracking-[0.14em]',
								l.on ? 'text-foreground' : 'text-muted-foreground/60'
							)}>{l.k}</span
						>
					</div>
				{/each}
			</div>
		</div>
	</header>

	<main class="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6">
		<div class="flex flex-wrap items-end justify-between gap-4">
			<h1 class="max-w-2xl text-2xl leading-tight font-medium tracking-tight text-balance">
				Is the datacenter running the correct model?
			</h1>
			<div class="flex gap-2">
				<button
					class="border border-border px-5 py-2 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase transition-colors hover:border-fault hover:text-fault disabled:pointer-events-none disabled:opacity-35"
					disabled={busy || !agentUp || !wireOk}
					onclick={() => start(true)}>Tamper</button
				>
				<button
					class="border border-signal bg-signal/10 px-6 py-2 font-mono text-[11px] tracking-[0.14em] text-signal uppercase transition-colors hover:bg-signal/20 disabled:pointer-events-none disabled:opacity-35"
					disabled={busy || !agentUp || !wireOk}
					onclick={() => start(false)}>Run</button
				>
			</div>
		</div>

		<!-- mode strip: never dismissible, fast mode must not read as a proof -->
		<div
			class={cn(
				'flex items-baseline gap-3 border-l-2 bg-card/60 px-4 py-2 font-mono text-[11px]',
				tampered ? 'border-l-fault text-fault' : 'border-l-caution text-muted-foreground'
			)}
		>
			<span class="shrink-0 tracking-[0.16em] uppercase"
				>{tampered ? 'Tampered' : 'Spot check'}</span
			>
			<span class="text-muted-foreground">
				{tampered
					? 'proving an output the certifier never fingerprinted — the key binding is full strength in every mode, so this fails every time'
					: modeText}
			</span>
		</div>

		<!-- scope -->
		<section class="relative h-[280px] overflow-hidden border border-border bg-card">
			<div
				class="pointer-events-none absolute inset-0 opacity-[0.55]"
				style="background-image:linear-gradient(to right,var(--grid) 1px,transparent 1px),linear-gradient(to bottom,var(--grid) 1px,transparent 1px);background-size:34px 34px"
			></div>

			<div class="absolute inset-x-[4%] top-[140px] h-px bg-border"></div>
			<div class="absolute inset-x-[4%] top-[140px] flex justify-between">
				{#each Array(29) as _, i (i)}<span class="h-1.5 w-px bg-border/70"></span>{/each}
			</div>

			<!-- certifier -->
			<div
				class={cn(
					'absolute top-[72px] left-[38%] flex h-[136px] w-[196px] -translate-x-1/2 flex-col items-center justify-center gap-2 border bg-background transition-all duration-300',
					hotFpga ? 'border-signal shadow-[0_0_26px_-4px_var(--signal)]' : 'border-border'
				)}
			>
				<div
					class={cn(
						'font-mono text-[10px] tracking-[0.16em] transition-colors',
						hotFpga ? 'text-signal' : 'text-muted-foreground'
					)}
				>
					FPGA
				</div>
				<div class="font-mono text-[15px] font-semibold tracking-[0.06em]">CERTIFIER</div>
				<div class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground uppercase">
					bump in the wire
				</div>
			</div>

			<!-- datacenter -->
			<div
				class={cn(
					'absolute top-[72px] left-[79%] flex h-[136px] w-[196px] -translate-x-1/2 flex-col items-center justify-center gap-2 border bg-background transition-all duration-300',
					verdict
						? verdict.verdict === 'PASS'
							? 'border-verified shadow-[0_0_30px_-4px_var(--verified)]'
							: 'border-fault shadow-[0_0_30px_-4px_var(--fault)]'
						: hotSpark
							? 'border-signal shadow-[0_0_26px_-4px_var(--signal)]'
							: 'border-border'
				)}
			>
				{#if verdict}
					{@const ok = verdict.verdict === 'PASS'}
					<div
						class={cn(
							'font-mono text-[10px] tracking-[0.16em]',
							ok ? 'text-verified' : 'text-fault'
						)}
					>
						{ok ? 'PROOF ACCEPTED' : 'PROOF REJECTED'}
					</div>
					<div
						class={cn(
							'font-mono text-[19px] font-bold tracking-[0.1em]',
							ok ? 'text-verified' : 'text-fault'
						)}
					>
						{ok ? 'VERIFIED' : 'REJECTED'}
					</div>
					<div class="tabular font-mono text-[9px] tracking-[0.1em] text-muted-foreground">
						U {verdict.U} · {elapsed}
					</div>
				{:else}
					<div
						class={cn(
							'font-mono text-[10px] tracking-[0.16em] transition-colors',
							hotSpark ? 'text-signal' : 'text-muted-foreground'
						)}
					>
						GPU
					</div>
					<div class="font-mono text-[15px] font-semibold tracking-[0.06em]">DATACENTER</div>
					<div class="font-mono text-[9px] tracking-[0.12em] text-muted-foreground uppercase">
						runs the model
					</div>
				{/if}
			</div>

			<!-- the one thing allowed to use the accent: traffic actually on the cable -->
			<div
				class={cn(
					'absolute top-[140px] -translate-x-1/2 -translate-y-1/2 border px-3 py-1.5 font-mono text-[10px] tracking-[0.12em] whitespace-nowrap transition-all duration-[900ms] ease-in-out',
					pktEnc
						? 'border-border bg-muted text-muted-foreground'
						: 'border-signal bg-signal/15 text-signal shadow-[0_0_18px_-3px_var(--signal)]',
					pktShown ? 'opacity-100' : 'opacity-0'
				)}
				style="left:{pktX}%"
			>
				{pktLabel}
			</div>

		</section>

		<FingerprintRegister
			req={reqFp}
			rsp={rspFp}
			model={phase === 'done' ? modelFp : null}
			stage={fpStage}
		/>

		<!-- readout -->
		<div class="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
			<div class="flex flex-col gap-2">
				<p class="text-[17px] leading-snug text-balance">{caption}</p>
				{#if detail}<p class="font-mono text-[11px] text-muted-foreground">{detail}</p>{/if}
				{#if answer}
					<div class="mt-1 border-l-2 border-signal/50 bg-card px-4 py-2.5 font-mono text-[13px]">
						{answer}
					</div>
				{/if}
			</div>
			<div
				class="tabular h-[132px] overflow-y-auto border border-border bg-card px-3 py-2 font-mono text-[10px] leading-[1.7] text-muted-foreground"
			>
				{#each trace as t, i (i)}<div>{t}</div>{:else}<div class="opacity-45">
						— no traffic —
					</div>{/each}
			</div>
		</div>
	</main>
</div>
