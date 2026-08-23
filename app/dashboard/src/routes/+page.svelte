<script lang="ts">
	/**
	 * Interlock — hardware-attested inference.
	 *
	 * Driven by demo_server.py (interlock/app), which orchestrates a Raspberry Pi
	 * holding the certified wire and a Spark running the model behind a PolarFire
	 * FPGA that fingerprints every packet in both directions. Every value rendered
	 * here arrived over that wire. The only thing this file invents is the pacing.
	 *
	 * ...unless the board is off, in which case it invents everything — see
	 * `simulate()`. That path exists so the demo survives a dead board, and it is
	 * labelled on the front panel, in the mode strip and in the trace, because a
	 * rehearsal that cannot be told apart from a run is worse than no rehearsal.
	 */
	import FingerprintRegister, { type Stage } from '$lib/components/fingerprint-register.svelte';
	import { cn } from '$lib/utils';
	import { resolve } from '$app/paths';
	import { io, type Socket } from 'socket.io-client';
	import { onDestroy, onMount } from 'svelte';

	type Verdict = { verdict: string; U: string; verify: string; keybind: string };

	let socket: Socket | undefined;
	let connected = $state(false);
	let agentUp = $state(false);
	let wireOk = $state(false);
	let wireFault = $state('');
	let modelName = $state('');
	let modeText = $state('1 token-layer of ~460 · not a proof of the forward pass');
	let busy = $state(false);

	/** the tamper switch: sticky, and only the operator flips it */
	let armed = $state(false);
	/** and whether the run being shown was actually the tampered one */
	let tampered = $state(false);
	/** force the simulator even with a healthy board */
	let simForce = $state(false);
	/** whether the run being shown came out of `simulate()` rather than the wire */
	let simRun = $state(false);

	let caption = $state('Idle.');
	let detail = $state('Press PROMPT to send a request across the certified link.');
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
	/** the proof is in flight: the register hunts for the seat until this clears */
	let proving = $state(false);
	let promptText = $state('');
	let answer = $state('');
	let verdict = $state<Verdict | null>(null);
	let elapsed = $state('');
	let trace = $state<string[]>([]);

	const short = (h: string | null, n = 8) => (h ? h.slice(0, n).toUpperCase() : '—');
	let tape = $state<HTMLDivElement | null>(null);
	// The trace box is four lines tall and a run writes a dozen, so without this the
	// newest line -- which is the one being talked about -- sits below the fold.
	const log = (s: string) => {
		trace = [...trace.slice(-40), s];
		queueMicrotask(() => tape?.scrollTo({ top: tape.scrollHeight }));
	};

	let pending: Record<string, any> = {};
	let chain: Promise<unknown> = Promise.resolve();
	let generation = 0;
	const queue = (fn: () => Promise<void>) => (chain = chain.then(fn).catch(console.error));

	/** Sleep that resolves to false if a newer run started while we waited. */
	async function step(ms: number, gen: number) {
		await new Promise((r) => setTimeout(r, ms));
		return gen === generation;
	}

	/** Everything a run puts on the screen. The switches are not part of a run. */
	function clearRun() {
		phase = 'idle';
		caption = 'Idle.';
		detail = 'Press PROMPT to send a request across the certified link.';
		hotFpga = hotSpark = false;
		pktShown = pktEnc = false;
		pktX = 6;
		reqFp = rspFp = null;
		proving = false;
		promptText = '';
		answer = '';
		verdict = null;
		elapsed = '';
		trace = [];
		tampered = false;
		simRun = false;
		busy = false;
	}

	/** the Reset button: the run, the switches, and anything armed on the server */
	function resetAll() {
		generation += 1; // orphans an in-flight animation, simulated or not
		chain = Promise.resolve();
		clearRun();
		armed = false;
		socket?.emit('demo:reset');
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
		// `proving` is what puts the register into its search, and it stays up until
		// the verdict lands however long that takes -- the animation is paced by the
		// prover, not by a timer that guesses at it.
		proving = true;
		caption = 'The datacenter proves the fingerprints came from the approved model.';
		detail = 'zero-knowledge — weights, prompt and answer all stay private';
		if (!(await step(1100, gen))) return;
	}

	async function runVerdict(d: any, gen: number) {
		// A verdict for a run that has already been superseded -- Reset pressed, or a
		// second Prompt -- must not repaint the panel it is no longer about.
		if (gen !== generation) return;
		verdict = d.result as Verdict;
		elapsed = d.secs ? `${d.secs}s` : '';
		phase = 'done';
		proving = false;
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
			if (phase === 'idle') detail = 'Press PROMPT to send a request across the certified link.';
		});
		// The board goes quiet a few hours after power-up. Say so on screen rather
		// than letting someone press PROMPT and find out twelve seconds later -- and
		// point at the simulator, which is the way out that does not need the board.
		socket.on('wire:fault', (d: any) => {
			wireOk = false;
			wireFault = d?.error ?? 'no sync stream';
			if (busy) return;
			caption = 'Wire fault.';
			detail =
				'the interlock is not emitting sync — power-cycle it; this re-arms automatically, ' +
				'and PROMPT runs the simulator in the meantime';
		});
		socket.on('beat:armed', () => (tampered = true));
		socket.on('beat:reset', clearRun);
		socket.on('beat:start', (d: any) => {
			generation += 1; // orphans any in-flight animation from a previous run
			chain = Promise.resolve();
			clearRun();
			promptText = d?.prompt ?? '';
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
			proving = false;
			busy = false;
			// A halt that did not take leaves the machine up, so the panel comes back
			// rather than sitting behind a "powering off" curtain that will never lift.
			goingDown = false;
		});
		socket.on('beat:shutdown', (d: any) => {
			goingDown = true;
			log(`HALT   ${d?.what ?? 'power off'}`);
		});
	});
	onDestroy(() => socket?.disconnect());

	// ── running it ─────────────────────────────────────────────────────────────
	/** the wire is only live when all three of these hold */
	const liveWire = $derived(connected && agentUp && wireOk);
	const simMode = $derived(simForce || !liveWire);

	function start() {
		if (busy || goingDown) return;
		if (simMode) {
			simulate(armed);
			return;
		}
		socket?.emit('demo:reset');
		setTimeout(() => socket?.emit(armed ? 'demo:tamper' : 'demo:run', {}), 250);
	}

	// ── the simulator ──────────────────────────────────────────────────────────
	/**
	 * A run with no hardware in it.
	 *
	 * The board goes quiet a few hours after power-up and the Pi has to be on the
	 * Spark's AP, so there are plenty of ways to arrive at a demo with nothing on the
	 * wire. This drives the same four beat functions the socket drives, on the same
	 * pacing, so what is rehearsed is what will run -- and it fabricates its digests
	 * rather than replaying a captured pair, because a recording of a real run is
	 * exactly the thing that could be passed off as one.
	 *
	 * It is never silent about itself: the SIM lamp, the mode strip, the trace's first
	 * line and the verdict's own footnote all say so, and none of them is dismissible.
	 */
	const SIM_PROMPT = 'Question: What is the capital of France?\nAnswer:';
	const SIM_ANSWER = 'Paris';
	const SIM_STATUS = [
		'loading proving key',
		'committing to the token layer',
		'weld: binding ciphertext to the proven tokens',
		'B1/B2 key binding at full strength',
		'folding'
	];

	/**
	 * Forty hex characters that behave like a digest: dependent on everything handed
	 * in, and different every run. FNV-1a into xorshift32 -- crypto.subtle is not
	 * available here, the demo being served over plain http on a LAN address, and
	 * this has no security job to do anyway.
	 */
	function fauxDigest(s: string) {
		let h = 0x811c9dc5 >>> 0;
		for (let i = 0; i < s.length; i++) {
			h ^= s.charCodeAt(i);
			h = Math.imul(h, 0x01000193) >>> 0;
		}
		let out = '';
		for (let i = 0; i < 40; i++) {
			h ^= h << 13;
			h >>>= 0;
			h ^= h >>> 17;
			h ^= h << 5;
			h >>>= 0;
			out += '0123456789abcdef'[h & 15];
		}
		return out;
	}

	function simulate(tamper: boolean) {
		generation += 1;
		const gen = generation;
		chain = Promise.resolve();
		clearRun();
		busy = true;
		simRun = true;
		tampered = tamper;
		promptText = SIM_PROMPT;
		if (!modelFp) modelFp = fauxDigest('simulated-weights');

		const nonce = `${Date.now()}:${Math.random()}`;
		const d = {
			n_tokens: 11,
			ct_in: '0'.repeat(2 * 108),
			request_digest: fauxDigest(`in:${SIM_PROMPT}:${nonce}`),
			response_digest: fauxDigest(`out:${SIM_ANSWER}:${nonce}`),
			request_audit: true,
			response_audit: true
		};

		queue(async () => {
			if (gen !== generation) return;
			log('SIM    simulated board — nothing below was certified or proven');
			await runRequest(d, gen);
			await runResponse(d, SIM_ANSWER, gen);
			await runProve(gen);
			for (const line of SIM_STATUS) {
				if (!(await step(1150, gen))) return;
				log(`PROVE  ${line}`);
			}
			if (!(await step(900, gen))) return;
			await runVerdict(
				{
					result: tamper
						? { verdict: 'FAIL', U: '2^-40', verify: 'REJECT', keybind: 'MISMATCH' }
						: { verdict: 'PASS', U: '2^-40', verify: 'ACCEPT', keybind: 'OK' },
					secs: 24.6
				},
				gen
			);
			log('SIM    end of simulated run');
		});
	}

	// ── power ──────────────────────────────────────────────────────────────────
	/**
	 * Two presses, and the second one only counts inside four seconds. This kills the
	 * Pi and then the Spark -- including the server that is serving this page, so
	 * there is no undo and no way back except walking over to the hardware.
	 */
	let armDown = $state(false);
	let downTimer = 0;
	let goingDown = $state(false);

	function shutdown() {
		if (!armDown) {
			armDown = true;
			clearTimeout(downTimer);
			downTimer = window.setTimeout(() => (armDown = false), 4000);
			return;
		}
		clearTimeout(downTimer);
		armDown = false;
		goingDown = true;
		// The token is checked server-side, so a stray `demo:shutdown` from a console
		// or a replayed frame cannot power the rack off by itself.
		socket?.emit('demo:shutdown', { confirm: 'POWER OFF' });
	}

	// ── the register ───────────────────────────────────────────────────────────
	// Three films: the two the certifier printed on the way past, and the model
	// commitment, which is known before anything is sent. They land as the run does,
	// hunt for their seat while the proof is in flight, and settle when it rules.
	const fpStage = $derived(
		(verdict
			? verdict.verdict === 'PASS'
				? 'pass'
				: 'fail'
			: proving
				? 'searching'
				: reqFp
					? 'dealing'
					: 'idle') as Stage
	);

	const lamps = $derived([
		{ k: 'LINK', on: connected, colour: 'bg-verified' },
		{ k: 'WIRE', on: wireOk, colour: 'bg-verified' },
		{ k: 'SIM', on: simMode, colour: 'bg-caution' },
		{ k: 'BUSY', on: busy, colour: 'bg-signal' },
		{ k: 'FAULT', on: verdict?.verdict === 'FAIL' || !!wireFault, colour: 'bg-fault' }
	]);
</script>

{#snippet toggle(on: boolean, label: string, tone: 'fault' | 'caution', click: () => void)}
	<button
		type="button"
		role="switch"
		aria-checked={on}
		aria-label={label}
		onclick={click}
		disabled={goingDown}
		class="flex items-center gap-2.5 disabled:pointer-events-none disabled:opacity-35"
	>
		<span
			class={cn(
				'relative h-4 w-8 border transition-colors duration-200',
				on
					? tone === 'fault'
						? 'border-fault bg-fault/20'
						: 'border-caution bg-caution/20'
					: 'border-border bg-muted'
			)}
		>
			<span
				class={cn(
					'absolute top-[1px] size-[12px] transition-all duration-200',
					on
						? `left-[17px] ${tone === 'fault' ? 'bg-fault' : 'bg-caution'}`
						: 'left-[1px] bg-muted-foreground/70'
				)}
			></span>
		</span>
		<span
			class={cn(
				'font-mono text-[11px] tracking-[0.14em] uppercase transition-colors',
				on
					? tone === 'fault'
						? 'text-fault'
						: 'text-caution'
					: 'text-muted-foreground hover:text-foreground'
			)}
		>
			{label}
		</span>
	</button>
{/snippet}

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
				<a
					href={resolve('/lab')}
					class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground/70 uppercase underline-offset-4 hover:text-foreground hover:underline"
				>
					share bench →
				</a>
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
				<button
					class={cn(
						'border px-3 py-1 font-mono text-[9px] tracking-[0.14em] uppercase transition-colors',
						armDown
							? 'border-fault bg-fault/20 text-fault'
							: 'border-border text-muted-foreground/70 hover:border-fault hover:text-fault'
					)}
					disabled={goingDown}
					onclick={shutdown}
				>
					{armDown ? 'confirm · powers off both' : 'shut down'}
				</button>
			</div>
		</div>
	</header>

	<main class="mx-auto flex max-w-7xl flex-col gap-4 px-6 py-6">
		<div class="flex flex-wrap items-end justify-between gap-4">
			<h1 class="max-w-2xl text-2xl leading-tight font-medium tracking-tight text-balance">
				Is the datacenter running the correct model?
			</h1>
			<div class="flex flex-wrap items-center gap-5">
				{@render toggle(armed, 'Tamper', 'fault', () => (armed = !armed))}
				{@render toggle(simForce || !liveWire, 'Simulate', 'caution', () => {
					// off is only offerable when there is a wire to fall back to
					if (liveWire) simForce = !simForce;
				})}
				<button
					class="border border-border px-4 py-2 font-mono text-[11px] tracking-[0.14em] text-muted-foreground uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
					disabled={goingDown}
					onclick={resetAll}>Reset</button
				>
				<button
					class="border border-signal bg-signal/10 px-6 py-2 font-mono text-[11px] tracking-[0.14em] text-signal uppercase transition-colors hover:bg-signal/20 disabled:pointer-events-none disabled:opacity-35"
					disabled={busy || goingDown}
					onclick={start}>Prompt</button
				>
			</div>
		</div>

		<!-- mode strip: never dismissible. Neither fast mode nor the simulator may be
		     allowed to read as a proof, and the simulator outranks the tamper here
		     because "none of this happened" is the more important of the two. -->
		<div
			class={cn(
				'flex items-baseline gap-3 border-l-2 bg-card/60 px-4 py-2 font-mono text-[11px]',
				simRun || simMode
					? 'border-l-caution text-caution'
					: tampered
						? 'border-l-fault text-fault'
						: 'border-l-caution text-muted-foreground'
			)}
		>
			<span class="shrink-0 tracking-[0.16em] uppercase">
				{simRun || simMode ? 'Simulated' : tampered ? 'Tampered' : 'Spot check'}
			</span>
			<span class="text-muted-foreground">
				{#if simRun || simMode}
					no hardware in the loop — the digests, the answer and the verdict on this screen are
					fabricated by the browser{armed ? ', with the tamper switch armed' : ''}. Nothing here was
					certified, and nothing here was proven.
				{:else if tampered}
					proving an output the certifier never fingerprinted — the key binding is full strength in
					every mode, so this fails every time
				{:else}
					{modeText}
				{/if}
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
						U {verdict.U} · {elapsed}{simRun ? ' · simulated' : ''}
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

		<FingerprintRegister req={reqFp} rsp={rspFp} model={modelFp} stage={fpStage} />

		<!-- readout -->
		<div class="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
			<div class="flex flex-col gap-2">
				<p class="text-[17px] leading-snug text-balance">{caption}</p>
				{#if detail}<p class="font-mono text-[11px] text-muted-foreground">{detail}</p>{/if}
				{#if promptText}
					<div
						class="mt-1 border-l-2 border-border bg-card px-4 py-2.5 font-mono text-[12px] whitespace-pre-line text-muted-foreground"
					>
						{promptText}
					</div>
				{/if}
				{#if answer}
					<div class="border-l-2 border-signal/50 bg-card px-4 py-2.5 font-mono text-[13px]">
						{answer}
					</div>
				{/if}
			</div>
			<div
				bind:this={tape}
				class="tabular h-[132px] overflow-y-auto border border-border bg-card px-3 py-2 font-mono text-[10px] leading-[1.7] text-muted-foreground"
			>
				{#each trace as t, i (i)}<div>{t}</div>{:else}<div class="opacity-45">
						— no traffic —
					</div>{/each}
			</div>
		</div>
	</main>

	{#if goingDown}
		<div
			class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-3 bg-background/95 backdrop-blur-sm"
		>
			<span class="font-mono text-[11px] tracking-[0.2em] text-fault uppercase">Powering off</span>
			<p class="max-w-md text-center text-sm text-muted-foreground">
				The Pi and the Spark are halting. This page is served by the Spark, so it will stop
				answering — bring both back up at the hardware.
			</p>
		</div>
	{/if}
</div>
