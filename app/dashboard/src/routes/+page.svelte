<script lang="ts">
	/**
	 * Interlock — the case.
	 *
	 * Driven by demo_server.py (interlock/app), which orchestrates a Raspberry Pi
	 * holding the certified wire and a Spark running the model behind a PolarFire
	 * FPGA that fingerprints every packet in both directions. Every value rendered
	 * here arrived over that wire. The only thing this file invents is the pacing.
	 *
	 * ...unless the board is off, in which case it invents everything — see
	 * `simulate()`. That path exists so the demo survives a dead board, and it says
	 * so on screen in the one strip that is never dismissible, because a rehearsal
	 * that cannot be told apart from a run is worse than no rehearsal.
	 *
	 * WHO IS READING THIS. A panel in the lid of a case, seen standing up from a few
	 * feet by someone who has not been briefed. That sets every rule below: one
	 * screen and no scroll, type sized off the viewport, one sentence at a time, and
	 * no term that would need a footnote. The numbers an engineer wants — the byte
	 * audits, the soundness bound, the prover's own status lines — are not gone; they
	 * are on the console and in /lab. They are just not on the lid.
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
	/** the server's own mode label, kept verbatim for the console and the tooltip */
	let modeRaw = $state('spot check');
	let busy = $state(false);

	/** the tamper switch: sticky, and only the operator flips it */
	let armed = $state(false);
	/** and whether the run being shown was actually the tampered one */
	let tampered = $state(false);
	/** force the simulator even with a healthy board */
	let simForce = $state(false);
	/** whether the run being shown came out of `simulate()` rather than the wire */
	let simRun = $state(false);

	let caption = $state('Ready — press PROMPT to send a question.');
	let phase = $state<'idle' | 'req' | 'gen' | 'rsp' | 'prove' | 'done'>('idle');
	let hotFpga = $state(false);
	let hotSpark = $state(false);

	/** where the packet is, across the cable: your machine, the checker, the far end */
	const STOP = [16, 50, 84];
	let pktX = $state(STOP[0]);
	let pktLabel = $state('QUESTION');
	let pktSealed = $state(false);
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

	const short = (h: string | null, n = 8) => (h ? h.slice(0, n).toUpperCase() : '—');
	/**
	 * The run's narration, on the console rather than on the lid. The status tape
	 * this used to paint was the densest thing on the screen and the least legible
	 * from three feet; an operator who wants it can open devtools, and /lab has the
	 * measurements in full.
	 */
	const log = (s: string) => console.debug('[interlock]', s);

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
		caption = 'Ready — press PROMPT to send a question.';
		hotFpga = hotSpark = false;
		pktShown = pktSealed = false;
		pktX = STOP[0];
		reqFp = rspFp = null;
		proving = false;
		promptText = '';
		answer = '';
		verdict = null;
		elapsed = '';
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
		pktLabel = 'QUESTION';
		pktSealed = false;
		pktX = STOP[0];
		pktShown = true;
		caption = 'A question leaves your machine.';
		if (!(await step(750, gen))) return;

		pktSealed = true;
		pktLabel = 'SEALED';
		caption = 'It is locked before it touches the cable.';
		log(`SEAL   ${d.n_tokens} tok → ${(d.ct_in ?? '').length / 2}B`);
		if (!(await step(900, gen))) return;

		pktX = STOP[1];
		hotFpga = true;
		if (!(await step(950, gen))) return;
		reqFp = d.request_digest ?? null;
		caption = 'The checker takes its fingerprint on the way past.';
		log(`CERT   inbound  ${short(reqFp, 16)} audit=${d.request_audit ? 'PASS' : 'FAIL'}`);
		if (!(await step(950, gen))) return;

		pktX = STOP[2];
		hotFpga = false;
		hotSpark = true;
		if (!(await step(950, gen))) return;
		pktShown = false;
	}

	async function runResponse(d: any, text: string, gen: number) {
		phase = 'gen';
		caption = 'The datacenter runs the model and locks the answer.';
		if (!(await step(1100, gen))) return;

		phase = 'rsp';
		pktLabel = 'SEALED';
		pktSealed = true;
		pktX = STOP[2];
		pktShown = true;
		if (!(await step(550, gen))) return;
		pktX = STOP[1];
		hotSpark = false;
		hotFpga = true;
		if (!(await step(950, gen))) return;

		rspFp = d.response_digest ?? null;
		caption = 'The answer is fingerprinted too.';
		log(`CERT   outbound ${short(rspFp, 16)} audit=${d.response_audit ? 'PASS' : 'FAIL'}`);
		if (!(await step(950, gen))) return;

		pktX = STOP[0];
		hotFpga = false;
		if (!(await step(950, gen))) return;
		pktSealed = false;
		pktLabel = 'ANSWER';
		caption = 'Only your machine holds the key that opens it.';
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
		caption = 'Now the datacenter has to prove those fingerprints came from the promised model.';
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
		caption = ok
			? 'It did. The three fingerprints line up.'
			: 'It could not. That answer never went past the checker.';
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
			if (d.mode) modeRaw = d.mode;
			if (d.model_fp) modelFp = d.model_fp;
		});
		socket.on('wire:agent', (d: any) => {
			agentUp = !!d.up;
			if (!d.up) wireOk = false;
		});
		socket.on('wire:ready', () => {
			wireOk = true;
			wireFault = '';
		});
		// The board goes quiet a few hours after power-up. The strip says so, and the
		// simulator picks itself up, so nobody presses PROMPT and finds out twelve
		// seconds later in front of an audience.
		socket.on('wire:fault', (d: any) => {
			wireOk = false;
			wireFault = d?.error ?? 'no sync stream';
			log(`FAULT  ${wireFault}`);
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
				await runResponse(pending, d.ok ? d.text : 'could not open it', gen);
				await runProve(gen);
			});
		});
		socket.on('beat:verdict', (d: any) => {
			if (d.model_fp) modelFp = d.model_fp;
			const gen = generation;
			queue(() => runVerdict(d, gen));
		});
		socket.on('beat:proof_status', (d: any) => log(`PROVE  ${String(d.line).trim()}`));
		socket.on('beat:error', (d: any) => {
			caption = 'Something went wrong. Press RESET and try again.';
			log(`ERROR  ${d.error ?? ''}`);
			proving = false;
			busy = false;
			// A halt that did not take leaves the machine up, so the panel comes back
			// rather than sitting behind a "powering off" curtain that will never lift.
			goingDown = false;
		});
		socket.on('beat:shutdown', () => (goingDown = true));
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
	 * Spark's AP, so there are plenty of ways to open the case and find nothing on
	 * the wire. This drives the same four beat functions the socket drives, on the
	 * same pacing, so what is rehearsed is what will run -- and it fabricates its
	 * digests rather than replaying a captured pair, because a recording of a real
	 * run is exactly the thing that could be passed off as one.
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
		});
	}

	// ── power ──────────────────────────────────────────────────────────────────
	/**
	 * Two presses, and the second one only counts inside four seconds. This kills the
	 * Pi and then the Spark -- including the server that is serving this page, so
	 * there is no undo and no way back except opening the case.
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
	// Three sheets: the two the checker printed on the way past, and the model's own,
	// which is fixed before anything is sent. They land as the run does, hunt for
	// their seat while the proof is in flight, and settle when it rules.
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

	// ── the one strip that is never dismissible ────────────────────────────────
	/**
	 * What an audience has a right to know before they believe the screen, in plain
	 * words and at reading size. The simulator outranks the tamper because "none of
	 * this happened" is the more important of the two.
	 *
	 * The mode line is DERIVED from the server's own label rather than written here,
	 * so a server that switches out of the subsampled prover cannot leave the lid
	 * claiming a spot check -- or, worse, leave a spot check unlabelled. The raw
	 * label rides along as the strip's tooltip for whoever is running the demo.
	 */
	const banner = $derived(
		simRun || simMode
			? {
					tag: 'Simulated',
					tone: 'caution' as const,
					say: `no hardware connected — everything on this screen is made up by the browser${armed ? ', with the tamper switch on' : ''}`
				}
			: tampered
				? {
						tag: 'Tampered',
						tone: 'fault' as const,
						say: 'the datacenter is claiming an answer the checker never saw — this fails every time'
					}
				: /spot check/i.test(modeRaw)
					? {
							tag: 'Spot check',
							tone: 'caution' as const,
							say: 'one slice of the answer is proved, not the whole run'
						}
					: { tag: 'Live', tone: 'ok' as const, say: modeRaw }
	);

	/** the prompt without its scaffolding, so the payoff reads as a question */
	const asked = $derived(
		promptText
			.replace(/^\s*Question:\s*/i, '')
			.replace(/\s*Answer:\s*$/i, '')
			.trim()
	);
	/** the far end is doing something you cannot see: say so with a sweep, not a word */
	const working = $derived(phase === 'gen' || phase === 'prove');
	/** and your own machine lights up for the two moments the key is in use */
	const hotHome = $derived(pktShown && pktX === STOP[0]);
	const TONE = {
		ok: { bar: 'border-l-verified', text: 'text-verified' },
		caution: { bar: 'border-l-caution', text: 'text-caution' },
		fault: { bar: 'border-l-fault', text: 'text-fault' }
	};
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
				'relative h-[1.5em] w-[2.9em] border text-[clamp(0.7rem,0.85vw,1rem)] transition-colors duration-200',
				on
					? tone === 'fault'
						? 'border-fault bg-fault/20'
						: 'border-caution bg-caution/20'
					: 'border-border bg-muted'
			)}
		>
			<span
				class={cn(
					'absolute top-[0.13em] size-[1.2em] transition-all duration-200',
					on
						? `left-[1.57em] ${tone === 'fault' ? 'bg-fault' : 'bg-caution'}`
						: 'left-[0.13em] bg-muted-foreground/70'
				)}
			></span>
		</span>
		<span
			class={cn(
				't-tag font-mono uppercase transition-colors',
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

{#snippet station(left: number, name: string, sub: string, hot: boolean)}
	<div
		class={cn(
			'absolute top-[6%] flex h-[56%] w-[clamp(140px,16vw,260px)] -translate-x-1/2 flex-col items-center justify-center gap-1 overflow-hidden border bg-background transition-all duration-300',
			hot ? 'border-signal shadow-[0_0_30px_-4px_var(--signal)]' : 'border-border'
		)}
		style="left:{left}%"
	>
		<div class="t-body font-mono font-semibold tracking-[0.05em]">{name}</div>
		<div class="t-tag px-2 text-center font-mono leading-tight text-muted-foreground uppercase">
			{sub}
		</div>
	</div>
{/snippet}

<div class="flex h-svh flex-col overflow-hidden bg-background text-foreground">
	<!-- front panel -->
	<header class="flex shrink-0 items-center justify-between gap-4 border-b border-border px-6 py-2">
		<span class="t-body font-mono font-semibold tracking-[0.24em]">INTERLOCK</span>
		<div class="flex items-center gap-4">
			<a
				href={resolve('/lab')}
				class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground/40 uppercase hover:text-foreground"
				>bench</a
			>
			<button
				class={cn(
					't-tag border px-3 py-1 font-mono uppercase transition-colors',
					armDown
						? 'border-fault bg-fault/20 text-fault'
						: 'border-border text-muted-foreground/60 hover:border-fault hover:text-fault'
				)}
				disabled={goingDown}
				onclick={shutdown}
			>
				{armDown ? 'press again to power off' : 'shut down'}
			</button>
		</div>
	</header>

	<main class="flex min-h-0 flex-1 flex-col gap-[clamp(0.5rem,1.4vh,1.1rem)] px-6 py-[1.2vh]">
		<!-- the question, and the controls -->
		<div class="flex shrink-0 flex-wrap items-center justify-between gap-x-8 gap-y-3">
			<h1 class="t-hero max-w-[22ch] font-medium tracking-tight text-balance">
				Is the datacenter really running the model it promised?
			</h1>
			<div class="flex flex-wrap items-center gap-x-6 gap-y-3">
				{@render toggle(armed, 'Tamper', 'fault', () => (armed = !armed))}
				{@render toggle(simForce || !liveWire, 'Simulate', 'caution', () => {
					// off is only offerable when there is a wire to fall back to
					if (liveWire) simForce = !simForce;
				})}
				<button
					class="t-tag border border-border px-4 py-2 font-mono text-muted-foreground uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
					disabled={goingDown}
					onclick={resetAll}>Reset</button
				>
				<button
					class={cn(
						't-lead border border-signal bg-signal/10 px-8 py-2 font-mono tracking-[0.14em] text-signal uppercase transition-colors hover:bg-signal/20 disabled:pointer-events-none disabled:opacity-35',
						!busy && !goingDown && phase !== 'done' && 'ilk-breathe'
					)}
					disabled={busy || goingDown}
					onclick={start}>Prompt</button
				>
			</div>
		</div>

		<!-- never dismissible: nothing here may read as a proof that it is not -->
		<div
			class={cn(
				't-body flex shrink-0 flex-wrap items-baseline gap-x-3 border-l-4 bg-card/60 px-4 py-2 font-mono',
				TONE[banner.tone].bar
			)}
			title={modeRaw}
		>
			<span class={cn('shrink-0 tracking-[0.16em] uppercase', TONE[banner.tone].text)}
				>{banner.tag}</span
			>
			<span class="text-muted-foreground">{banner.say}</span>
		</div>

		<!--
			Two bands: the three machines along the top, the cable underneath them. They
			used to share one line, which put the packet on top of whichever station it
			had reached and covered the label -- exactly at the moment the label matters.
		-->
		<section
			class="relative h-[clamp(118px,18vh,230px)] shrink-0 overflow-hidden border border-border bg-card"
		>
			<div
				class="pointer-events-none absolute inset-0 opacity-50"
				style="background-image:linear-gradient(to right,var(--grid) 1px,transparent 1px),linear-gradient(to bottom,var(--grid) 1px,transparent 1px);background-size:44px 44px"
			></div>

			<!-- a drop from each machine down to the cable it is spliced into -->
			{#each STOP as x (x)}
				<div class="absolute top-[62%] h-[20%] w-px bg-border" style="left:{x}%"></div>
			{/each}

			<!-- the cable itself, and the flow it carries only while there is traffic -->
			<div class="absolute inset-x-[8%] top-[82%] h-px bg-border"></div>
			<div
				class={cn(
					'absolute inset-x-[8%] top-[82%] h-[2px] transition-opacity duration-500',
					pktShown ? 'ilk-flow opacity-80' : 'opacity-0'
				)}
			></div>

			{@render station(STOP[0], 'YOUR MACHINE', 'holds the key', hotHome)}
			{@render station(STOP[1], 'THE CHECKER', 'a chip in the cable', hotFpga)}

			<!-- the far end, which becomes the verdict once there is one -->
			<div
				class={cn(
					'absolute top-[6%] flex h-[56%] -translate-x-1/2 flex-col items-center justify-center gap-1 overflow-hidden border bg-background transition-all duration-500',
					verdict ? 'w-[clamp(180px,21vw,340px)]' : 'w-[clamp(140px,16vw,260px)]',
					verdict
						? verdict.verdict === 'PASS'
							? 'border-verified shadow-[0_0_40px_-4px_var(--verified)]'
							: 'border-fault shadow-[0_0_40px_-4px_var(--fault)]'
						: hotSpark
							? 'border-signal shadow-[0_0_30px_-4px_var(--signal)]'
							: 'border-border'
				)}
				style="left:{STOP[2]}%"
			>
				{#if verdict}
					{@const ok = verdict.verdict === 'PASS'}
					<div
						class={cn(
							'ilk-bloom font-mono text-[clamp(1.15rem,2vw,2.3rem)] leading-none font-bold tracking-[0.08em]',
							ok ? 'text-verified' : 'text-fault'
						)}
					>
						{ok ? 'VERIFIED' : 'REJECTED'}
					</div>
					{#if elapsed}
						<div class="tabular t-tag font-mono text-muted-foreground">proved in {elapsed}</div>
					{/if}
				{:else}
					{#if working}
						<div class="ilk-sweep pointer-events-none absolute inset-x-0 h-1/3 bg-signal/15"></div>
					{/if}
					<div class="t-body font-mono font-semibold tracking-[0.05em]">THE DATACENTER</div>
					<div
						class="t-tag px-2 text-center font-mono leading-tight text-muted-foreground uppercase"
					>
						runs the model
					</div>
				{/if}
			</div>

			<!-- the one thing allowed to use the accent: traffic actually on the cable -->
			<div
				class={cn(
					't-tag absolute top-[82%] z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 border px-3 py-1 font-mono whitespace-nowrap transition-all duration-[900ms] ease-in-out',
					pktSealed
						? 'border-border bg-muted text-muted-foreground'
						: 'border-signal bg-signal/15 text-signal shadow-[0_0_22px_-3px_var(--signal)]',
					pktShown ? 'opacity-100' : 'opacity-0'
				)}
				style="left:{pktX}%"
			>
				<svg
					viewBox="0 0 24 24"
					class="size-[1.15em]"
					fill="none"
					stroke="currentColor"
					stroke-width="2.4"
					aria-hidden="true"
				>
					<rect x="4" y="11" width="16" height="10" rx="1.5" />
					{#if pktSealed}
						<path d="M8 11V7a4 4 0 0 1 8 0v4" />
					{:else}
						<path d="M8 11V7a4 4 0 0 1 7.4-2" />
					{/if}
				</svg>
				{pktLabel}
			</div>
		</section>

		<!-- the three fingerprints, which is the thing worth watching -->
		<FingerprintRegister req={reqFp} rsp={rspFp} model={modelFp} stage={fpStage} />

		<!-- one sentence, and the answer -->
		<div class="flex shrink-0 items-end justify-between gap-8">
			<p class="t-lead max-w-[52ch] text-balance">{caption}</p>
			{#if answer}
				<div class="ilk-bloom flex shrink-0 flex-col items-end gap-1">
					{#if asked}
						<span class="t-body text-muted-foreground">{asked}</span>
					{/if}
					<span class="t-big font-mono font-semibold text-signal">{answer}</span>
				</div>
			{/if}
		</div>
	</main>

	{#if goingDown}
		<div
			class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-background/95 backdrop-blur-sm"
		>
			<span class="t-big font-mono tracking-[0.14em] text-fault uppercase">Powering off</span>
			<p class="t-lead max-w-[34ch] text-center text-muted-foreground">
				Both machines are halting. This screen is served by one of them, so it will go dark.
			</p>
		</div>
	{/if}
</div>
